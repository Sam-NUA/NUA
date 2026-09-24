"""Durable partner webhook delivery with bounded retries and crash recovery.

A resident process must run the lifespan worker. Delivery is at least once:
partners deduplicate the stable event id, including after ambiguous timeouts.
The booking write and emit are still separate operations (see architecture).
"""
import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

from database import db

logger = logging.getLogger("bookings.webhooks")
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = [2, 8, 30]
LEASE_SECONDS = 60
CAPTURE: Optional[list] = None
_worker: Optional[asyncio.Task] = None


def _now():
    return datetime.now(timezone.utc)


async def emit(partner: dict, event: str, payload: dict) -> None:
    now = _now().isoformat()
    doc = {
        "id": f"WHK-{uuid.uuid4().hex}",
        "partner_id": partner["id"], "url": partner.get("webhook_url"),
        "event": event, "payload": payload,
        "status": "pending" if partner.get("webhook_url") else "skipped_no_url",
        "attempts": 0, "created_at": now, "next_attempt_at": now,
    }
    if CAPTURE is not None:
        CAPTURE.append({"event": event, "payload": payload, "partner_id": partner["id"]})
        doc["status"] = "delivered"
    await db.webhook_outbox.insert_one(doc)


async def deliver_next() -> bool:
    """Claim and deliver one due event. Multiple workers may call safely.

    Claims use Mongo's atomic find-and-update; acknowledgements require the
    same token. Expired leases recover after process termination. A crashed
    final attempt is marked failed for operator reconciliation, never lost.
    """
    now = _now()
    stamp = now.isoformat()
    await db.webhook_outbox.update_many(
        {"status": "delivering", "lease_until": {"$lte": stamp},
         "attempts": {"$gte": MAX_ATTEMPTS}},
        {"$set": {"status": "failed", "last_error": "delivery_outcome_unknown"},
         "$unset": {"claim_token": "", "lease_until": ""}},
    )
    token = uuid.uuid4().hex
    doc = await db.webhook_outbox.find_one_and_update(
        {"attempts": {"$lt": MAX_ATTEMPTS}, "$or": [
            {"status": {"$in": ["pending", "retrying"]}, "$or": [
                {"next_attempt_at": {"$lte": stamp}},
                {"next_attempt_at": {"$exists": False}},
            ]},
            {"status": "delivering", "lease_until": {"$lte": stamp}},
        ]},
        {"$set": {"status": "delivering", "claim_token": token,
                  "lease_until": (now + timedelta(seconds=LEASE_SECONDS)).isoformat()},
         "$inc": {"attempts": 1}},
        sort=[("created_at", 1)], return_document=True,
    )
    if doc is None:
        return False
    state = {"status": "delivered", "last_error": None}
    if not doc.get("url"):
        state["status"] = "skipped_no_url"
    else:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(doc["url"], json={
                    "id": doc["id"], "event": doc["event"], "created_at": doc["created_at"],
                    "data": doc["payload"],
                })
            if not 200 <= response.status_code < 300:
                state["last_error"] = f"http_{response.status_code}"
                retryable = response.status_code in (408, 429) or response.status_code >= 500
                state["status"] = "retrying" if retryable else "failed"
        except httpx.HTTPError as exc:
            state = {"status": "retrying", "last_error": type(exc).__name__}
        if state["status"] == "retrying":
            if doc["attempts"] >= MAX_ATTEMPTS:
                state["status"] = "failed"
            else:
                state["next_attempt_at"] = (
                    _now() + timedelta(seconds=BACKOFF_SECONDS[doc["attempts"] - 1])
                ).isoformat()
    await db.webhook_outbox.update_one(
        {"_id": doc["_id"], "claim_token": token},
        {"$set": state, "$unset": {"claim_token": "", "lease_until": ""}},
    )
    return True


async def _run():
    while True:
        try:
            # Bounded batch gives shutdown and other event-loop work a turn.
            for _ in range(20):
                if not await deliver_next():
                    break
        except Exception:
            logger.exception("Webhook worker iteration failed")
        await asyncio.sleep(1)


async def start_worker():
    global _worker
    await db.webhook_outbox.create_index([("status", 1), ("next_attempt_at", 1)])
    await db.webhook_outbox.create_index([("status", 1), ("lease_until", 1)])
    if _worker is None or _worker.done():
        _worker = asyncio.create_task(_run())


async def stop_worker():
    global _worker
    if _worker is not None:
        _worker.cancel()
        try:
            await _worker
        except asyncio.CancelledError:
            pass
        _worker = None
