"""Atomic idempotency claim for Stripe/Coinbase checkout-session creation.

Without this, a double-click or client retry on "Pay with card"/"Pay with
crypto" can create two live Stripe Checkout Sessions / Coinbase charges for
the same cart or order — the guest pays twice, or two redirect URLs race
each other. Same shape as routes/transactions.py's clientOpId dedup and
services/nua_tools.py's execute_tool idempotency-key handling: an atomic
upsert claims the key (MongoDB's unique index decides which of two racing
callers wins, not a Python-side check that could itself race), and a
genuinely concurrent second caller polls briefly for the first caller's
result instead of calling out to the payment provider a second time.

db.payment_session_claims' sparse-unique index on `claimKey` (see
services/db_indexes.py) is the real atomic guard against two concurrent
callers both winning the initial claim.

Deliberately NOT a forever-cache: a claim older than CLAIM_STALE_AFTER_SECONDS
is treated as if it never existed. Without that, a guest whose card was
declined, or who simply abandoned an old Stripe/Coinbase session and comes
back later to pay the same order/split, would be redirected to that same
dead session forever — worse than the duplicate-session bug this module
exists to fix.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from pymongo import ReturnDocument

from database import db


class IdempotencyConflict(Exception):
    """Same idempotency key, materially different request. Per standard
    idempotency-key semantics (Stripe's own included) this must be
    rejected, not silently answered with the first request's result — a
    client bug that reuses a stale key across two different carts/amounts
    would otherwise redirect the guest to pay the WRONG amount with no
    error at all."""


def fingerprint(*parts: Any) -> str:
    """A short, stable hash of the request-defining fields (amount,
    orderId, ...) a caller wants pinned to a given idempotency key.
    Deliberately not the whole request body — fields like originUrl vary
    harmlessly across legitimate retries (redirect flow, different tab)."""
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:16]

CLAIM_STALE_AFTER_SECONDS = 30 * 60  # covers a double-click or a retry after
                                      # a dropped response; short enough that
                                      # a genuinely new attempt later isn't
                                      # stuck replaying a dead session
CLAIM_DOC_TTL_SECONDS = 7 * 24 * 60 * 60  # storage hygiene only — the
                                           # staleness check above is what
                                           # actually governs reuse


def _is_stale(doc: dict) -> bool:
    created = doc.get("createdAt")
    if not created:
        return True
    try:
        created_dt = datetime.fromisoformat(created)
    except ValueError:
        return True
    return (datetime.now(timezone.utc) - created_dt).total_seconds() > CLAIM_STALE_AFTER_SECONDS


async def claim_or_wait(provider: str, key: Optional[str],
                         payload_fingerprint: Optional[str] = None) -> Optional[dict]:
    """Returns None when this call may proceed to create a new session
    (no key given, this call is the first to claim it, or the prior claim
    was stale) — the caller must call record_result once it has one.
    Returns the already-known result ({"url": ..., "sessionId": ...}) when
    a prior, still-fresh call already claimed this exact key.

    payload_fingerprint (see fingerprint() above), when supplied, is
    compared against the fingerprint the FIRST caller for this key
    recorded. A mismatch means the same idempotency key was reused for a
    materially different request (a different amount, a different order)
    — raises IdempotencyConflict rather than silently handing back the
    first request's session, which would redirect the guest to pay the
    wrong amount. Callers that don't pass one skip this check entirely
    (existing behavior, unchanged).

    A claim that never resolves (the first caller crashed after claiming
    but before recording a result) is not blocked on forever: after ~2s
    this gives up waiting and returns None, letting the caller create its
    own session. Favors availability over a stuck request — Stripe/
    Coinbase network calls normally finish well inside that window."""
    if not key:
        return None
    claim_key = f"{provider}:{key}"
    now = datetime.now(timezone.utc)
    prior = await db.payment_session_claims.find_one_and_update(
        {"claimKey": claim_key},
        {"$setOnInsert": {"claimKey": claim_key, "provider": provider, "key": key,
                           "createdAt": now.isoformat(),
                           "expiresAt": now + timedelta(seconds=CLAIM_DOC_TTL_SECONDS),
                           "payloadFingerprint": payload_fingerprint,
                           "result": None}},
        upsert=True, return_document=ReturnDocument.BEFORE,
    )
    if prior is None:
        return None  # we won the claim — proceed to create the session

    if (payload_fingerprint is not None and prior.get("payloadFingerprint") is not None
            and prior["payloadFingerprint"] != payload_fingerprint and not _is_stale(prior)):
        raise IdempotencyConflict(
            f"idempotency key already used for a different request (provider={provider!r})"
        )

    if _is_stale(prior):
        # Old enough that reusing its result would likely redirect to a
        # dead/expired session — refresh the claim in place and proceed as
        # a fresh claim. Not itself atomic against another equally-stale
        # concurrent refresh, but that's the same "gave up waiting, create
        # our own" tradeoff already accepted below — at worst two sessions
        # get created for a retry happening 30+ minutes after the first.
        await db.payment_session_claims.update_one(
            {"claimKey": claim_key},
            {"$set": {"createdAt": now.isoformat(),
                       "expiresAt": now + timedelta(seconds=CLAIM_DOC_TTL_SECONDS),
                       "payloadFingerprint": payload_fingerprint,
                       "result": None}},
        )
        return None

    existing = prior
    for _ in range(20):  # ~2s total
        if existing.get("result") is not None:
            return existing["result"]
        await asyncio.sleep(0.1)
        existing = await db.payment_session_claims.find_one({"claimKey": claim_key}, {"_id": 0})
        if existing is None:
            return None
    return None  # gave up waiting — let this caller create its own session


async def record_result(provider: str, key: Optional[str], result: dict) -> None:
    if not key:
        return
    await db.payment_session_claims.update_one(
        {"claimKey": f"{provider}:{key}"}, {"$set": {"result": result}},
    )
