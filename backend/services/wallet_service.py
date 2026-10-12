"""
Customer wallet — one place that answers "what value does this customer
hold with the store right now?": store credit, loyalty points, active
vouchers, and auto-issued occasion offers (birthday month, etc.).

Occasion offers are issued lazily whenever a wallet is read (and in bulk
by the loyalty agent tick), deduped per customer per occasion per year.
"""
from datetime import datetime, timezone
from typing import Optional
import calendar
import uuid

from database import db
from middleware.actor_context import tenant_scope_filter

DEFAULT_OFFERS = {
    "birthdayEnabled": True,
    "birthdayAmount": 10.0,   # $ voucher, valid for the whole birthday month
}


async def get_offer_settings(business_id: Optional[str] = None) -> dict:
    """Defaults business_id from the request's actor context (same pattern
    as notification_service.send()) so existing callers don't need
    editing — this used to be one config shared by every business on the
    deployment; see services/tenant_settings.py."""
    from services.tenant_settings import get_setting
    value = await get_setting("wallet_offers", business_id)
    cfg = dict(DEFAULT_OFFERS)
    if isinstance(value, dict):
        cfg.update(value)
    return cfg


def _parse_birthday(raw: str):
    """Accept YYYY-MM-DD or MM-DD; return (month, day) or None."""
    if not raw:
        return None
    parts = str(raw).split("-")
    try:
        if len(parts) == 3:
            return int(parts[1]), int(parts[2])
        if len(parts) == 2:
            return int(parts[0]), int(parts[1])
    except (ValueError, IndexError):
        return None
    return None


async def ensure_birthday_voucher(customer: dict, amount: Optional[float] = None) -> Optional[dict]:
    """Issue this year's birthday-month voucher if the customer's birthday
    falls in the current month and they don't have one yet. Idempotent.

    Ownership comes from the customer record's own `businessId`, never from
    the bare customerId — every caller here already resolved `customer` from
    a tenant-scoped query, so this is the verified business, not a guess.
    A customer with no businessId (unowned/legacy) gets no voucher rather
    than one stamped to nobody or to a guessed tenant."""
    business_id = customer.get("businessId")
    if not business_id:
        return None
    cfg = await get_offer_settings(business_id)
    if not cfg.get("birthdayEnabled", True):
        return None
    bd = _parse_birthday(customer.get("birthday"))
    if not bd:
        return None
    now = datetime.now(timezone.utc)
    if bd[0] != now.month:
        return None
    existing = await db.vouchers.find_one({
        "customerId": customer["id"], "reason": "birthday", "year": now.year,
        **tenant_scope_filter(business_id),
    })
    if existing:
        return None
    last_day = calendar.monthrange(now.year, now.month)[1]
    expires = datetime(now.year, now.month, last_day, 23, 59, 59, tzinfo=timezone.utc)
    voucher = {
        "id": f"VCH-{str(uuid.uuid4())[:8].upper()}",
        "customerId": customer["id"],
        "businessId": business_id,
        "amount": float(amount if amount is not None else cfg.get("birthdayAmount", 10.0)),
        "reason": "birthday",
        "occasion": "Birthday Month 🎂",
        "year": now.year,
        "status": "active",
        "createdAt": now.isoformat(),
        "expiresAt": expires.isoformat(),
    }
    await db.vouchers.insert_one(voucher)
    voucher.pop("_id", None)
    return voucher


async def expire_stale_vouchers(customer_id: str, business_id: Optional[str] = None):
    """Flip active-but-expired vouchers to 'expired' so wallets stay honest.

    Scoped to the caller's own business — a legacy voucher with no
    businessId yet (pre-dating this fix) is left alone rather than expired
    by a tenant that was never confirmed to own it; it becomes reachable
    again once resolved through the reviewed ownership-migration workflow
    (services/ownership_migration.py; "vouchers" is already in its
    MIGRATABLE_COLLECTIONS)."""
    now_iso = datetime.now(timezone.utc).isoformat()
    await db.vouchers.update_many(
        {"customerId": customer_id, "status": "active", "expiresAt": {"$lt": now_iso},
         **tenant_scope_filter(business_id)},
        {"$set": {"status": "expired"}},
    )


async def get_wallet(customer_id: str, business_id: Optional[str] = None) -> Optional[dict]:
    from middleware.actor_context import get_actor_context
    biz = business_id or get_actor_context().get("businessId")
    customer = await db.customers.find_one({**tenant_scope_filter(biz), "id": customer_id}, {"_id": 0})
    if not customer:
        return None
    # The verified customer record is the ownership source of truth from
    # here on — not the bare customer_id the caller passed in.
    biz = customer.get("businessId") or biz
    # Lazy occasion issuance + cleanup, then read
    await ensure_birthday_voucher(customer)
    await expire_stale_vouchers(customer_id, biz)
    vouchers = await db.vouchers.find(
        {"customerId": customer_id, "status": "active", **tenant_scope_filter(biz)}, {"_id": 0}
    ).to_list(100)
    # Two kinds of voucher land in this collection: wallet ones written here
    # (amount/createdAt) and Universal Voucher Engine ones from campaigns,
    # refunds and promotions (value/issuedAt, plus a code + QR). Normalize so
    # the wallet shows one consistent list — before this, engine vouchers
    # displayed as $0 and sorted to the bottom for want of an `amount`.
    for v in vouchers:
        if v.get("amount") is None and v.get("value") is not None:
            v["amount"] = float(v.get("value") or 0)
        v.setdefault("createdAt", v.get("issuedAt"))
    vouchers.sort(key=lambda v: str(v.get("createdAt") or ""), reverse=True)
    # Percentage-off vouchers have no fixed dollar value, so they'd inflate a
    # dollar total — count only the fixed-value ones.
    fixed_value = [v for v in vouchers if v.get("valueType") != "percentage"]
    return {
        "customerId": customer_id,
        "name": customer.get("name"),
        "storeCredit": round(float(customer.get("storeCredit") or 0), 2),
        "points": int(customer.get("points") or 0),
        "membershipTier": customer.get("membershipTier", "Bronze"),
        "vouchers": vouchers,
        "occasionOffers": [v for v in vouchers if v.get("occasion")],
        "totalVoucherValue": round(sum(float(v.get("amount") or 0) for v in fixed_value), 2),
    }


async def redeem_wallet_voucher(voucher_id: str, txn_id: str, requested_amount: float = 0.0,
                                 business_id: Optional[str] = None) -> float:
    """Atomically validate and consume a wallet voucher used as a POS
    discount. Returns the amount actually applied, capped to what the
    voucher is really worth — the caller's requested_amount is a display
    hint, never authoritative, since it ultimately comes from the client.

    Sets status to "redeemed"/"partial" (not the old "used") because that's
    the only vocabulary the rest of the voucher lifecycle — in particular
    commerce_v29.py's _validate_voucher_rules, which gates re-redemption —
    actually checks. A voucher left in status "used" was invisible to that
    check and could be redeemed a second time through /vouchers/redeem.

    Tenant-scoped on both the read and the compare-and-swap write.
    routes/transactions.py already re-prices a foreign voucherId's discount
    to $0 before this is ever called, but that's the caller's defense, not
    this function's — scoping here too means a foreign/unowned voucher_id
    can never be redeemed through this entry point even if a future caller
    forgets that re-pricing step."""
    # Compare-and-swap retry loop, same idiom as routes/commerce_v29.py's
    # redeem_voucher — this function is live (routes/transactions.py calls
    # it for every POS-checkout wallet-voucher discount), and the old
    # single-shot filter pinned only `status`, not `residualValue`: two
    # concurrent checkouts both applying the same partial-redeemable
    # voucher could both read the same residual, both compute a new
    # residual from it, and both write — the exact lost-update/overdraw
    # race already fixed in commerce_v29.py, just reachable from this
    # sibling entry point too.
    from middleware.actor_context import get_actor_context
    biz = business_id or get_actor_context().get("businessId")
    scope = tenant_scope_filter(biz)
    for _attempt in range(8):
        v = await db.vouchers.find_one({"id": voucher_id, **scope}, {"_id": 0})
        if not v or v.get("status") not in ("active", "partial"):
            return 0.0

        if v.get("valueType") == "percentage":
            applied = max(0.0, float(requested_amount))
        else:
            cap = float(v.get("residualValue")) if v.get("partialRedeemable") else float(v.get("value", 0) or 0)
            applied = max(0.0, min(float(requested_amount), max(cap, 0.0)))
        if applied <= 0:
            return 0.0

        update = {"usedAt": datetime.now(timezone.utc).isoformat(), "transactionId": txn_id}
        if v.get("partialRedeemable"):
            prev_residual = float(v.get("residualValue") if v.get("residualValue") is not None else v.get("value", 0))
            new_residual = round(max(0.0, prev_residual - applied), 2)
            update["residualValue"] = new_residual
            update["status"] = "partial" if new_residual > 0 else "redeemed"
        else:
            update["status"] = "redeemed"

        cas_filter = {
            "id": voucher_id, "status": v["status"],
            "residualValue": v.get("residualValue"),
            "redemptionCount": v.get("redemptionCount", 0),
            **scope,
        }
        res = await db.vouchers.find_one_and_update(
            cas_filter, {"$set": update, "$inc": {"redemptionCount": 1}},
        )
        if res is not None:
            return round(applied, 2)
        # Lost the race — someone else redeemed/updated this voucher
        # between our read and write. Retry against fresh state.
    return 0.0
