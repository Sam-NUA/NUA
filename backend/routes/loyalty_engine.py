"""v17 — Loyalty Engine (category multipliers + points-and-pay) + Autonomous AI Agent (Ash).

Loyalty rules (user spec):
- 1 USD spent = 1 point (base)
- Categories can have a multiplier configured by owner (e.g. Coffee 2x)
- Minimum redemption = 10 points (= $0.10)
- 1 point = 1¢ = $0.01 face value at redemption
"""
from fastapi import APIRouter, HTTPException, Request, Depends
from deps import get_user, require_owner, require_owner_or_manager
from database import db
from middleware.actor_context import tenant_owns, tenant_owns_strict, tenant_scope_filter
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List
import uuid
import os
import json
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


# =============================================================================
# LOYALTY CONFIG (category multipliers)
# =============================================================================
DEFAULT_CONFIG = {
    "earnRate": 1.0,         # 1 point per $1 base
    "redeemRate": 0.01,      # 1 point = $0.01 (so 10 points = 10c)
    "minRedeem": 10,         # minimum 10 points (= $0.10) to redeem
    "categoryMultipliers": {},  # { "Coffee": 2.0, "Pastry": 1.5 }
    "active": True,
    "pointsExpiryDays": 0,      # 0 = never expire. Otherwise: zero a customer's
                                 # balance once this many days pass with no earn
                                 # or redeem activity at all (inactivity-based,
                                 # not FIFO-per-earn — simpler and matches how
                                 # most POS loyalty programs actually expire).
    "expiryWarnDays": 7,        # send a one-time "your points expire soon" notice
                                 # this many days before pointsExpiryDays actually
                                 # zeroes the balance. Only matters when
                                 # pointsExpiryDays > 0.
    "downgradeEnabled": False,  # tiers only ever went up before; this lets them
                                 # come back down when a customer's balance
                                 # genuinely drops below their tier's threshold.
    "downgradeGraceDays": 30,   # days a customer can sit below-threshold before
                                 # actually being downgraded — a slow month
                                 # shouldn't cost someone their tier overnight.
}


async def get_config(business_id: Optional[str] = None):
    """Every business's own loyalty program configuration (earn rate,
    redeem rate, category multipliers, expiry/downgrade policy) — was a
    single global `{"id": "default"}` document shared by every business on
    the deployment until this fix; see services/tenant_settings.py."""
    from services.tenant_settings import get_scoped_singleton
    cfg = await get_scoped_singleton(db.loyalty_config, {"id": "default"}, business_id)
    return cfg or {"id": "default", **DEFAULT_CONFIG}


@router.get("/loyalty/config")
async def get_loyalty_config(user: dict = Depends(get_user)):
    return await get_config(user.get("businessId"))


@router.put("/loyalty/config")
async def update_loyalty_config(data: dict, user: dict = Depends(require_owner)):
    from services.tenant_settings import set_scoped_singleton
    update = {k: v for k, v in data.items() if k in (
        "earnRate", "redeemRate", "minRedeem", "categoryMultipliers", "active",
        "pointsExpiryDays", "expiryWarnDays", "downgradeEnabled", "downgradeGraceDays",
    )}
    update["updatedAt"] = datetime.now(timezone.utc).isoformat()
    await set_scoped_singleton(db.loyalty_config, {"id": "default"}, update, user.get("businessId"))
    return await get_config(user.get("businessId"))


# =============================================================================
# EARN POINTS (called after a successful transaction)
# =============================================================================
# Neither /loyalty/earn nor /loyalty/redeem below is currently called by
# anything — routes/transactions.py earns/redeems points inline as part of
# checkout (its own _redeem helper + earn calc, not this module) instead of
# calling out to these. That inlining is what actually runs today; these
# stay as the auth-protected place to wire any future NON-checkout
# redemption flow (e.g. a customer scanning a QR code to redeem points
# without a cashier present — see routes/loyalty.py's comment on why that
# must go through an auth-protected handler, not a bare unauthenticated
# one). Not dead code to delete on sight; genuinely unused today, kept on
# purpose.
@router.post("/loyalty/earn")
async def earn_points(data: dict, user: dict = Depends(get_user)):
    customer_id = data.get("customerId")
    items = data.get("items", [])  # [{ category, price, quantity }]
    transaction_id = data.get("transactionId")
    if not customer_id or not items:
        raise HTTPException(status_code=400, detail="customerId + items required")
    customer = await db.customers.find_one({**tenant_scope_filter(user.get("businessId")), "id": customer_id}, {"_id": 0, "businessId": 1})
    if not customer or not tenant_owns(customer.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Customer not found")
    # Idempotency: skip if we already credited this transaction
    if transaction_id:
        existing = await db.loyalty_ledger.find_one({"transactionId": transaction_id, "type": "earn"})
        if existing:
            return {"earned": existing["points"], "skipped": True, "reason": "already credited"}
    cfg = await get_config(user.get("businessId"))
    if not cfg.get("active", True):
        return {"earned": 0, "skipped": True, "reason": "loyalty disabled"}
    mults = cfg.get("categoryMultipliers", {})
    earned = 0.0
    breakdown = []
    for it in items:
        cat = it.get("category", "Other")
        qty = float(it.get("quantity", 1))
        price = float(it.get("price", 0))
        spend = qty * price
        mult = float(mults.get(cat, 1.0))
        pts = spend * float(cfg.get("earnRate", 1.0)) * mult
        earned += pts
        breakdown.append({"category": cat, "spend": round(spend, 2), "multiplier": mult, "points": round(pts, 2)})
    earned_int = int(round(earned))
    # Credit ledger
    entry = {
        "id": f"LP-{str(uuid.uuid4())[:8].upper()}",
        "customerId": customer_id,
        "transactionId": transaction_id,
        "type": "earn",
        "points": earned_int,
        "breakdown": breakdown,
        "businessId": user.get("businessId"),
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    await db.loyalty_ledger.insert_one(entry)
    # Bump customer balance — "points" is the canonical balance field (also
    # what the Customer model declares and what POS checkout earns/redeems
    # against); this used to write "loyaltyPoints" instead, a field checkout
    # never read, so points earned through this endpoint were invisible at
    # the register.
    await db.customers.update_one({**tenant_scope_filter(user.get("businessId")), "id": customer_id}, {"$inc": {"points": earned_int}})
    return {"earned": earned_int, "breakdown": breakdown}


# =============================================================================
# REDEEM (points-and-pay at checkout)
# =============================================================================
@router.post("/loyalty/redeem")
async def redeem_points(data: dict, user: dict = Depends(get_user)):
    customer_id = data.get("customerId")
    points = int(data.get("points", 0))
    transaction_id = data.get("transactionId")
    if not customer_id or points <= 0:
        raise HTTPException(status_code=400, detail="customerId + points (>0) required")
    locked_check = await db.customers.find_one({**tenant_scope_filter(user.get("businessId")), "id": customer_id}, {"_id": 0, "loyaltyLocked": 1, "businessId": 1})
    if not locked_check or not tenant_owns(locked_check.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Customer not found")
    if locked_check and locked_check.get("loyaltyLocked"):
        raise HTTPException(status_code=403, detail="Loyalty account locked pending fraud review")
    cfg = await get_config(user.get("businessId"))
    min_redeem = int(cfg.get("minRedeem", 10))
    if points < min_redeem:
        raise HTTPException(status_code=400, detail=f"Minimum {min_redeem} points required")
    # Atomic balance-checked decrement — same pattern as the checkout redeem
    # path, so a double-tap or concurrent call can't take a customer negative.
    updated = await db.customers.find_one_and_update(
        {**tenant_scope_filter(user.get("businessId")), "id": customer_id, "points": {"$gte": points}},
        {"$inc": {"points": -points}},
    )
    if not updated:
        current = await db.customers.find_one({**tenant_scope_filter(user.get("businessId")), "id": customer_id}, {"_id": 0, "points": 1})
        if not current:
            raise HTTPException(status_code=404, detail="Customer not found")
        raise HTTPException(status_code=400, detail=f"Insufficient points: {int(current.get('points', 0))} available")
    balance = int(updated.get("points", 0))
    value = round(points * float(cfg.get("redeemRate", 0.01)), 2)
    entry = {
        "id": f"LP-{str(uuid.uuid4())[:8].upper()}",
        "customerId": customer_id,
        "transactionId": transaction_id,
        "type": "redeem",
        "points": -points,
        "value": value,
        "businessId": user.get("businessId"),
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    await db.loyalty_ledger.insert_one(entry)
    return {"redeemed": points, "discountValue": value, "newBalance": balance - points}


@router.get("/loyalty/balance/{customer_id}")
async def get_balance(customer_id: str, user: dict = Depends(get_user)):
    customer = await db.customers.find_one({**tenant_scope_filter(user.get("businessId")), "id": customer_id}, {"_id": 0})
    if not customer or not tenant_owns(customer.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Customer not found")
    pts = int(customer.get("points", 0))
    cfg = await get_config(user.get("businessId"))
    return {
        "customerId": customer_id,
        "points": pts,
        "value": round(pts * float(cfg.get("redeemRate", 0.01)), 2),
        "minRedeem": int(cfg.get("minRedeem", 10)),
        "canRedeem": pts >= int(cfg.get("minRedeem", 10)),
    }


@router.get("/loyalty/ledger/{customer_id}")
async def get_ledger(customer_id: str, user: dict = Depends(get_user)):
    customer = await db.customers.find_one({**tenant_scope_filter(user.get("businessId")), "id": customer_id}, {"_id": 0, "businessId": 1})
    if not customer or not tenant_owns(customer.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Customer not found")
    entries = await db.loyalty_ledger.find({"customerId": customer_id}, {"_id": 0}).sort("createdAt", -1).to_list(100)
    return entries


# =============================================================================
# REPORTS — outstanding liability + fraud signals
# =============================================================================
@router.get("/loyalty/reports/liability")
async def get_liability_report(user: dict = Depends(require_owner_or_manager)):
    """Points sitting on customer balances are a real liability — the
    business owes that $ value in future discounts the moment it's earned,
    same accounting posture as gratuity being tracked as a liability rather
    than revenue. Nothing already computed this anywhere; it only ever
    existed implicitly as a sum nobody had run."""
    cfg = await get_config(user.get("businessId"))
    redeem_rate = float(cfg.get("redeemRate", 0.01))
    scope = tenant_scope_filter(user.get("businessId"))
    customers = await db.customers.find(
        {**tenant_scope_filter(user.get("businessId")), "$and": [scope, {"points": {"$gt": 0}}]}, {"_id": 0, "id": 1, "name": 1, "points": 1}
    ).to_list(20000)
    total_points = sum(int(c.get("points", 0)) for c in customers)
    top_holders = sorted(customers, key=lambda c: c.get("points", 0), reverse=True)[:20]
    return {
        "totalPointsOutstanding": total_points,
        "totalLiabilityValue": round(total_points * redeem_rate, 2),
        "customersWithBalance": len(customers),
        "redeemRate": redeem_rate,
        "topHolders": [{"customerId": c["id"], "name": c.get("name"), "points": c.get("points", 0),
                         "value": round(c.get("points", 0) * redeem_rate, 2)} for c in top_holders],
    }


@router.get("/loyalty/reports/roi")
async def get_loyalty_roi_report(user: dict = Depends(require_owner_or_manager)):
    """Redemption cost vs incremental spend — the other half of the
    liability picture above. Liability says what the business currently
    OWES in unredeemed points; this says what the program has actually
    PAID OUT so far (real, already-redeemed value) and whether members
    are worth it.

    Methodology, stated plainly because this is a directional proxy, not
    a certified ROI figure: NUA has no A/B control group and doesn't
    reliably capture per-visit spend timestamped against each customer's
    loyalty join date, so a true before/after cohort study isn't possible
    from data that exists today. "Incremental spend" here instead means
    the gap in average totalSpent between customers who have EVER earned
    or redeemed a loyalty point ("engaged") and those who never have
    ("never engaged"), both drawn from the same business at the same
    point in time — a same-business snapshot comparison, not causal
    attribution. Read the ratio as a signal worth investigating, not a
    number to put in a board deck unqualified.
    """
    business_id = user.get("businessId")
    scope = tenant_scope_filter(business_id)

    cost_row = None
    async for row in db.loyalty_ledger.aggregate([
        {"$match": {"$and": [scope, {"type": "redeem"}]}},
        {"$group": {
            "_id": None,
            "totalValue": {"$sum": "$value"},
            "totalPointsRedeemed": {"$sum": {"$multiply": ["$points", -1]}},
            "redemptionCount": {"$sum": 1},
        }},
    ]):
        cost_row = row
    program_cost = round(float((cost_row or {}).get("totalValue") or 0), 2)
    points_redeemed_total = int(round((cost_row or {}).get("totalPointsRedeemed") or 0))
    redemption_count = int((cost_row or {}).get("redemptionCount") or 0)

    engaged_ids = set()
    async for row in db.loyalty_ledger.aggregate([
        {"$match": scope},
        {"$group": {"_id": "$customerId"}},
    ]):
        if row["_id"]:
            engaged_ids.add(row["_id"])

    all_customers = await db.customers.find(
        scope, {"_id": 0, "id": 1, "totalSpent": 1, "visits": 1, "membershipTier": 1}
    ).to_list(50000)
    engaged = [c for c in all_customers if c["id"] in engaged_ids]
    never_engaged = [c for c in all_customers if c["id"] not in engaged_ids]

    def _avg(rows, field):
        vals = [float(r.get(field, 0) or 0) for r in rows]
        return round(sum(vals) / len(vals), 2) if vals else 0.0

    avg_spend_engaged = _avg(engaged, "totalSpent")
    avg_spend_never_engaged = _avg(never_engaged, "totalSpent")
    incremental_per_engaged = round(avg_spend_engaged - avg_spend_never_engaged, 2)
    # Only credit the program with a positive gap — a negative gap is a real,
    # reportable finding (engaged customers spending less on average), not
    # something to floor at zero and hide.
    estimated_incremental_spend = round(incremental_per_engaged * len(engaged), 2) if incremental_per_engaged > 0 else 0.0
    roi_multiple = round(estimated_incremental_spend / program_cost, 2) if program_cost > 0 else None

    by_tier: dict = {}
    for c in all_customers:
        tier = c.get("membershipTier") or "Bronze"
        by_tier.setdefault(tier, []).append(c)
    tier_breakdown = [
        {"tier": tier, "customerCount": len(rows), "avgSpend": _avg(rows, "totalSpent"), "avgVisits": _avg(rows, "visits")}
        for tier, rows in sorted(by_tier.items())
    ]

    return {
        "programCost": program_cost,
        "pointsRedeemedTotal": points_redeemed_total,
        "redemptionCount": redemption_count,
        "engagedCustomers": len(engaged),
        "neverEngagedCustomers": len(never_engaged),
        "avgSpendEngaged": avg_spend_engaged,
        "avgSpendNeverEngaged": avg_spend_never_engaged,
        "incrementalSpendPerEngagedCustomer": incremental_per_engaged,
        "estimatedIncrementalSpend": estimated_incremental_spend,
        "roiMultiple": roi_multiple,
        "byTier": tier_breakdown,
        "methodology": (
            "\"Engaged\" = has ever earned or redeemed a loyalty point. Incremental "
            "spend = avg totalSpent(engaged) - avg totalSpent(never engaged), a "
            "same-business snapshot comparison, not a before/after cohort study."
        ),
    }


@router.get("/loyalty/reports/locked-accounts")
async def get_locked_accounts(user: dict = Depends(require_owner_or_manager)):
    """Confirming a point-farming flag locks the account, but nothing ever
    listed who's currently locked — the only way to find out was to already
    know the customerId and check their profile. This is the other half of
    that action: see who's locked, so the unlock endpoint has somewhere to
    be driven from."""
    scope = tenant_scope_filter(user.get("businessId"))
    customers = await db.customers.find(
        {**tenant_scope_filter(user.get("businessId")), "$and": [scope, {"loyaltyLocked": True}]}, {"_id": 0, "id": 1, "name": 1, "email": 1, "points": 1}
    ).to_list(500)
    return {"accounts": customers, "count": len(customers)}


async def _compute_fraud_signals(business_id: Optional[str] = None) -> list:
    """Two concrete, computable signals from data that already exists —
    not a general fraud model, just the two patterns explicitly called out
    in the loyalty engine spec's fraud-prevention section that had nothing
    behind them yet:

    - point_farming: a customer with an unusually high rate of separate
      earn events in a short window (repeated minimum-value transactions
      purely to rack up points).
    - voucher_sharing: the same voucher code redeemed from more than one
      terminal within a short window (the code changed hands rather than
      staying with whoever it was issued to).
    """
    window_start = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    scope = tenant_scope_filter(business_id)

    signals = []
    pipeline = [
        {"$match": {"$and": [scope, {"type": "earn", "createdAt": {"$gte": window_start}}]}},
        {"$group": {"_id": "$customerId", "count": {"$sum": 1}, "totalPoints": {"$sum": "$points"}}},
        {"$match": {"count": {"$gte": 5}}},
    ]
    async for row in db.loyalty_ledger.aggregate(pipeline):
        if not row["_id"]:
            continue
        customer = await db.customers.find_one({**tenant_scope_filter(business_id), "id": row["_id"]}, {"_id": 0, "name": 1})
        signals.append({
            "type": "point_farming",
            "customerId": row["_id"],
            "customerName": (customer or {}).get("name"),
            "earnEventsLast24h": row["count"],
            "totalPointsEarned": row["totalPoints"],
            "reason": f"{row['count']} separate earn events in the last 24h",
        })

    recent_vouchers = await db.vouchers.find(
        {"$and": [scope, {"redemptions.1": {"$exists": True}}]}, {"_id": 0, "id": 1, "code": 1, "redemptions": 1}
    ).to_list(2000)
    for v in recent_vouchers:
        redemptions = sorted(v.get("redemptions") or [], key=lambda r: r.get("at", ""))
        for i in range(len(redemptions) - 1):
            a, b = redemptions[i], redemptions[i + 1]
            if not a.get("terminalId") or not b.get("terminalId") or a["terminalId"] == b["terminalId"]:
                continue
            try:
                t_a = datetime.fromisoformat(a["at"].replace("Z", "+00:00"))
                t_b = datetime.fromisoformat(b["at"].replace("Z", "+00:00"))
            except Exception:
                continue
            if abs((t_b - t_a).total_seconds()) <= 600:  # 10 minutes
                signals.append({
                    "type": "voucher_sharing",
                    "voucherId": v["id"], "code": v.get("code"),
                    "terminals": [a["terminalId"], b["terminalId"]],
                    "reason": "Same code redeemed from two different terminals within 10 minutes",
                })
                break  # one flag per voucher is enough signal

    return signals


def _flag_dedup_key(signal: dict) -> dict:
    """One open flag per underlying issue — re-computing signals on every
    report view (or agent tick) shouldn't spam a fresh flag each time."""
    if signal["type"] == "point_farming":
        return {"type": "point_farming", "customerId": signal["customerId"]}
    return {"type": "voucher_sharing", "voucherId": signal["voucherId"]}


async def _persist_fraud_flags(signals: list, business_id: Optional[str] = None) -> int:
    created = 0
    for signal in signals:
        key = _flag_dedup_key(signal)
        existing = await db.loyalty_fraud_flags.find_one(
            {"$and": [tenant_scope_filter(business_id), {**key, "status": "open"}]}, {"_id": 0, "id": 1})
        if existing:
            continue
        await db.loyalty_fraud_flags.insert_one({
            "id": f"FLAG-{str(uuid.uuid4())[:8].upper()}",
            **signal,
            "businessId": business_id,
            "status": "open",
            "reviewedBy": None, "reviewedAt": None, "reviewReason": None,
            "createdAt": datetime.now(timezone.utc).isoformat(),
        })
        created += 1
    return created


@router.get("/loyalty/reports/fraud-flags")
async def get_fraud_flags(status: str = "open", user: dict = Depends(require_owner_or_manager)):
    business_id = user.get("businessId")
    signals = await _compute_fraud_signals(business_id)
    await _persist_fraud_flags(signals, business_id)
    scope = tenant_scope_filter(business_id)
    status_filter = {} if status == "all" else {"status": status}
    flags = await db.loyalty_fraud_flags.find(
        {"$and": [scope, status_filter]}, {"_id": 0}
    ).sort("createdAt", -1).to_list(500)
    return {"flags": flags, "checkedAt": datetime.now(timezone.utc).isoformat()}


@router.put("/loyalty/reports/fraud-flags/{flag_id}")
async def resolve_fraud_flag(flag_id: str, data: dict, user: dict = Depends(require_owner_or_manager)):
    """Close the loop on a flag: mark it reviewed, or confirm abuse and take
    the matching action — lock the customer's loyalty account (point
    farming) or revoke the voucher (sharing). Previously a flag was just
    information with nothing to do about it."""
    new_status = data.get("status")
    if new_status not in ("reviewed_ok", "confirmed_abuse"):
        raise HTTPException(status_code=400, detail="status must be reviewed_ok or confirmed_abuse")
    flag = await db.loyalty_fraud_flags.find_one({"$and": [{"id": flag_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0})
    if not flag or not tenant_owns_strict(flag.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Flag not found")
    if flag["status"] != "open":
        raise HTTPException(status_code=400, detail=f"Flag already {flag['status']}")

    action_taken = None
    if new_status == "confirmed_abuse":
        if flag["type"] == "point_farming" and flag.get("customerId"):
            await db.customers.update_one({**tenant_scope_filter(user.get("businessId")), "id": flag["customerId"]}, {"$set": {"loyaltyLocked": True}})
            action_taken = "Loyalty account locked — redemption blocked until unlocked"
        elif flag["type"] == "voucher_sharing" and flag.get("voucherId"):
            await db.vouchers.update_one({"id": flag["voucherId"]}, {"$set": {
                "status": "revoked",
                "revokedAt": datetime.now(timezone.utc).isoformat(),
                "revokedBy": user.get("email"),
                "revokeReason": "Confirmed voucher sharing (fraud flag)",
            }})
            action_taken = "Voucher revoked"

    await db.loyalty_fraud_flags.update_one({"$and": [{"id": flag_id}, tenant_scope_filter(user.get("businessId"))]}, {"$set": {
        "status": new_status,
        "reviewedBy": user.get("email"), "reviewedAt": datetime.now(timezone.utc).isoformat(),
        "reviewReason": data.get("reason"),
        "actionTaken": action_taken,
    }})
    try:
        from services.audit_service import log_event
        await log_event(entity_type="loyalty_fraud_flag", entity_id=flag_id, action=new_status,
                         memo=f"{flag['type']} flag resolved: {new_status}" + (f" — {action_taken}" if action_taken else ""))
    except Exception as e:
        from utils.errors import log_and_continue
        log_and_continue(logger, f"Fraud flag audit log write failed for {flag_id}", e)
    return {"ok": True, "status": new_status, "actionTaken": action_taken}


@router.post("/loyalty/customers/{customer_id}/unlock")
async def unlock_loyalty_account(customer_id: str, user: dict = Depends(require_owner)):
    """Reverse a loyaltyLocked from a confirmed_abuse flag — owner only,
    since re-enabling redemption after a fraud confirmation is a judgment
    call worth restricting more tightly than reviewing the flag itself."""
    customer = await db.customers.find_one({**tenant_scope_filter(user.get("businessId")), "id": customer_id}, {"_id": 0, "businessId": 1})
    if not customer or not tenant_owns(customer.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Customer not found")
    await db.customers.update_one({**tenant_scope_filter(user.get("businessId")), "id": customer_id}, {"$set": {"loyaltyLocked": False}})
    return {"ok": True}


# =============================================================================
# AUTONOMOUS AI AGENT (Ash) — observes, decides, acts
# =============================================================================
async def _segment_customers(business_id: Optional[str] = None):
    """Auto-segment customers: VIP / regular / at-risk / first-timer.

    Was reading totalVisits/totalSpend/lastVisit — none of which exist on
    the Customer model (models/customer.py has visits/totalSpent/
    lastVisitDate). Every customer silently read as 0/0/"" and fell
    through to "first_timer" for anyone with visits<=1 (which is all of
    them, since totalVisits was always 0) — this has been mis-segmenting
    every customer since the field was added.
    """
    customers = await db.customers.find(tenant_scope_filter(business_id), {"_id": 0}).to_list(5000)
    now = datetime.now(timezone.utc)
    sixty_days_ago = (now - timedelta(days=60)).date().isoformat()
    segments: Dict[str, List[str]] = {"vip": [], "regular": [], "at_risk": [], "first_timer": []}
    for c in customers:
        visits = int(c.get("visits", 0) or 0)
        spend = float(c.get("totalSpent", 0) or 0)
        last_visit = c.get("lastVisitDate", "")
        if spend > 500 and visits > 10:
            segments["vip"].append(c["id"])
        elif visits <= 1:
            segments["first_timer"].append(c["id"])
        elif last_visit and last_visit < sixty_days_ago:
            segments["at_risk"].append(c["id"])
        else:
            segments["regular"].append(c["id"])
    return segments


async def _record_decision(action_type: str, summary: str, payload: dict, status: str = "executed",
                            business_id: Optional[str] = None):
    rec = {
        "id": f"AGT-{str(uuid.uuid4())[:8].upper()}",
        "actionType": action_type,
        "summary": summary,
        "payload": payload,
        "status": status,
        "businessId": business_id,
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    await db.agent_decisions.insert_one(rec)
    rec.pop("_id", None)
    return rec


# =============================================================================
# POINTS EXPIRY (inactivity-based, opt-in via loyalty_config.pointsExpiryDays)
# =============================================================================
async def _expire_inactive_points(cfg: dict, business_id: Optional[str] = None) -> list:
    """Zero out a customer's points balance once pointsExpiryDays have passed
    since their last earn/redeem activity. Inactivity-based rather than
    FIFO-per-earn (which would need tracking an expiry date per earn ledger
    entry and partially consuming it on redemption) — simpler, and matches
    how most POS loyalty programs actually communicate expiry to customers
    ("use your points within a year of your last visit")."""
    days = int(cfg.get("pointsExpiryDays") or 0)
    if days <= 0:
        return []
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    customers = await db.customers.find(
        {"points": {"$gt": 0}, **tenant_scope_filter(business_id)}, {"_id": 0, "id": 1, "points": 1}
    ).to_list(20000)
    expired = []
    for c in customers:
        last = await db.loyalty_ledger.find_one(
            {"customerId": c["id"]}, {"_id": 0, "createdAt": 1}, sort=[("createdAt", -1)]
        )
        last_activity = (last or {}).get("createdAt")
        if not last_activity or last_activity >= cutoff:
            continue
        pts = int(c.get("points", 0))
        if pts <= 0:
            continue
        await db.customers.update_one({**tenant_scope_filter(business_id), "id": c["id"]}, {"$inc": {"points": -pts}})
        await db.loyalty_ledger.insert_one({
            "id": f"LP-{str(uuid.uuid4())[:8].upper()}",
            "customerId": c["id"], "type": "expire", "points": -pts,
            "createdAt": datetime.now(timezone.utc).isoformat(),
        })
        expired.append({"customerId": c["id"], "points": pts})
    return expired


async def _warn_expiring_points(cfg: dict, business_id: Optional[str] = None) -> list:
    """One-time "your points expire soon" notice, sent expiryWarnDays before
    pointsExpiryDays actually zeroes a balance. Expiry used to run
    completely silently — a customer only found out their balance was gone
    after the fact, with no chance to use it first."""
    expiry_days = int(cfg.get("pointsExpiryDays") or 0)
    warn_days = int(cfg.get("expiryWarnDays") or 7)
    if expiry_days <= 0 or warn_days <= 0:
        return []
    from utils.notifications import send_email, send_sms
    now = datetime.now(timezone.utc)
    warn_cutoff = (now - timedelta(days=max(expiry_days - warn_days, 0))).isoformat()
    expire_cutoff = (now - timedelta(days=expiry_days)).isoformat()
    customers = await db.customers.find(
        {"points": {"$gt": 0}, **tenant_scope_filter(business_id)},
        {"_id": 0, "id": 1, "name": 1, "email": 1, "phone": 1, "points": 1, "loyaltyExpiryWarnedAt": 1},
    ).to_list(20000)
    warned = []
    for c in customers:
        last = await db.loyalty_ledger.find_one(
            {"customerId": c["id"]}, {"_id": 0, "createdAt": 1}, sort=[("createdAt", -1)]
        )
        last_activity = (last or {}).get("createdAt")
        # In the warning window: inactive long enough to be within
        # warn_days of expiring, but not already expired (that's
        # _expire_inactive_points's job, run separately in the same tick).
        if not last_activity or not (expire_cutoff < last_activity <= warn_cutoff):
            continue
        already_warned = c.get("loyaltyExpiryWarnedAt")
        if already_warned and already_warned >= last_activity:
            continue  # already warned for this inactivity stretch — new activity would push last_activity forward
        if not c.get("email") and not c.get("phone"):
            continue
        try:
            last_dt = datetime.fromisoformat(last_activity.replace("Z", "+00:00"))
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue
        days_left = max(0, (last_dt + timedelta(days=expiry_days) - now).days)
        pts = int(c.get("points", 0))
        msg = f"You have {pts} points expiring in {days_left} day{'s' if days_left != 1 else ''} — visit us to keep them active!"
        if c.get("email"):
            await send_email(c["email"], "Your points are expiring soon",
                              f"<p>Hi {c.get('name', '')},</p><p>{msg}</p>")
        if c.get("phone"):
            await send_sms(c["phone"], msg)
        await db.customers.update_one({**tenant_scope_filter(business_id), "id": c["id"]}, {"$set": {"loyaltyExpiryWarnedAt": now.isoformat()}})
        warned.append({"customerId": c["id"], "points": pts, "daysLeft": days_left})
    return warned


# =============================================================================
# TIER RE-EVALUATION (upgrade always; downgrade opt-in, with a grace period)
# =============================================================================
async def _reevaluate_tiers(cfg: dict, business_id: Optional[str] = None) -> dict:
    """Recompute each customer's tier from their current points balance
    against routes/loyalty.py's owner-editable loyalty_tiers ladder.
    Upgrades apply immediately (unchanged from before). Downgrades only
    happen when downgradeEnabled is on, and only after the customer has sat
    below their tier's threshold continuously for downgradeGraceDays — a
    single slow week shouldn't cost someone their tier the moment this
    tick runs."""
    tiers = await db.loyalty_tiers.find(tenant_scope_filter(business_id), {"_id": 0}).to_list(20)
    if not tiers:
        return {"downgraded": [], "upgraded": []}
    tiers_desc = sorted(tiers, key=lambda t: t.get("minPoints", 0), reverse=True)
    downgrade_enabled = bool(cfg.get("downgradeEnabled", False))
    grace_days = int(cfg.get("downgradeGraceDays") or 30)
    now = datetime.now(timezone.utc)

    customers = await db.customers.find(
        {"membershipTier": {"$exists": True}, **tenant_scope_filter(business_id)},
        {"_id": 0, "id": 1, "points": 1, "membershipTier": 1, "tierGraceStartedAt": 1},
    ).to_list(20000)
    downgraded, upgraded = [], []
    for c in customers:
        pts = int(c.get("points", 0))
        qualifying = next((t["name"] for t in tiers_desc if pts >= t.get("minPoints", 0)), tiers_desc[-1]["name"])
        current = c.get("membershipTier", tiers_desc[-1]["name"])
        rank = {t["name"]: i for i, t in enumerate(tiers_desc)}  # 0 = highest tier
        cur_rank = rank.get(current, len(tiers_desc) - 1)
        qual_rank = rank.get(qualifying, len(tiers_desc) - 1)

        if qual_rank < cur_rank:
            # Balance now qualifies for a HIGHER tier than currently held.
            await db.customers.update_one(
                {**tenant_scope_filter(business_id), "id": c["id"]}, {"$set": {"membershipTier": qualifying}, "$unset": {"tierGraceStartedAt": ""}}
            )
            upgraded.append({"customerId": c["id"], "from": current, "to": qualifying})
        elif qual_rank > cur_rank:
            # Balance has fallen below the current tier's threshold.
            if not downgrade_enabled:
                continue
            started = c.get("tierGraceStartedAt")
            if not started:
                await db.customers.update_one({**tenant_scope_filter(business_id), "id": c["id"]}, {"$set": {"tierGraceStartedAt": now.isoformat()}})
                continue
            started_dt = datetime.fromisoformat(started.replace("Z", "+00:00")) if isinstance(started, str) else started
            if started_dt.tzinfo is None:
                started_dt = started_dt.replace(tzinfo=timezone.utc)
            if (now - started_dt).days >= grace_days:
                await db.customers.update_one(
                    {**tenant_scope_filter(business_id), "id": c["id"]}, {"$set": {"membershipTier": qualifying}, "$unset": {"tierGraceStartedAt": ""}}
                )
                downgraded.append({"customerId": c["id"], "from": current, "to": qualifying})
        elif c.get("tierGraceStartedAt"):
            # Back at/above threshold before the grace period ran out — clear it.
            await db.customers.update_one({**tenant_scope_filter(business_id), "id": c["id"]}, {"$unset": {"tierGraceStartedAt": ""}})
    return {"downgraded": downgraded, "upgraded": upgraded}


@router.get("/agent/segments")
async def get_segments(_: dict = Depends(require_owner_or_manager)):
    s = await _segment_customers(_.get("businessId"))
    return {"segments": {k: len(v) for k, v in s.items()}, "ids": s}


@router.get("/agent/decisions")
async def get_decisions( limit: int = 100, _: dict = Depends(require_owner_or_manager)):
    decisions = await db.agent_decisions.find(
        tenant_scope_filter(_.get("businessId")), {"_id": 0}
    ).sort("createdAt", -1).to_list(limit)
    return decisions


@router.post("/agent/tick")
async def agent_tick(request: Request, user: dict = Depends(require_owner_or_manager)):
    """Run all autonomous rules once. Returns the list of decisions taken.

    Every read/write below is scoped to the caller's own business_id.
    Previously none of them were: any owner/manager at any business
    calling this endpoint zeroed out points balances, changed membership
    tiers, and issued real wallet vouchers for every business's customers
    on the deployment, not just their own — see the independent security
    review that found this for the exact mechanism."""
    business_id = user.get("businessId")
    decisions = []
    # 1. Auto-segment + flag at-risk
    segs = await _segment_customers(business_id)
    if len(segs["at_risk"]) > 0:
        decisions.append(await _record_decision("at_risk_flagged",
            f"Flagged {len(segs['at_risk'])} customers as at-risk (no visit in 60 days)",
            {"customerIds": segs["at_risk"][:20]}, business_id=business_id))
    # 2. Birthday vouchers — actually issue wallet vouchers for customers whose
    # birthday month is now (idempotent per customer per year).
    from services.wallet_service import ensure_birthday_voucher
    customers = await db.customers.find(
        {"birthday": {"$exists": True}, **tenant_scope_filter(business_id)}, {"_id": 0}
    ).to_list(5000)
    issued = []
    for c in customers:
        try:
            v = await ensure_birthday_voucher(c)
            if v:
                issued.append({"customerId": c["id"], "name": c.get("name"), "voucherId": v["id"], "amount": v["amount"]})
        except Exception:
            continue
    if issued:
        decisions.append(await _record_decision("birthday_vouchers",
            f"Issued {len(issued)} birthday-month vouchers straight to customer wallets",
            {"issued": issued[:20]}, business_id=business_id))
    # 3. Inventory low-stock reorder suggestions
    products = await db.products.find(
        {"stock": {"$lte": 5}, "active": {"$ne": False}, **tenant_scope_filter(business_id)},
        {"_id": 0, "id": 1, "name": 1, "stock": 1},
    ).to_list(500)
    if products:
        decisions.append(await _record_decision("low_stock_alert",
            f"{len(products)} products at/below 5 units — suggest reorder",
            {"products": [{"id": p["id"], "name": p["name"], "stock": p["stock"]} for p in products[:20]]},
            business_id=business_id))
    # 4. Anomaly check on inventory
    try:
        from routes.v15_features import inventory_anomalies  # reuse
        anom = await inventory_anomalies(request)
        if anom.get("anomalies"):
            decisions.append(await _record_decision("inventory_anomaly",
                f"Detected {len(anom['anomalies'])} unusual sales velocity",
                {"anomalies": anom["anomalies"][:10]}, business_id=business_id))
    except Exception:
        pass
    # 5. Tonight-only blast suggestion if low booking count
    today_iso = datetime.now(timezone.utc).date().isoformat()
    bookings_today = await db.reservations.count_documents({"date": today_iso, **tenant_scope_filter(business_id)})
    if bookings_today < 5:
        decisions.append(await _record_decision("blast_suggested",
            f"Only {bookings_today} bookings tonight — suggest 20% off SMS blast to VIPs",
            {"bookingsToday": bookings_today, "vipCount": len(segs["vip"])},
            status="suggested", business_id=business_id))
    # 6. Points expiry warning + 7. Points expiry + 8. Tier re-evaluation —
    # all opt-in via loyalty_config (pointsExpiryDays / downgradeEnabled),
    # no-ops otherwise. Warning runs before expiry so a customer who's about
    # to lose points this tick was at least told last tick, not the same run.
    cfg = await get_config(business_id)
    warned = await _warn_expiring_points(cfg, business_id)
    if warned:
        decisions.append(await _record_decision("points_expiry_warned",
            f"Sent expiry warning to {len(warned)} customer(s) with points expiring soon",
            {"warned": warned[:20]}, business_id=business_id))
    expired = await _expire_inactive_points(cfg, business_id)
    if expired:
        decisions.append(await _record_decision("points_expired",
            f"Expired inactive points for {len(expired)} customer(s)",
            {"expired": expired[:20]}, business_id=business_id))
    tier_changes = await _reevaluate_tiers(cfg, business_id)
    if tier_changes["upgraded"]:
        decisions.append(await _record_decision("tier_upgraded",
            f"{len(tier_changes['upgraded'])} customer(s) auto-upgraded to a higher tier",
            {"upgraded": tier_changes["upgraded"][:20]}, business_id=business_id))
    if tier_changes["downgraded"]:
        decisions.append(await _record_decision("tier_downgraded",
            f"{len(tier_changes['downgraded'])} customer(s) downgraded after {cfg.get('downgradeGraceDays', 30)} days below their tier's threshold",
            {"downgraded": tier_changes["downgraded"][:20]}, business_id=business_id))
    return {"decisionsCount": len(decisions), "decisions": decisions, "segments": {k: len(v) for k, v in segs.items()}}


# =============================================================================
# VOICE COMMAND ROUTER (natural language → action)
# =============================================================================
@router.post("/agent/voice-command")
async def voice_command(data: dict, request: Request, user: dict = Depends(get_user)):
    """Accepts text or audio (base64), classifies intent, executes."""
    text = (data.get("text") or "").strip()
    audio_b64 = data.get("audioBase64")
    if audio_b64 and not text:
        try:
            from routes.v15_features import voice_order
            r = await voice_order({"audioBase64": audio_b64, "mime": data.get("mime", "audio/webm")}, request)
            text = r.get("transcript", "") if isinstance(r, dict) else ""
        except Exception:
            pass

    if not text:
        raise HTTPException(status_code=400, detail="text or audioBase64 required")

    # Quick intent routing using simple LLM call
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        chat = LlmChat(
            api_key=os.environ.get("EMERGENT_LLM_KEY"),
            session_id=f"voice-cmd-{user['id']}-{uuid.uuid4()}",
            system_message=(
                "Classify this restaurant POS command into one of these intents and return STRICT JSON only: "
                "navigate, add_item, book_reservation, run_report, agent_tick, redeem_points, message_blast, unknown. "
                "Format: {\"intent\":\"...\",\"target\":\"...\",\"args\":{...}}. "
                "Examples: 'open dashboard' → navigate dashboard; 'add 2 flat whites' → add_item; "
                "'show today report' → run_report; 'send tonight blast to vips' → message_blast; "
                "'pay using my points' → redeem_points."
            ),
        )
        chat.with_model("openai", "gpt-5.2")
        resp = await chat.send_message(UserMessage(text=text))
        # Parse JSON from response
        try:
            parsed = json.loads(resp.strip().strip("`").strip())
        except Exception:
            # fallback: try to extract braces
            import re
            m = re.search(r"\{.*\}", resp, re.DOTALL)
            parsed = json.loads(m.group(0)) if m else {"intent": "unknown", "raw": resp}
    except Exception as e:
        return {"transcript": text, "intent": "unknown", "error": str(e)[:200]}

    intent = parsed.get("intent", "unknown")
    # Map intent → action route hint for the frontend to execute
    route_map = {
        "navigate": {"navigate": parsed.get("target", "/")},
        "add_item": {"action": "add_to_cart", "items": parsed.get("args", {}).get("items", [])},
        "book_reservation": {"navigate": "/reservations", "preset": parsed.get("args", {})},
        "run_report": {"navigate": "/end-of-day"},
        "redeem_points": {"action": "redeem_points"},
        "message_blast": {"action": "open_blast", "audience": parsed.get("args", {}).get("audience", "vip")},
        "agent_tick": {"action": "agent_tick"},
    }
    return {"transcript": text, "intent": intent, "parsed": parsed, "instruction": route_map.get(intent, {})}


# =============================================================================
# VOICE COMMAND CATALOG (per section)
# =============================================================================
VOICE_CATALOG = {
    "POS": [
        "Add two flat whites and a croissant",
        "Hold this order",
        "Pay using points",
        "Show tabs",
        "Open dashboard",
    ],
    "Items": [
        "Show items",
        "Add new item called Iced Latte for $5.50 in Beverages",
        "Generate image for Avocado Toast",
        "Import items from CSV",
    ],
    "Reservations": [
        "Show today's bookings",
        "Add booking for 4 at 7 PM",
        "Open floor plan",
        "Send confirmation SMS to next booking",
    ],
    "Roster": [
        "Show this week's roster",
        "Run AI auto-roster",
        "Approve all pending swap requests",
    ],
    "Customers": [
        "Show VIP customers",
        "Send tonight blast to at-risk customers",
        "Export GDPR data for John",
    ],
    "Reports": [
        "Show today's revenue",
        "Run end of day",
        "Show inventory anomalies",
        "What's our retention rate?",
    ],
    "Agent": [
        "Run agent tick",
        "Show recent decisions",
        "Approve birthday vouchers",
    ],
}

@router.get("/agent/voice-catalog")
async def voice_catalog():
    return VOICE_CATALOG
