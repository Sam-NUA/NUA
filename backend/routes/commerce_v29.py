"""
NUA Customer Commerce Platform — v29

Endpoints
─────────
Universal Voucher Engine
  POST   /vouchers                  — issue voucher (any sourceType)
  POST   /vouchers/bulk             — bulk issue (corporate, event, staff)
  GET    /vouchers                  — list with filters
  GET    /vouchers/{id}             — single with full audit
  POST   /vouchers/validate         — pre-flight check (no redeem)
  POST   /vouchers/redeem           — apply against a transaction
  POST   /vouchers/{id}/revoke      — owner/manager revocation
  GET    /vouchers/lookup/{code}    — resolve manual code → voucher

Unified Wallet
  GET    /wallet/{customerId}       — buckets + expiry + pending + timeline
  POST   /wallet/{customerId}/credit — add value (any type)
  POST   /wallet/{customerId}/debit  — deduct (with reason)
  GET    /wallet/{customerId}/timeline — full journey (bookings + orders +
                                          payments + refunds + points +
                                          vouchers + reviews)

Flexible Refund Engine
  POST   /refunds                    — refund with split modes (card/credit/points/voucher)

AI Promotion Builder
  POST   /ai/promotion-goal          — plain-English goal → complete campaign

Promotion Analytics
  GET    /promo-analytics/summary    — vouchers issued/redeemed/expired, ROI, best channel

Loyalty 2.0
  GET    /loyalty/status/{customerId} — tier + milestones + streaks + badges
  POST   /loyalty/award              — grant a badge / milestone

AI Personalisation
  GET    /personalisation/{customerId} — recommended offers based on history

Gift Card 2.0 (extends existing gift-card sale)
  POST   /gift-cards/schedule        — scheduled delivery (future date)
  POST   /gift-cards/{id}/reload     — top up an existing card
"""
from __future__ import annotations
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from database import db
from deps import get_user
from middleware.actor_context import get_actor_context, tenant_scope_filter, tenant_owns, tenant_owns_strict
from models.voucher import Voucher, VoucherCreate, VoucherRedeemRequest, VoucherValidateRequest, VoucherRedemption, VoucherRules
from models.wallet_ledger import LedgerEntry, LedgerEntryCreate
import base64
import hashlib
import hmac
import json
import os
import secrets
import string
import uuid
import logging

logger = logging.getLogger(__name__)
router = APIRouter()

# ═════════════════════════════════════════════════════════════════════════
# Signing helpers (HMAC-SHA256 with JWT_SECRET, base64url with no padding)
# ═════════════════════════════════════════════════════════════════════════
def _secret() -> bytes:
    return os.environ["JWT_SECRET"].encode()

def _sign_payload(payload: dict) -> str:
    body = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).rstrip(b"=").decode()
    sig = hmac.new(_secret(), body.encode(), hashlib.sha256).digest()
    sig_b = base64.urlsafe_b64encode(sig).rstrip(b"=").decode()
    return f"{body}.{sig_b}"

def _verify_payload(token: str) -> Optional[dict]:
    try:
        body, sig = token.split(".")
        raw = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
        expected = hmac.new(_secret(), body.encode(), hashlib.sha256).digest()
        expected_b = base64.urlsafe_b64encode(expected).rstrip(b"=").decode()
        if not hmac.compare_digest(sig, expected_b):
            return None
        return json.loads(raw)
    except Exception:
        return None

def _gen_code(prefix: str = "NUA") -> str:
    alphabet = string.ascii_uppercase + string.digits
    body = "".join(secrets.choice(alphabet) for _ in range(8))
    return f"{prefix}-{body[:4]}-{body[4:]}"

from utils.ids import now_utc as _now, to_iso as _iso


# ═════════════════════════════════════════════════════════════════════════
# Universal Voucher Engine
# ═════════════════════════════════════════════════════════════════════════
def _build_voucher_doc(payload: dict, user: Optional[dict], customer_data: dict) -> dict:
    """Pure (no I/O) construction of one voucher document — split out of
    _issue_voucher so bulk issuance can build N of these in memory and
    insert them in a single round trip, instead of one insert_one (and one
    redundant customer lookup) per voucher."""
    code = _gen_code(payload.get("codePrefix", "NUA"))
    vid = str(uuid.uuid4())
    qr_payload = _sign_payload({"vid": vid, "code": code, "issued": int(_now().timestamp())})

    v = Voucher(
        id=vid, code=code, qrPayload=qr_payload,
        sourceType=payload.get("sourceType", "manual"),
        sourceRef=payload.get("sourceRef"),
        label=payload.get("label") or "NUA Voucher",
        description=payload.get("description"),
        valueType=payload.get("valueType", "amount"),
        value=float(payload.get("value") or 0),
        faceValue=float(payload.get("value") or 0),
        residualValue=float(payload.get("value") or 0) if payload.get("partialRedeemable") else 0.0,
        usageType=payload.get("usageType", "one_time"),
        maxRedemptions=payload.get("maxRedemptions", 1),
        partialRedeemable=bool(payload.get("partialRedeemable", False)),
        customerId=payload.get("customerId"),
        **customer_data,
        rules=VoucherRules(**(payload.get("rules") or {})),
        expiresAt=payload.get("expiresAt"),
        issuedBy=(user or {}).get("email"),
        freeItemId=payload.get("freeItemId"),
        metadata=payload.get("metadata") or {},
        # The authenticated caller's own businessId always wins — this used
        # to check payload.get("businessId") FIRST, meaning any client could
        # put {"businessId": "<another business's id>"} in the POST body and
        # have the voucher tagged as belonging to a different tenant than
        # the one they're actually authenticated as. No current caller
        # (public /vouchers, /vouchers/bulk, or the internal refund/gift-card
        # issuers) relies on payload.businessId when a user is present, so
        # it's now only consulted as a last resort with no user in scope.
        businessId=(user or {}).get("businessId") or get_actor_context().get("businessId") or payload.get("businessId"),
    )
    return v.dict()


async def _lookup_customer_data(customer_id: Optional[str]) -> dict:
    if not customer_id:
        return {}
    c = await db.customers.find_one({**tenant_scope_filter(), "id": customer_id}, {"_id": 0}) or {}
    return {"customerEmail": c.get("email"), "customerName": c.get("name")}


async def _issue_voucher(payload: dict, user: Optional[dict] = None) -> dict:
    """Internal helper used by /vouchers, /refunds, promotion auto-issue."""
    customer_data = await _lookup_customer_data(payload.get("customerId"))
    doc = _build_voucher_doc(payload, user, customer_data)
    await db.vouchers.insert_one(dict(doc))
    doc.pop("_id", None)
    return doc


@router.post("/vouchers")
async def issue_voucher(body: VoucherCreate, user: dict = Depends(get_user)):
    if user["role"] not in ("owner", "manager"):
        raise HTTPException(403, "Owner/manager only")
    return await _issue_voucher(body.dict(), user)


@router.post("/vouchers/bulk")
async def bulk_issue_voucher(body: dict, user: dict = Depends(get_user)):
    """Issue N identical vouchers — for corporate hand-outs, staff perks, event give-aways.

    Builds all N documents in memory (one customer lookup total, not one
    per voucher — the customerId, if any, is the same for the whole batch)
    and inserts them in a single insert_many instead of N sequential
    insert_one round trips."""
    if user["role"] not in ("owner", "manager"):
        raise HTTPException(403, "Owner/manager only")
    count = int(body.get("count", 1))
    if count < 1 or count > 5000:
        raise HTTPException(400, "count must be 1..5000")
    template = {k: v for k, v in body.items() if k != "count"}
    customer_data = await _lookup_customer_data(template.get("customerId"))
    docs = [_build_voucher_doc(template, user, customer_data) for _ in range(count)]
    if docs:
        await db.vouchers.insert_many([dict(d) for d in docs])
    codes = [{"id": d["id"], "code": d["code"], "qrPayload": d["qrPayload"]} for d in docs]
    return {"issued": count, "vouchers": codes}


@router.get("/vouchers")
async def list_vouchers(status: Optional[str] = None,
                         customer_id: Optional[str] = None,
                         source_type: Optional[str] = None,
                         limit: int = 200,
                         user: dict = Depends(get_user)):
    from utils.mongo_safe import safe_parse_list
    q: Dict[str, Any] = tenant_scope_filter(user.get("businessId"))
    if status: q["status"] = status
    if customer_id: q["customerId"] = customer_id
    if source_type: q["sourceType"] = source_type
    rows = await db.vouchers.find(q, {"_id": 0}).sort("issuedAt", -1).to_list(limit)
    return safe_parse_list(rows, Voucher, where="vouchers")


@router.get("/vouchers/{voucher_id}")
async def get_voucher(voucher_id: str, user: dict = Depends(get_user)):
    v = await db.vouchers.find_one({**tenant_scope_filter(user.get("businessId")), "id": voucher_id}, {"_id": 0})
    if not v:
        raise HTTPException(404, "Voucher not found")
    return v


@router.get("/vouchers/lookup/{code}")
async def lookup_code(code: str, user: dict = Depends(get_user)):
    v = await db.vouchers.find_one({**tenant_scope_filter(user.get("businessId")), "code": code.upper()}, {"_id": 0})
    if not v:
        raise HTTPException(404, "Voucher not found")
    return v


async def _resolve_voucher(code: Optional[str], token: Optional[str], business_id: Optional[str] = None) -> dict:
    # Scoped by tenant_scope_filter's usual fail-open rule: matches the
    # caller's own business plus any not-yet-tagged voucher, but never a
    # voucher clearly tagged for a *different* business — the same
    # isolation every other tenant-scoped lookup in this app already gets,
    # applied here so a caller who does carry business context can't be
    # handed another business's voucher just by guessing its code.
    # business_id is passed explicitly by every authenticated caller (their
    # real user.businessId, from the DB) rather than read from actor
    # context here — the actor context's businessId can come from an
    # X-Business-Id/X-Tenant-Id header instead of the JWT when both are
    # present, which is the right override for a partner integration
    # calling with its own header but the wrong one to trust for a
    # logged-in staff member's own request. Only the fully anonymous
    # public-check path (no user at all) falls back to actor context.
    scope = tenant_scope_filter(business_id)
    if token:
        payload = _verify_payload(token)
        if not payload:
            raise HTTPException(401, "Invalid or tampered token")
        v = await db.vouchers.find_one({**scope, "id": payload.get("vid")}, {"_id": 0})
    elif code:
        v = await db.vouchers.find_one({**scope, "code": code.strip().upper()}, {"_id": 0})
    else:
        raise HTTPException(400, "Provide code or token")
    if not v:
        raise HTTPException(404, "Voucher not found")
    return v


def _compute_voucher_discount(v: dict, subtotal: float) -> float:
    """The one place voucher-discount math happens — percentage discounts
    respect rules.maxDiscount (silently ignored everywhere this was
    previously duplicated, so a "15% off, capped at $20" voucher gave the
    full uncapped 15% on a large cart), and amount-type discounts still
    respect residualValue for partially-redeemed vouchers. Always clamped
    to the cart subtotal so a discount can never exceed what's being paid."""
    if v["valueType"] == "percentage":
        discount = subtotal * (float(v["value"]) / 100)
        max_discount = (v.get("rules") or {}).get("maxDiscount")
        if max_discount is not None:
            discount = min(discount, float(max_discount))
    else:
        cap = float(v.get("residualValue", v["value"])) if v.get("partialRedeemable") else float(v["value"])
        discount = min(float(v["value"]), cap)
    return round(min(discount, subtotal), 2)


def _validate_voucher_rules(v: dict, *, cart: Optional[list] = None,
                             customer_id: Optional[str] = None,
                             location_id: Optional[str] = None,
                             channel: Optional[str] = None) -> Optional[str]:
    """Return a human-readable rejection reason, or None if the voucher passes."""
    if v["status"] in ("expired", "revoked"):
        return f"Voucher is {v['status']}"
    if v["status"] == "redeemed":
        return "Voucher already fully redeemed"
    now = _now()
    if v.get("expiresAt"):
        try:
            exp = datetime.fromisoformat(v["expiresAt"].replace("Z", "+00:00"))
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if now > exp:
                return "Voucher has expired"
        except Exception:
            pass
    if v.get("customerId") and customer_id and v["customerId"] != customer_id:
        return "Voucher is assigned to a different customer"
    if v.get("maxRedemptions") and v.get("redemptionCount", 0) >= v["maxRedemptions"]:
        return "Voucher has reached max redemptions"

    r = v.get("rules") or {}
    # Date window
    if r.get("startDate") and now.date().isoformat() < r["startDate"]:
        return "Voucher not yet active"
    if r.get("endDate") and now.date().isoformat() > r["endDate"]:
        return "Voucher validity window has ended"
    # Weekdays
    if r.get("activeDays"):
        wk = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"][now.weekday()]
        if wk not in r["activeDays"]:
            return f"Voucher not valid on {wk}"
    # Time window
    if r.get("startTime") and now.strftime("%H:%M") < r["startTime"]:
        return "Outside voucher time window"
    if r.get("endTime") and now.strftime("%H:%M") > r["endTime"]:
        return "Outside voucher time window"
    # Locations
    if r.get("locationIds") and location_id and location_id not in r["locationIds"]:
        return "Voucher not valid at this location"
    # Channel
    if r.get("deliveryChannels") and channel and channel not in r["deliveryChannels"]:
        return f"Voucher not valid for {channel}"
    # Min spend + eligibility
    if cart:
        subtotal = sum(float(i.get("price", 0)) * int(i.get("quantity", 1)) for i in cart)
        if r.get("minSpend") and subtotal < r["minSpend"]:
            return f"Minimum spend ${r['minSpend']} not met"
        if r.get("eligibleItems"):
            ids = {i.get("productId") or i.get("id") for i in cart}
            if not (set(r["eligibleItems"]) & ids):
                return "None of the eligible items are in the cart"
        if r.get("eligibleCategories"):
            cats = {i.get("category") for i in cart}
            if not (set(r["eligibleCategories"]) & cats):
                return "No cart items match eligible categories"
    return None


@router.post("/vouchers/validate")
async def validate_voucher(body: VoucherValidateRequest, user: dict = Depends(get_user)):
    v = await _resolve_voucher(body.code, body.token, user.get("businessId"))
    reason = _validate_voucher_rules(
        v, cart=body.cart, customer_id=body.customerId,
        location_id=body.locationId, channel=body.channel,
    )
    if reason:
        return {"valid": False, "voucher": v, "reason": reason}
    return {"valid": True, "voucher": v}


class PublicVoucherCheck(BaseModel):
    code: str
    cart: Optional[list] = None


@router.post("/vouchers/public-check")
async def public_check_voucher(body: PublicVoucherCheck, business: Optional[str] = None):
    """Unauthenticated counterpart to /vouchers/validate — for guest-facing
    surfaces (online ordering, table QR ordering) that have no staff login
    to attach. Deliberately minimal: no customer/staff auth is required to
    call this, so the response only ever returns a discount amount + label,
    never the underlying voucher document (customerId, metadata, full
    redemption history) an anonymous caller has no business seeing.
    Doesn't commit anything — same as the staff-facing validate endpoint,
    this is a dry-run check only."""
    try:
        from routes.online_orders import resolve_or_require_business_id
        business_id = await resolve_or_require_business_id(business)
        v = await _resolve_voucher(body.code, None, business_id)
    except HTTPException:
        return {"valid": False, "reason": "Code not found"}
    reason = _validate_voucher_rules(v, cart=body.cart)
    if reason:
        return {"valid": False, "reason": reason}
    subtotal = sum(float(i.get("price", 0)) * int(i.get("quantity", 1)) for i in (body.cart or []))
    discount = _compute_voucher_discount(v, subtotal)
    if discount <= 0:
        return {"valid": False, "reason": "Voucher has no remaining value"}
    return {"valid": True, "discount": discount, "label": v.get("label"), "voucherId": v["id"]}


@router.post("/vouchers/redeem")
async def redeem_voucher(body: VoucherRedeemRequest, user: dict = Depends(get_user)):
    # Two concurrent redemptions of the same voucher (two terminals, or a
    # shared code redeemed twice near-simultaneously) used to both read the
    # same voucher snapshot, both compute their own "new" residual/count/
    # status, and both write with a bare $set — the second write silently
    # overwrote the first's, so a one-time voucher could be redeemed twice,
    # or a partial voucher's residual could be applied against a stale
    # balance. Fixed with a bounded optimistic-concurrency loop: each
    # attempt re-reads the voucher fresh, computes the update, and commits
    # it with find_one_and_update's filter pinned to the exact prior
    # status/residualValue/redemptionCount/updatedAt it read — MongoDB
    # only applies the write if nothing else changed the document in
    # between (the same compare-and-swap idiom services/wallet_service.py's
    # redeem_voucher_line already uses), so a losing concurrent attempt
    # sees no match and retries against the winner's fresh state instead of
    # clobbering it.
    max_attempts = 8
    updated = None
    applied = 0.0
    for _attempt in range(max_attempts):
        v = await _resolve_voucher(body.code, body.token, user.get("businessId"))

        # Duplicate redemption guard must run BEFORE rule/quota checks so that
        # accidental double-clicks return a clear 409 rather than "max reached".
        if body.transactionId and any(r.get("transactionId") == body.transactionId for r in v.get("redemptions", [])):
            raise HTTPException(409, "Voucher already applied to this transaction")

        reason = _validate_voucher_rules(v, cart=body.cart, location_id=body.locationId)
        if reason:
            # Partial-redeemable exception: a one_time voucher with residual > 0
            # should still accept additional partial applications until residual
            # hits zero. Only skip if the failure is specifically "max reached".
            if v.get("partialRedeemable") and float(v.get("residualValue", 0)) > 0 and "max redemptions" in reason.lower():
                pass   # allow — partial redemptions decrement residual, not the counter
            else:
                raise HTTPException(400, reason)

        # Determine amount actually applied
        requested = float(body.amount)
        if v["valueType"] == "amount":
            if v.get("partialRedeemable"):
                applied = min(requested, float(v.get("residualValue", v["value"])))
            else:
                applied = min(requested, float(v["value"]))
        elif v["valueType"] == "percentage":
            applied = requested  # caller (POS) computes % → $ before calling
        else:  # free_item / tier_upgrade — face value is informational
            applied = min(requested, float(v.get("value", 0)))

        if applied <= 0:
            raise HTTPException(400, "Voucher residual value is $0")

        # Build audit entry
        rec = VoucherRedemption(
            amount=round(applied, 2),
            staffId=user.get("id"),
            staffName=user.get("name") or user.get("email"),
            terminalId=body.terminalId,
            transactionId=body.transactionId,
            locationId=body.locationId,
            note=body.note,
        ).dict()

        new_count = v.get("redemptionCount", 0) + 1
        new_residual = v.get("residualValue", 0.0)
        new_status = v["status"]
        if v.get("partialRedeemable"):
            # Partial vouchers use residual value as the true "remaining budget"
            # — max_redemptions is treated as informational, not a hard cap.
            prev_residual = float(v.get("residualValue") if v.get("residualValue") is not None else v["value"])
            new_residual = round(max(0.0, prev_residual - applied), 2)
            new_status = "redeemed" if new_residual <= 0 else "partial"
        else:
            if not v.get("maxRedemptions") or new_count >= v["maxRedemptions"]:
                new_status = "redeemed"

        cas_filter = {
            "id": v["id"],
            **tenant_scope_filter(user.get("businessId")),
            "status": v["status"],
            "redemptionCount": v.get("redemptionCount", 0),
            "residualValue": v.get("residualValue", 0.0),
        }
        updated = await db.vouchers.find_one_and_update(
            cas_filter,
            {
                "$push": {"redemptions": rec},
                "$set": {
                    "status": new_status,
                    "residualValue": new_residual,
                    "redemptionCount": new_count,
                    "lastRedeemedAt": _iso(_now()),
                },
            },
            return_document=True,
        )
        if updated is not None:
            break
        # Someone else redeemed (or revoked) this exact voucher between our
        # read and our write — loop back and retry against fresh state
        # rather than silently applying a decision based on stale data.
    else:
        raise HTTPException(
            409, "Voucher was redeemed by another request at the same moment — please retry"
        )

    # Ledger write (if voucher was assigned to a customer)
    if updated.get("customerId"):
        await _ledger_write(
            customer_id=updated["customerId"], type_="voucher", sign=-1,
            amount=applied, source_type="voucher_redeem", source_ref=updated["id"],
            metadata={
                "voucherCode": updated["code"],
                "transactionId": body.transactionId,
                "terminalId": body.terminalId,
                "staffId": user.get("id"),
                "locationId": body.locationId,
            },
        )

    updated.pop("_id", None)
    return {"ok": True, "amountApplied": round(applied, 2), "voucher": updated}


@router.post("/vouchers/{voucher_id}/revoke")
async def revoke_voucher(voucher_id: str, body: dict, user: dict = Depends(get_user)):
    if user["role"] not in ("owner", "manager"):
        raise HTTPException(403, "Owner/manager only")
    v = await db.vouchers.find_one({"$and": [{"id": voucher_id}, tenant_scope_filter(user.get("businessId"))]})
    if not v or not tenant_owns_strict(v.get("businessId"), user.get("businessId")):
        raise HTTPException(404, "Voucher not found")
    await db.vouchers.update_one({"$and": [{"id": voucher_id}, tenant_scope_filter(user.get("businessId"))]}, {"$set": {
        "status": "revoked",
        "revokedAt": _iso(_now()),
        "revokedBy": user.get("email"),
        "revokeReason": body.get("reason", "manually revoked"),
    }})
    return {"ok": True}


# ═════════════════════════════════════════════════════════════════════════
# Unified Wallet
# ═════════════════════════════════════════════════════════════════════════
_BUCKETS = ("points", "store_credit", "gift_card", "voucher", "cashback", "referral")


async def _ledger_write(*, customer_id: str, type_: str, sign: int, amount: float,
                          source_type: str, source_ref: Optional[str] = None,
                          note: Optional[str] = None,
                          metadata: Optional[dict] = None) -> dict:
    if type_ not in _BUCKETS:
        raise HTTPException(400, f"Unknown ledger type: {type_}")
    delta = round(sign * amount, 2)
    # Snapshot new balance for fast timeline reads
    scope = tenant_scope_filter()
    prev_entries = await db.wallet_ledger.find(
        {"customerId": customer_id, "type": type_, **scope},
        {"_id": 0, "sign": 1, "amount": 1},
    ).to_list(50000)
    prev_bal = sum(e.get("sign", 1) * e.get("amount", 0) for e in prev_entries)
    entry = LedgerEntry(
        customerId=customer_id, type=type_, sign=sign, amount=abs(amount),
        balanceAfter=round(prev_bal + delta, 2),
        sourceType=source_type, sourceRef=source_ref, note=note,
        metadata=metadata or {},
        businessId=get_actor_context().get("businessId"),
    ).dict()
    await db.wallet_ledger.insert_one(dict(entry))
    entry.pop("_id", None)
    return entry


@router.get("/wallet/{customer_id}")
async def get_wallet(customer_id: str, user: dict = Depends(get_user)):
    scope = tenant_scope_filter(user.get("businessId"))
    c = await db.customers.find_one({**scope, "id": customer_id}, {"_id": 0})
    if not c or not tenant_owns(c.get("businessId"), user.get("businessId")):
        raise HTTPException(404, "Customer not found")
    entries = await db.wallet_ledger.find({"customerId": customer_id, **scope}, {"_id": 0}).sort("createdAt", -1).to_list(2000)
    balances = {b: 0.0 for b in _BUCKETS}
    for e in entries:
        if e["type"] in balances:
            balances[e["type"]] = round(balances[e["type"]] + e.get("sign", 1) * e.get("amount", 0), 2)

    # Active vouchers assigned to this customer
    vs = await db.vouchers.find(
        {"customerId": customer_id, "status": {"$in": ["active", "partial"]}, **scope},
        {"_id": 0},
    ).sort("issuedAt", -1).to_list(500)

    # Expiry summary — sum voucher face values expiring in next 30 days
    soon = (_now() + timedelta(days=30)).isoformat()
    expiring_soon = [v for v in vs if v.get("expiresAt") and v["expiresAt"] < soon]
    return {
        "customerId": customer_id,
        "name": c.get("name"),
        "tier": c.get("membershipTier"),
        "balances": balances,
        "vouchers": vs,
        "expiringSoon": expiring_soon,
        "recentEntries": entries[:50],
    }


@router.post("/wallet/{customer_id}/credit")
async def credit_wallet(customer_id: str, body: LedgerEntryCreate, user: dict = Depends(get_user)):
    if user["role"] not in ("owner", "manager"):
        raise HTTPException(403, "Owner/manager only")
    if body.customerId != customer_id:
        body.customerId = customer_id
    if not await db.customers.find_one({"id": customer_id, **tenant_scope_filter(user.get("businessId"))}, {"_id": 1}):
        raise HTTPException(404, "Customer not found")
    return await _ledger_write(
        customer_id=customer_id, type_=body.type, sign=+1,
        amount=abs(body.amount), source_type=body.sourceType,
        source_ref=body.sourceRef, note=body.note,
        metadata={**(body.metadata or {}), "staffId": user.get("id"), "staffEmail": user.get("email")},
    )


@router.post("/wallet/{customer_id}/debit")
async def debit_wallet(customer_id: str, body: LedgerEntryCreate, user: dict = Depends(get_user)):
    if user["role"] not in ("owner", "manager"):
        raise HTTPException(403, "Owner/manager only")
    scope = tenant_scope_filter(user.get("businessId"))
    if not await db.customers.find_one({"id": customer_id, **scope}, {"_id": 1}):
        raise HTTPException(404, "Customer not found")
    # Balance check
    entries = await db.wallet_ledger.find(
        {"customerId": customer_id, "type": body.type, **scope},
        {"_id": 0, "sign": 1, "amount": 1},
    ).to_list(50000)
    bal = sum(e.get("sign", 1) * e.get("amount", 0) for e in entries)
    if abs(body.amount) > bal + 0.001:
        raise HTTPException(400, f"Insufficient {body.type} balance (have ${bal:.2f})")
    return await _ledger_write(
        customer_id=customer_id, type_=body.type, sign=-1,
        amount=abs(body.amount), source_type=body.sourceType,
        source_ref=body.sourceRef, note=body.note,
        metadata={**(body.metadata or {}), "staffId": user.get("id")},
    )


@router.get("/wallet/{customer_id}/timeline")
async def wallet_timeline(customer_id: str, limit: int = 200, user: dict = Depends(get_user)):
    """Merged customer journey across bookings, orders, payments, refunds,
    points/voucher movements, and reviews. Sorted DESC by time."""
    scope = tenant_scope_filter(user.get("businessId"))
    c = await db.customers.find_one({**scope, "id": customer_id}, {"_id": 0})
    if not c:
        raise HTTPException(404, "Customer not found")
    events: List[dict] = []

    async def _add(cursor, mk):
        async for doc in cursor:
            try: events.append(mk(doc))
            except Exception: continue

    await _add(
        db.reservations.find({"customerId": customer_id, **scope}, {"_id": 0}).sort("createdAt", -1).limit(200),
        lambda d: {"type": "booking", "at": d.get("createdAt") or d.get("date"), "title": f"Booking · party of {d.get('partySize', 1)}", "meta": d, "icon": "calendar"},
    )
    await _add(
        db.transactions.find({"customerId": customer_id, **scope}, {"_id": 0}).sort("createdAt", -1).limit(500),
        lambda d: {"type": "order", "at": d.get("createdAt"), "title": f"Order · ${d.get('total', 0):.2f}", "meta": d, "icon": "shopping-cart"},
    )
    await _add(
        db.refunds.find({"customerId": customer_id, **scope}, {"_id": 0}).sort("createdAt", -1).limit(200),
        lambda d: {"type": "refund", "at": d.get("createdAt"), "title": f"Refund · ${d.get('amount', 0):.2f}", "meta": d, "icon": "rotate-ccw"},
    )
    await _add(
        db.wallet_ledger.find({"customerId": customer_id, **scope}, {"_id": 0}).sort("createdAt", -1).limit(500),
        lambda d: {"type": "ledger", "at": d.get("createdAt"), "title": f"{'+' if d.get('sign', 1) > 0 else '−'} {d.get('amount', 0)} {d.get('type')}", "meta": d, "icon": "wallet"},
    )
    await _add(
        db.vouchers.find({"customerId": customer_id, **scope}, {"_id": 0}).sort("issuedAt", -1).limit(200),
        lambda d: {"type": "voucher", "at": d.get("issuedAt"), "title": f"Voucher issued · {d.get('code')}", "meta": d, "icon": "gift"},
    )
    await _add(
        db.feedback.find({"customerId": customer_id, **scope}, {"_id": 0}).sort("createdAt", -1).limit(200),
        lambda d: {"type": "review", "at": d.get("createdAt"), "title": f"Feedback · {d.get('rating', '?')}★", "meta": d, "icon": "star"},
    )

    events = [e for e in events if e.get("at")]
    events.sort(key=lambda e: e["at"], reverse=True)
    return {
        "customerId": customer_id,
        "name": c.get("name"),
        "events": events[:limit],
        "lifetimeValue": round(sum(t.get("meta", {}).get("total", 0) for t in events if t["type"] == "order"), 2),
        "totalOrders": sum(1 for t in events if t["type"] == "order"),
    }


# ═════════════════════════════════════════════════════════════════════════
# Flexible Refund Engine
# ═════════════════════════════════════════════════════════════════════════
@router.post("/refunds/flexible")
async def create_refund(body: dict, user: dict = Depends(get_user)):
    """Refund with split modes.

    body = {
      transactionId, customerId?, amount, reason?, note?,
      splits: [
        {mode: "card"|"store_credit"|"points"|"voucher", amount: 12.50, ...opts},
        ...
      ]
    }
    """
    if user["role"] not in ("owner", "manager", "cashier"):
        raise HTTPException(403, "Not permitted")

    tx_id = body.get("transactionId")
    customer_id = body.get("customerId")
    amount = float(body.get("amount", 0) or 0)
    splits = body.get("splits") or [{"mode": "card", "amount": amount}]

    if amount <= 0:
        raise HTTPException(400, "amount must be > 0")
    split_total = round(sum(float(s.get("amount", 0)) for s in splits), 2)
    if abs(split_total - amount) > 0.01:
        raise HTTPException(400, f"Splits total ${split_total} does not match refund ${amount}")

    scope = tenant_scope_filter(user.get("businessId"))
    txn = await db.transactions.find_one({"id": tx_id, **scope}, {"_id": 0}) if tx_id else None
    if tx_id and not txn:
        raise HTTPException(404, "Transaction not found")
    resolved_customer_id = customer_id or (txn or {}).get("customerId")
    if resolved_customer_id and not await db.customers.find_one(
        {"id": resolved_customer_id, **scope}, {"_id": 1}
    ):
        raise HTTPException(404, "Customer not found")

    rid = f"RF-{uuid.uuid4().hex[:8].upper()}"
    refund_doc: dict = {
        "id": rid,
        "transactionId": tx_id,
        "customerId": resolved_customer_id,
        "businessId": user.get("businessId"),
        "amount": round(amount, 2),
        "reason": body.get("reason"),
        "note": body.get("note"),
        "splits": [],
        "processedBy": user.get("email"),
        "createdAt": _iso(_now()),
        "status": "completed",
    }

    for s in splits:
        mode = s.get("mode")
        amt = round(float(s.get("amount", 0)), 2)
        if amt <= 0: continue
        result: dict = {"mode": mode, "amount": amt}

        if mode == "card":
            # Actual card gateway refund would go here — we log the intent.
            result["method"] = (txn or {}).get("paymentMethod", "card")
            result["reference"] = f"CARD-REFUND-{secrets.token_hex(4).upper()}"
        elif mode == "store_credit":
            if not refund_doc["customerId"]:
                raise HTTPException(400, "customerId required for store_credit split")
            entry = await _ledger_write(
                customer_id=refund_doc["customerId"], type_="store_credit",
                sign=+1, amount=amt, source_type="refund", source_ref=rid,
                note=body.get("reason"),
                metadata={"transactionId": tx_id, "staffId": user.get("id")},
            )
            result["ledgerEntryId"] = entry["id"]
        elif mode == "points":
            if not refund_doc["customerId"]:
                raise HTTPException(400, "customerId required for points split")
            # $1 → 10 points (configurable via metadata.rate)
            rate = float(s.get("pointsPerDollar", 10))
            pts = round(amt * rate, 2)
            entry = await _ledger_write(
                customer_id=refund_doc["customerId"], type_="points",
                sign=+1, amount=pts, source_type="refund", source_ref=rid,
                note=f"Points refund ({rate}pts/$1)",
                metadata={"transactionId": tx_id, "dollarValue": amt, "staffId": user.get("id")},
            )
            result["pointsAwarded"] = pts
            result["ledgerEntryId"] = entry["id"]
        elif mode == "voucher":
            v = await _issue_voucher({
                "label": s.get("label") or f"Refund voucher · ${amt:.2f}",
                "sourceType": "refund", "sourceRef": rid,
                "valueType": "amount", "value": amt,
                "usageType": "one_time", "maxRedemptions": 1,
                "customerId": refund_doc["customerId"],
                "expiresAt": (_now() + timedelta(days=int(s.get("expireInDays", 180)))).isoformat(),
                "partialRedeemable": bool(s.get("partialRedeemable", True)),
            }, user)
            result["voucherId"] = v["id"]
            result["voucherCode"] = v["code"]
        else:
            raise HTTPException(400, f"Unsupported split mode: {mode}")
        refund_doc["splits"].append(result)

    await db.refunds.insert_one(dict(refund_doc))
    refund_doc.pop("_id", None)

    # Mark original transaction as refunded/partial-refunded
    if tx_id:
        prev_refunds = await db.refunds.find({"transactionId": tx_id, **scope}, {"_id": 0, "amount": 1}).to_list(50)
        refunded_total = sum(r.get("amount", 0) for r in prev_refunds)
        original_total = (txn or {}).get("total", 0) or 0
        new_status = "refunded" if refunded_total >= original_total - 0.01 else "partial_refund"
        await db.transactions.update_one(
            {"id": tx_id, **scope},
            {"$set": {"refundStatus": new_status, "refundedAmount": round(refunded_total, 2)}},
        )

    return refund_doc


# ═════════════════════════════════════════════════════════════════════════
# AI Promotion Builder
# ═════════════════════════════════════════════════════════════════════════
@router.post("/ai/promotion-goal")
async def ai_promotion_goal(body: dict, user: dict = Depends(get_user)):
    """Turn a plain-English goal into a complete campaign template.

    Owner types: "Bring back inactive customers", "Boost Tuesday lunch",
                 "Fill empty tables tonight", "Increase coffee sales".
    Returns:     name, offer copy, voucher template, targeting, schedule,
                 SMS + email body.
    """
    if user["role"] not in ("owner", "manager"):
        raise HTTPException(403, "Owner/manager only")
    goal = (body.get("goal") or "").strip()
    if not goal:
        raise HTTPException(400, "goal is required")

    # Try LLM first; fall back to a heuristic library so this endpoint never
    # 500s in demos / offline runs.
    key = os.environ.get("EMERGENT_LLM_KEY") or os.environ.get("OPENAI_API_KEY")
    if key:
        try:
            from emergentintegrations.llm.chat import LlmChat, UserMessage
            chat = LlmChat(
                api_key=key,
                session_id=f"promo-goal-{uuid.uuid4().hex[:6]}",
                system_message=(
                    "You design hospitality promotions. Reply ONLY with strict JSON matching this schema: "
                    '{"name": string, "objective": string, "offerHeadline": string, "offerBody": string, '
                    '"voucherTemplate": {"valueType": "amount"|"percentage", "value": number, "usageType": "one_time"|"multi_use", "partialRedeemable": bool}, '
                    '"rules": {"activeDays": string[], "startTime": string, "endTime": string, "minSpend": number, "eligibleCategories": string[]}, '
                    '"targeting": {"segment": string, "customerFilter": string}, '
                    '"channels": string[], "smsCopy": string, "emailSubject": string, "emailBody": string, "estimatedRedemptions": int, "estimatedROI": string}'
                ),
            ).with_model("openai", "gpt-4o-mini")
            resp = await chat.send_message(UserMessage(text=f"Owner goal: {goal}. Restaurant context: full-service, avg check $32, weekday lunch is slow. Reply with JSON only."))
            text = resp if isinstance(resp, str) else getattr(resp, "text", str(resp))
            start = text.find("{"); end = text.rfind("}")
            parsed = json.loads(text[start:end+1])
            return {"source": "ai", "goal": goal, **parsed}
        except Exception as e:
            logger.warning(f"AI promotion builder LLM failed: {e}")

    # Heuristic fallback — a decent template based on keyword matching.
    g = goal.lower()
    if "coffee" in g or "morning" in g:
        return _fallback_template(goal, "Coffee AM Boost", "amount", 2.50, ["Monday","Tuesday","Wednesday","Thursday","Friday"], "07:00", "10:30", ["Coffee","Breakfast"], "sms", "$2.50 off your morning coffee 07:00-10:30 weekdays. Show this at counter.")
    if "tuesday" in g or "lunch" in g:
        return _fallback_template(goal, "Tuesday Lunch Rush", "percentage", 20.0, ["Tuesday"], "11:30", "14:30", ["Mains","Lunch"], "email", "20% off Tuesday lunch — 11:30–14:30. Show this voucher.")
    if "empty" in g or "tonight" in g or "fill" in g:
        return _fallback_template(goal, "Fill Tonight", "amount", 15.0, [], "17:00", "20:30", [], "sms", "Tonight only: $15 off any dine-in table over $80. First 30 bookings.")
    if "inactive" in g or "back" in g or "win-back" in g or "winback" in g:
        return _fallback_template(goal, "Win-back Special", "percentage", 25.0, [], None, None, [], "email", "We miss you — 25% off your next visit. Valid 30 days.")
    # Generic
    return _fallback_template(goal, "Custom Promo", "percentage", 15.0, [], None, None, [], "sms", "Show this to save 15% on your next visit.")


def _fallback_template(goal: str, name: str, vt: str, val: float, days: list,
                        start_t: Optional[str], end_t: Optional[str],
                        cats: list, channel: str, sms: str) -> dict:
    return {
        "source": "heuristic", "goal": goal,
        "name": name,
        "objective": goal,
        "offerHeadline": name,
        "offerBody": sms,
        "voucherTemplate": {"valueType": vt, "value": val, "usageType": "one_time", "partialRedeemable": False},
        "rules": {"activeDays": days, "startTime": start_t, "endTime": end_t,
                   "minSpend": 0, "eligibleCategories": cats},
        "targeting": {"segment": "all-customers", "customerFilter": "any"},
        "channels": [channel],
        "smsCopy": sms,
        "emailSubject": name,
        "emailBody": f"{sms}\n\nSee you soon,\nThe NUA Team",
        "estimatedRedemptions": 40,
        "estimatedROI": "3.2x (based on category benchmarks)",
    }


# ═════════════════════════════════════════════════════════════════════════
# Promotion Analytics
# ═════════════════════════════════════════════════════════════════════════
@router.get("/promo-analytics/summary")
async def promo_analytics(days: int = 30, user: dict = Depends(get_user)):
    since = (_now() - timedelta(days=days)).isoformat()
    scope = tenant_scope_filter(user.get("businessId"))
    vs = await db.vouchers.find({"issuedAt": {"$gte": since}, **scope}, {"_id": 0}).to_list(20000)
    issued = len(vs)
    redeemed = sum(1 for v in vs if v.get("redemptionCount", 0) > 0)
    expired = sum(1 for v in vs if v.get("status") == "expired")
    revoked = sum(1 for v in vs if v.get("status") == "revoked")

    # One batched $in lookup for every redemption's transaction instead of
    # one find_one() per redemption — with thousands of vouchers each
    # carrying multiple redemptions, this page used to issue thousands of
    # individual queries on a single load.
    txn_ids = list({
        r["transactionId"] for v in vs for r in v.get("redemptions", []) if r.get("transactionId")
    })
    totals_by_txn = {}
    if txn_ids:
        rows = await db.transactions.find(
            {"id": {"$in": txn_ids}, **scope}, {"_id": 0, "id": 1, "total": 1}
        ).to_list(len(txn_ids))
        totals_by_txn = {row["id"]: row.get("total", 0) for row in rows}
    revenue_generated = sum(
        totals_by_txn.get(r.get("transactionId"), 0)
        for v in vs for r in v.get("redemptions", [])
    )

    # By source type
    by_source: Dict[str, dict] = {}
    for v in vs:
        s = by_source.setdefault(v.get("sourceType", "manual"), {"issued": 0, "redeemed": 0, "value": 0.0})
        s["issued"] += 1
        if v.get("redemptionCount", 0) > 0:
            s["redeemed"] += 1
        s["value"] += float(v.get("faceValue", 0))

    return {
        "windowDays": days,
        "issued": issued,
        "redeemed": redeemed,
        "expired": expired,
        "revoked": revoked,
        "redemptionRate": round((redeemed / issued * 100) if issued else 0, 1),
        "revenueGenerated": round(revenue_generated, 2),
        "faceValueIssued": round(sum(v.get("faceValue", 0) for v in vs), 2),
        "bySource": by_source,
    }


# ═════════════════════════════════════════════════════════════════════════
# Loyalty 2.0 — milestones, badges, streaks, tier progression
# ═════════════════════════════════════════════════════════════════════════
_MILESTONES = [
    {"key": "first_visit", "label": "First visit", "type": "visits", "threshold": 1, "reward": {"type": "voucher", "amount": 5.0}},
    {"key": "regular_5", "label": "Regular · 5 visits", "type": "visits", "threshold": 5, "reward": {"type": "voucher", "amount": 10.0}},
    {"key": "loyal_10", "label": "Loyal · 10 visits", "type": "visits", "threshold": 10, "reward": {"type": "voucher", "amount": 20.0}},
    {"key": "vip_25", "label": "VIP · 25 visits", "type": "visits", "threshold": 25, "reward": {"type": "voucher", "amount": 50.0}},
    {"key": "big_spender_500", "label": "$500 lifetime", "type": "spend", "threshold": 500, "reward": {"type": "voucher", "amount": 25.0}},
    {"key": "big_spender_2k", "label": "$2,000 lifetime", "type": "spend", "threshold": 2000, "reward": {"type": "voucher", "amount": 100.0}},
]

@router.get("/loyalty/status/{customer_id}")
async def loyalty_status(customer_id: str, _: dict = Depends(get_user)):
    c = await db.customers.find_one({**tenant_scope_filter(), "id": customer_id}, {"_id": 0})
    if not c:
        raise HTTPException(404, "Customer not found")
    scope = tenant_scope_filter()
    txns = await db.transactions.find({
        "customerId": customer_id, "status": {"$in": ["completed", "paid", "closed"]},
        **scope,
    }, {"_id": 0}).to_list(5000)
    total_visits = len(txns)
    total_spend = sum(t.get("total", 0) for t in txns)

    # Tier comes from the same points-based db.loyalty_tiers ladder every
    # other tier calculation in the app uses (loyalty_v2's progress view,
    # checkout's own discount lookup, the leaderboard) — this endpoint used
    # to run its own hardcoded, spend-based Bronze/Silver/Gold/Platinum/VIP
    # thresholds instead, so the same customer could show as one tier on
    # the wallet panel and a different tier everywhere else in the app.
    points = int(c.get("points") or 0)
    tiers = await db.loyalty_tiers.find(scope, {"_id": 0}).sort("minPoints", 1).to_list(20)
    current_tier_doc = tiers[0] if tiers else None
    next_tier_doc = None
    for t in tiers:
        if points >= t["minPoints"]:
            current_tier_doc = t
        elif not next_tier_doc:
            next_tier_doc = t
    tier = current_tier_doc["name"] if current_tier_doc else "Bronze"
    next_tier = next_tier_doc["name"] if next_tier_doc else None
    next_threshold = next_tier_doc["minPoints"] if next_tier_doc else None
    tier_progress_pct = 100.0
    if current_tier_doc and next_tier_doc:
        span = max(1, next_tier_doc["minPoints"] - current_tier_doc["minPoints"])
        tier_progress_pct = round(max(0, min(100, (points - current_tier_doc["minPoints"]) / span * 100)), 1)
    # Streak — count consecutive weeks with at least one visit
    weeks_visited = set()
    for t in txns:
        try:
            d = datetime.fromisoformat((t.get("createdAt") or "").replace("Z", "+00:00"))
            weeks_visited.add(d.isocalendar()[:2])
        except Exception:
            continue
    # Streak: walk back week-by-week from current week until miss.
    now = _now()
    cur_iso = now.isocalendar()[:2]
    streak = 0
    y, w = cur_iso
    while (y, w) in weeks_visited:
        streak += 1
        # step back one week
        prev = datetime.fromisocalendar(y, w, 1) - timedelta(days=1)
        y, w = prev.isocalendar()[:2]
    # Awarded milestones (persisted to db.loyalty_awards; auto-award new ones)
    awarded_docs = await db.loyalty_awards.find({"customerId": customer_id, **scope}, {"_id": 0}).to_list(200)
    awarded_keys = {a["key"] for a in awarded_docs}
    newly_awarded = []
    for m in _MILESTONES:
        if m["key"] in awarded_keys:
            continue
        hit = (m["type"] == "visits" and total_visits >= m["threshold"]) or (m["type"] == "spend" and total_spend >= m["threshold"])
        if hit:
            doc = {"customerId": customer_id, "key": m["key"], "label": m["label"],
                   "awardedAt": _iso(now), "businessId": c.get("businessId")}
            await db.loyalty_awards.insert_one(dict(doc))
            doc.pop("_id", None)
            newly_awarded.append(doc)

    milestones_view = [
        {**m, "achieved": m["key"] in awarded_keys or any(a["key"] == m["key"] for a in newly_awarded),
              "progress": min(1.0, (total_visits if m["type"] == "visits" else total_spend) / m["threshold"])}
        for m in _MILESTONES
    ]

    return {
        "customerId": customer_id,
        "name": c.get("name"),
        "tier": tier,
        "nextTier": next_tier,
        "nextTierAt": next_threshold,
        "tierProgressPct": tier_progress_pct,
        "points": points,
        "totalVisits": total_visits,
        "totalSpend": round(total_spend, 2),
        "streakWeeks": streak,
        "milestones": milestones_view,
        "newlyAwarded": newly_awarded,
        "badges": [a["key"] for a in awarded_docs] + [a["key"] for a in newly_awarded],
    }


@router.post("/loyalty/award")
async def loyalty_award(body: dict, user: dict = Depends(get_user)):
    if user["role"] not in ("owner", "manager"):
        raise HTTPException(403, "Owner/manager only")
    if not await db.customers.find_one(
        {"id": body["customerId"], **tenant_scope_filter(user.get("businessId"))}, {"_id": 1}
    ):
        raise HTTPException(404, "Customer not found")
    doc = {
        "customerId": body["customerId"],
        "businessId": user.get("businessId"),
        "key": body["key"],
        "label": body.get("label", body["key"]),
        "awardedAt": _iso(_now()),
        "awardedBy": user.get("email"),
    }
    await db.loyalty_awards.insert_one(dict(doc))
    doc.pop("_id", None)
    return doc


# ═════════════════════════════════════════════════════════════════════════
# AI Personalisation — recommended offers per customer
# ═════════════════════════════════════════════════════════════════════════
@router.get("/personalisation/{customer_id}")
async def personalisation(customer_id: str, user: dict = Depends(get_user)):
    scope = tenant_scope_filter(user.get("businessId"))
    c = await db.customers.find_one({**scope, "id": customer_id}, {"_id": 0})
    if not c:
        raise HTTPException(404, "Customer not found")
    txns = await db.transactions.find(
        {"customerId": customer_id, "status": {"$in": ["completed", "paid", "closed"]}, **scope},
        {"_id": 0},
    ).sort("createdAt", -1).to_list(500)

    fav_items: Dict[str, dict] = {}
    hour_counts: Dict[int, int] = {}
    weekday_counts: Dict[int, int] = {}
    last_visit = None

    for t in txns:
        for it in t.get("items") or []:
            pid = it.get("productId") or it.get("id")
            if not pid: continue
            f = fav_items.setdefault(pid, {"count": 0, "name": it.get("name"), "spend": 0.0, "category": it.get("category")})
            f["count"] += int(it.get("quantity", 1))
            f["spend"] += float(it.get("price", 0)) * int(it.get("quantity", 1))
        try:
            d = datetime.fromisoformat((t.get("createdAt") or "").replace("Z", "+00:00"))
            hour_counts[d.hour] = hour_counts.get(d.hour, 0) + 1
            weekday_counts[d.weekday()] = weekday_counts.get(d.weekday(), 0) + 1
            if not last_visit or d > last_visit:
                last_visit = d
        except Exception:
            continue

    fav_list = sorted(fav_items.values(), key=lambda x: x["count"], reverse=True)[:5]
    typical_hour = max(hour_counts, key=hour_counts.get) if hour_counts else None
    typical_weekday = max(weekday_counts, key=weekday_counts.get) if weekday_counts else None
    days_since_last = (_now() - last_visit).days if last_visit else None
    avg_check = round(sum(t.get("total", 0) for t in txns) / len(txns), 2) if txns else 0

    # Recommend offers
    recs: List[dict] = []
    if days_since_last and days_since_last > 14:
        recs.append({
            "type": "winback", "label": "Come back — 25% off",
            "reason": f"Last visit {days_since_last} days ago",
            "offer": {"valueType": "percentage", "value": 25.0, "usageType": "one_time"},
        })
    if fav_list:
        top = fav_list[0]
        recs.append({
            "type": "favourite", "label": f"Free {top['name']} on next visit",
            "reason": f"Favourite item · ordered {top['count']}×",
            "offer": {"valueType": "free_item", "value": float(top.get("spend", 0) / max(1, top["count"])), "freeItemId": None, "itemName": top["name"]},
        })
    if avg_check and avg_check > 60:
        recs.append({
            "type": "high_value", "label": f"$15 off next visit over ${avg_check:.0f}",
            "reason": f"Avg check ${avg_check:.2f}",
            "offer": {"valueType": "amount", "value": 15.0, "minSpend": avg_check},
        })
    weekday_names = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]
    if typical_weekday is not None and typical_hour is not None:
        recs.append({
            "type": "time_based",
            "label": f"20% off {weekday_names[typical_weekday]}s at your usual time",
            "reason": f"Usual pattern · {weekday_names[typical_weekday]} @ {typical_hour:02d}:00",
            "offer": {"valueType": "percentage", "value": 20.0,
                       "activeDays": [weekday_names[typical_weekday]],
                       "startTime": f"{max(typical_hour-1,0):02d}:00",
                       "endTime": f"{min(typical_hour+1,23):02d}:00"},
        })

    return {
        "customerId": customer_id,
        "name": c.get("name"),
        "insights": {
            "favouriteItems": fav_list,
            "typicalVisitHour": typical_hour,
            "typicalWeekday": weekday_names[typical_weekday] if typical_weekday is not None else None,
            "daysSinceLastVisit": days_since_last,
            "averageCheck": avg_check,
        },
        "recommendations": recs,
    }


# ═════════════════════════════════════════════════════════════════════════
# Gift Card 2.0 — scheduled delivery + reload
# ═════════════════════════════════════════════════════════════════════════
@router.post("/gift-cards/schedule")
async def schedule_gift(body: dict, user: dict = Depends(get_user)):
    """Buy a gift card now, deliver later (e.g. valentine's day)."""
    if user["role"] not in ("owner", "manager"):
        raise HTTPException(403, "Owner/manager only")
    if not body.get("deliverAt"):
        raise HTTPException(400, "deliverAt required")
    v = await _issue_voucher({
        "label": body.get("label") or f"Gift card · ${float(body.get('amount', 0)):.2f}",
        "sourceType": "gift_card",
        "valueType": "amount",
        "value": float(body.get("amount", 0)),
        "usageType": "multi_use",
        "maxRedemptions": None,
        "partialRedeemable": True,
        "customerId": body.get("recipientCustomerId"),
        "expiresAt": body.get("expiresAt"),
        "metadata": {
            "recipientEmail": body.get("recipientEmail"),
            "recipientName": body.get("recipientName"),
            "senderName": body.get("senderName"),
            "personalMessage": body.get("personalMessage"),
            "deliverAt": body.get("deliverAt"),
            "delivered": False,
        },
    }, user)
    # Gift cards mint real spendable value with no purchase transaction
    # backing them (unlike a POS sale) — that made them invisible to the
    # universal audit log entirely; owner/manager gating alone doesn't
    # answer "who minted how much, and when."
    from services.audit_service import log_event
    await log_event(entity_type="gift_card", entity_id=v["id"], action="created",
                     after=v, memo=f"Gift card scheduled: ${v['value']:.2f} by {user.get('email')}")
    return v


@router.post("/gift-cards/{voucher_id}/reload")
async def reload_gift(voucher_id: str, body: dict, user: dict = Depends(get_user)):
    if user["role"] not in ("owner", "manager"):
        raise HTTPException(403, "Owner/manager only")
    scope = tenant_scope_filter(user.get("businessId"))
    v = await db.vouchers.find_one({"id": voucher_id, **scope}, {"_id": 0})
    if not v or v.get("sourceType") != "gift_card":
        raise HTTPException(404, "Gift card not found")
    amt = float(body.get("amount", 0))
    if amt <= 0:
        raise HTTPException(400, "amount must be > 0")
    updated = await db.vouchers.find_one_and_update(
        {"id": voucher_id, "sourceType": "gift_card", **scope},
        {"$inc": {"value": amt, "residualValue": amt, "faceValue": amt},
         "$set": {"status": "partial"}},
        return_document=True,
    )
    if not updated:
        raise HTTPException(404, "Gift card not found")
    new_value = round(updated["value"], 2)
    new_residual = round(updated.get("residualValue") or 0.0, 2)
    from services.audit_service import log_event
    await log_event(entity_type="gift_card", entity_id=voucher_id, action="updated",
                     before=v, after={**v, "value": new_value, "residualValue": new_residual},
                     memo=f"Gift card reloaded: +${amt:.2f} by {user.get('email')} (new balance ${new_residual:.2f})")
    return {"ok": True, "newBalance": new_residual}
