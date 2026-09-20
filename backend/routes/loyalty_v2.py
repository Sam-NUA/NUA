"""
Loyalty 2.0 — Badges, Milestones, Seasonal Challenges & Tier Progression.

Design
──────
• Badges are catalog entries (10 pre-seeded). Each has a `condition` string
  interpreted by the engine (first_visit, visits>=10, spend>=500, categorySpend:Wine>=200).
• Milestones are numeric thresholds (visits/spend) that award a `reward` — voucher, points, tier bump.
• Challenges are owner-authored, time-boxed missions with a target + reward.
• `evaluate_customer(customerId)` walks the catalog and idempotently awards new items.
• `progress(customerId)` returns tier progress + milestone completion for the UI.

Idempotency guaranteed by `customer_badges` composite key {customerId, badgeId}.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, HTTPException, Depends
from database import db
from deps import get_user, require_owner_or_manager
from middleware.actor_context import tenant_scope_filter, tenant_owns, tenant_owns_strict
from utils.notifications import send_sms
import hashlib
import secrets
import uuid
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/loyalty/v2")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ═════════════════════════════════════════════════════════════════════════
# Seed catalogs (idempotent — only seeded if collection empty)
# ═════════════════════════════════════════════════════════════════════════
BADGE_SEEDS = [
    {"id": "badge-first-visit", "name": "First Visit", "icon": "sparkles", "color": "#8b5cf6",
     "description": "Welcome to the family!", "condition": "visits>=1", "points": 10},
    {"id": "badge-regular", "name": "Regular", "icon": "coffee", "color": "#f59e0b",
     "description": "5 visits and counting", "condition": "visits>=5", "points": 50},
    {"id": "badge-loyalist", "name": "Loyalist", "icon": "heart", "color": "#dc2626",
     "description": "10 visits — you know the staff by name", "condition": "visits>=10", "points": 100},
    {"id": "badge-century", "name": "Century Club", "icon": "trophy", "color": "#eab308",
     "description": "50 visits", "condition": "visits>=50", "points": 500},
    {"id": "badge-spender", "name": "Big Spender", "icon": "dollar-sign", "color": "#10b981",
     "description": "$500 lifetime spend", "condition": "spend>=500", "points": 100},
    {"id": "badge-whale", "name": "VIP Whale", "icon": "crown", "color": "#7c3aed",
     "description": "$5,000 lifetime spend", "condition": "spend>=5000", "points": 1000},
    {"id": "badge-early-bird", "name": "Early Bird", "icon": "sunrise", "color": "#f97316",
     "description": "3 breakfast visits", "condition": "categoryVisits:Breakfast>=3", "points": 30},
    {"id": "badge-wine-buff", "name": "Wine Buff", "icon": "wine", "color": "#be123c",
     "description": "$200 in wine purchases", "condition": "categorySpend:Wine>=200", "points": 100},
    {"id": "badge-referrer", "name": "Community Builder", "icon": "users", "color": "#2563eb",
     "description": "Referred 3 friends", "condition": "referrals>=3", "points": 200},
    {"id": "badge-birthday", "name": "Birthday Guest", "icon": "gift", "color": "#ec4899",
     "description": "Celebrated a birthday with us", "condition": "birthdayVisit=true", "points": 50},
]

MILESTONE_SEEDS = [
    {"id": "mile-visits-5", "name": "5 Visits", "metric": "visits", "threshold": 5,
     "reward": {"type": "voucher", "value": 5, "label": "$5 voucher"}, "order": 1},
    {"id": "mile-visits-25", "name": "25 Visits", "metric": "visits", "threshold": 25,
     "reward": {"type": "voucher", "value": 25, "label": "$25 voucher"}, "order": 2},
    {"id": "mile-spend-100", "name": "$100 Spent", "metric": "spend", "threshold": 100,
     "reward": {"type": "points", "value": 200, "label": "200 bonus points"}, "order": 3},
    {"id": "mile-spend-500", "name": "$500 Spent", "metric": "spend", "threshold": 500,
     "reward": {"type": "tier", "value": "Silver", "label": "Silver tier"}, "order": 4},
    {"id": "mile-spend-2000", "name": "$2,000 Spent", "metric": "spend", "threshold": 2000,
     "reward": {"type": "tier", "value": "Gold", "label": "Gold tier"}, "order": 5},
    {"id": "mile-spend-5000", "name": "$5,000 Spent", "metric": "spend", "threshold": 5000,
     "reward": {"type": "tier", "value": "Platinum", "label": "Platinum tier"}, "order": 6},
]


async def _ensure_seeded(business_id: Optional[str] = None) -> None:
    """Idempotent per-business seed. Previously seeded once globally
    ("if the collection is empty at all") — every business after the
    first one to trigger this ever saw loyalty_badges/loyalty_milestones
    as already non-empty and got no catalog of its own, so every business
    on the deployment silently shared one badge/milestone catalog with no
    real per-business identity, and business B's badges/milestones were
    fully visible to (and, since they're unscoped everywhere they're
    read, indistinguishable from) business A's."""
    scope = tenant_scope_filter(business_id)
    if await db.loyalty_badges.count_documents(scope) == 0:
        await db.loyalty_badges.insert_many([{**b, "businessId": business_id} for b in BADGE_SEEDS])
    if await db.loyalty_milestones.count_documents(scope) == 0:
        await db.loyalty_milestones.insert_many([{**m, "businessId": business_id} for m in MILESTONE_SEEDS])


# ═════════════════════════════════════════════════════════════════════════
# Condition evaluator
# ═════════════════════════════════════════════════════════════════════════
def _customer_metric(customer: Dict[str, Any], metric: str) -> float:
    if metric == "visits":
        return float(customer.get("totalVisits") or customer.get("visits") or 0)
    if metric == "spend":
        return float(customer.get("totalSpend") or customer.get("totalSpent") or 0)
    if metric == "referrals":
        return float(customer.get("referrals") or 0)
    return 0.0


async def _category_spend(customer_id: str, category: str) -> float:
    """Sum transactions where any line item has the given category."""
    total = 0.0
    async for t in db.transactions.find(
        {"customerId": customer_id, "items.category": category},
        {"_id": 0, "items": 1},
    ):
        for item in t.get("items", []):
            if item.get("category") == category:
                total += float(item.get("total") or (float(item.get("price") or 0) * float(item.get("quantity") or 1)))
    return total


async def _category_visits(customer_id: str, category: str) -> int:
    return await db.transactions.count_documents(
        {"customerId": customer_id, "items.category": category}
    )


async def _condition_met(customer: Dict[str, Any], cond: str) -> bool:
    """Interpret a simple condition string. Very limited on purpose."""
    if cond == "birthdayVisit=true":
        return bool(customer.get("celebratedBirthday"))
    if ":" in cond:
        # Format: categoryMetric:Value>=Number
        head, tail = cond.split(":", 1)
        cat, expr = tail.split(">=", 1)
        target = float(expr)
        if head == "categorySpend":
            return await _category_spend(customer["id"], cat) >= target
        if head == "categoryVisits":
            return (await _category_visits(customer["id"], cat)) >= target
        return False
    for op in (">=", "<=", ">", "<", "=="):
        if op in cond:
            key, val = cond.split(op, 1)
            actual = _customer_metric(customer, key.strip())
            target = float(val)
            return {
                ">=": actual >= target, "<=": actual <= target,
                ">": actual > target, "<": actual < target,
                "==": actual == target,
            }[op]
    return False


# ═════════════════════════════════════════════════════════════════════════
# Public evaluation + progress
# ═════════════════════════════════════════════════════════════════════════
async def evaluate_customer(customer_id: str, business_id: Optional[str] = None) -> Dict[str, Any]:
    """Award any newly-earned badges + milestones."""
    customer = await db.customers.find_one({**tenant_scope_filter(business_id), "id": customer_id}, {"_id": 0})
    if not customer:
        return {"error": "customer not found"}
    business_id = customer.get("businessId")
    await _ensure_seeded(business_id)
    scope = tenant_scope_filter(business_id)

    awarded_badges: List[Dict[str, Any]] = []
    awarded_milestones: List[Dict[str, Any]] = []

    # ── Badges ──
    badges = await db.loyalty_badges.find(scope, {"_id": 0}).to_list(200)
    for b in badges:
        existing = await db.customer_badges.find_one({"customerId": customer_id, "badgeId": b["id"]})
        if existing:
            continue
        if await _condition_met(customer, b.get("condition", "")):
            doc = {
                "id": str(uuid.uuid4()), "customerId": customer_id,
                "badgeId": b["id"], "badgeName": b["name"], "icon": b.get("icon"), "color": b.get("color"),
                "pointsAwarded": int(b.get("points") or 0), "awardedAt": _now(),
            }
            await db.customer_badges.insert_one(dict(doc))
            if doc["pointsAwarded"]:
                # "points" is the canonical balance field (Customer model,
                # POS checkout earn/redeem) — "loyaltyPoints" doesn't exist
                # on the customer document, so badge point awards were
                # invisible everywhere else: checkout redemption, the
                # wallet, the liability report, tier progress below.
                await db.customers.update_one(
                    {**tenant_scope_filter(business_id), "id": customer_id},
                    {"$inc": {"points": doc["pointsAwarded"]}},
                )
            awarded_badges.append(doc)

    # ── Milestones ──
    miles = await db.loyalty_milestones.find(scope, {"_id": 0}).sort("order", 1).to_list(200)
    for m in miles:
        existing = await db.customer_milestones.find_one({"customerId": customer_id, "milestoneId": m["id"]})
        if existing:
            continue
        actual = _customer_metric(customer, m["metric"])
        if actual < float(m["threshold"]):
            continue
        reward = m.get("reward") or {}
        rec = {
            "id": str(uuid.uuid4()), "customerId": customer_id,
            "milestoneId": m["id"], "name": m["name"],
            "reward": reward, "achievedAt": _now(),
        }
        await db.customer_milestones.insert_one(dict(rec))
        # Apply the reward
        if reward.get("type") == "points":
            await db.customers.update_one({**tenant_scope_filter(business_id), "id": customer_id}, {"$inc": {"points": int(reward.get("value") or 0)}})
        elif reward.get("type") == "tier":
            await db.customers.update_one({**tenant_scope_filter(business_id), "id": customer_id}, {"$set": {"membershipTier": reward.get("value")}})
        elif reward.get("type") == "voucher":
            # Routed through the shared issuer (commerce_v29._issue_voucher)
            # rather than a hand-rolled insert — a bare {id, value, status}
            # dict is missing the code/qrPayload the redemption flow and the
            # admin voucher list both require, so it was created, shown in
            # the wallet, and permanently unredeemable. See _issue_voucher
            # for the fields that actually matter.
            try:
                from routes.commerce_v29 import _issue_voucher
                v = await _issue_voucher({
                    "sourceType": "loyalty_milestone", "sourceRef": m["id"],
                    "label": reward.get("label") or "Milestone voucher",
                    "valueType": "amount", "value": float(reward.get("value") or 0),
                    "customerId": customer_id, "businessId": customer.get("businessId"),
                })
                rec["voucherId"] = v["id"]
            except Exception:
                pass
        awarded_milestones.append(rec)

    # ── Notifications for freshly-earned badges/milestones ──
    if awarded_badges or awarded_milestones:
        try:
            from services import notification_service as ns
            cust_email = customer.get("email")
            cust_name = customer.get("name") or "Guest"
            for b in awarded_badges:
                await ns.send(
                    role="marketing", kind="loyalty", severity="info",
                    title=f"{cust_name} earned {b['badgeName']}",
                    body=f"Consider a congrats message — worth {b.get('pointsAwarded', 0)} bonus pts.",
                    link=f"/loyalty-progress?customer={customer_id}",
                    data={"customerId": customer_id, "badgeId": b["badgeId"]},
                )
                if cust_email:
                    await ns.send(
                        email=cust_email, kind="loyalty", severity="info",
                        title=f"You just earned the {b['badgeName']} badge!",
                        body=f"Thanks for being one of us. Enjoy {b.get('pointsAwarded', 0)} bonus points.",
                        data={"badgeId": b["badgeId"]},
                    )
            for m in awarded_milestones:
                reward_label = (m.get("reward") or {}).get("label", "reward")
                await ns.send(
                    role="marketing", kind="loyalty", severity="notice",
                    title=f"{cust_name} hit milestone: {m['name']}",
                    body=f"Reward: {reward_label}.",
                    link=f"/loyalty-progress?customer={customer_id}",
                    data={"customerId": customer_id, "milestoneId": m["milestoneId"]},
                )
                if cust_email:
                    await ns.send(
                        email=cust_email, kind="loyalty", severity="notice",
                        title=f"Milestone unlocked: {m['name']}",
                        body=f"Your reward: {reward_label}.",
                        data={"milestoneId": m["milestoneId"]},
                    )
        except Exception:
            pass

    # ── Seasonal Challenges ──
    challenges = await db.loyalty_challenges.find(
        {"$and": [scope, {"active": True, "startDate": {"$lte": _now()}, "endDate": {"$gte": _now()}}]},
        {"_id": 0},
    ).to_list(50)
    challenge_progress = []
    for ch in challenges:
        prog = await db.customer_challenge_progress.find_one(
            {"customerId": customer_id, "challengeId": ch["id"]},
        )
        # Compute the customer's live progress since the challenge started
        current = 0.0
        if ch["metric"] == "visits":
            current = await db.transactions.count_documents(
                {"customerId": customer_id, "timestamp": {"$gte": ch["startDate"]}},
            )
        elif ch["metric"] == "spend":
            async for t in db.transactions.find(
                {"customerId": customer_id, "timestamp": {"$gte": ch["startDate"]}},
                {"_id": 0, "total": 1},
            ):
                current += float(t.get("total") or 0)
        completed = current >= float(ch["target"])
        rec = {
            "challengeId": ch["id"], "customerId": customer_id,
            "current": current, "target": ch["target"],
            "progressPercent": min(100, round((current / max(1, ch["target"])) * 100)),
            "completed": completed, "updatedAt": _now(),
        }
        if prog:
            await db.customer_challenge_progress.update_one(
                {"customerId": customer_id, "challengeId": ch["id"]},
                {"$set": rec},
            )
        else:
            rec["id"] = str(uuid.uuid4())
            await db.customer_challenge_progress.insert_one(dict(rec))
        if completed and not (prog or {}).get("rewarded"):
            reward = ch.get("reward") or {}
            if reward.get("type") == "points":
                await db.customers.update_one({**tenant_scope_filter(business_id), "id": customer_id}, {"$inc": {"points": int(reward.get("value") or 0)}})
            elif reward.get("type") == "voucher":
                try:
                    from routes.commerce_v29 import _issue_voucher
                    await _issue_voucher({
                        "sourceType": "loyalty_challenge", "sourceRef": ch["id"],
                        "label": reward.get("label") or ch["name"],
                        "valueType": "amount", "value": float(reward.get("value") or 0),
                        "customerId": customer_id, "businessId": customer.get("businessId"),
                    })
                except Exception:
                    pass
            await db.customer_challenge_progress.update_one(
                {"customerId": customer_id, "challengeId": ch["id"]},
                {"$set": {"rewarded": True, "rewardedAt": _now()}},
            )
        challenge_progress.append(rec)

    return {"awardedBadges": awarded_badges, "awardedMilestones": awarded_milestones,
            "challengeProgress": challenge_progress}


async def get_customer_progress(customer_id: str, business_id: Optional[str] = None) -> Dict[str, Any]:
    customer = await db.customers.find_one({**tenant_scope_filter(business_id), "id": customer_id}, {"_id": 0})
    if not customer:
        return {"error": "customer not found"}
    business_id = customer.get("businessId")
    await _ensure_seeded(business_id)
    scope = tenant_scope_filter(business_id)

    # Tier calculation
    tiers = await db.loyalty_tiers.find(scope, {"_id": 0}).sort("minPoints", 1).to_list(20)
    points = int(customer.get("points") or 0)
    current_tier = tiers[0] if tiers else None
    next_tier = None
    for t in tiers:
        if points >= t["minPoints"]:
            current_tier = t
        elif not next_tier:
            next_tier = t

    tier_progress = None
    if current_tier and next_tier:
        span = max(1, next_tier["minPoints"] - current_tier["minPoints"])
        prog = points - current_tier["minPoints"]
        tier_progress = {
            "current": current_tier["name"], "next": next_tier["name"],
            "pointsNeeded": next_tier["minPoints"] - points,
            "percent": max(0, min(100, round((prog / span) * 100))),
        }
    elif current_tier:
        tier_progress = {"current": current_tier["name"], "next": None,
                           "pointsNeeded": 0, "percent": 100}

    # Earned badges + all badge catalog
    catalog = await db.loyalty_badges.find(scope, {"_id": 0}).to_list(200)
    earned_badges = await db.customer_badges.find(
        {"customerId": customer_id}, {"_id": 0},
    ).to_list(200)
    earned_ids = {b["badgeId"] for b in earned_badges}
    badge_view = [{**b, "earned": b["id"] in earned_ids} for b in catalog]

    # Milestones
    miles = await db.loyalty_milestones.find(scope, {"_id": 0}).sort("order", 1).to_list(200)
    achieved = await db.customer_milestones.find(
        {"customerId": customer_id}, {"_id": 0},
    ).to_list(200)
    achieved_ids = {m["milestoneId"] for m in achieved}
    milestone_view = []
    for m in miles:
        actual = _customer_metric(customer, m["metric"])
        milestone_view.append({
            **m, "achieved": m["id"] in achieved_ids,
            "current": actual,
            "progressPercent": min(100, round((actual / max(1, m["threshold"])) * 100)),
        })

    # Active challenges
    now = _now()
    challenges = await db.loyalty_challenges.find(
        {"$and": [scope, {"active": True, "startDate": {"$lte": now}, "endDate": {"$gte": now}}]},
        {"_id": 0},
    ).to_list(50)
    prog_rows = await db.customer_challenge_progress.find(
        {"customerId": customer_id}, {"_id": 0},
    ).to_list(100)
    prog_map = {p["challengeId"]: p for p in prog_rows}
    challenge_view = []
    for ch in challenges:
        p = prog_map.get(ch["id"]) or {"current": 0, "progressPercent": 0, "completed": False}
        challenge_view.append({**ch, **p})

    return {
        "customerId": customer_id,
        "customerName": customer.get("name"),
        "points": points,
        "tier": current_tier and current_tier["name"],
        "tierProgress": tier_progress,
        "badges": badge_view,
        "milestones": milestone_view,
        "challenges": challenge_view,
    }


# ═════════════════════════════════════════════════════════════════════════
# HTTP endpoints
# ═════════════════════════════════════════════════════════════════════════
@router.get("/badges")
async def list_badges(user: dict = Depends(get_user)):
    business_id = user.get("businessId")
    await _ensure_seeded(business_id)
    return await db.loyalty_badges.find(tenant_scope_filter(business_id), {"_id": 0}).to_list(200)


@router.get("/milestones")
async def list_milestones(user: dict = Depends(get_user)):
    business_id = user.get("businessId")
    await _ensure_seeded(business_id)
    return await db.loyalty_milestones.find(tenant_scope_filter(business_id), {"_id": 0}).sort("order", 1).to_list(200)


@router.get("/challenges")
async def list_challenges(active_only: bool = True, user: dict = Depends(get_user)):
    scope = tenant_scope_filter(user.get("businessId"))
    q = scope
    if active_only:
        now = _now()
        q = {"$and": [scope, {"active": True, "startDate": {"$lte": now}, "endDate": {"$gte": now}}]}
    return await db.loyalty_challenges.find(q, {"_id": 0}).sort("startDate", -1).to_list(50)


@router.post("/challenges")
async def create_challenge(body: dict, user: dict = Depends(require_owner_or_manager)):
    required = {"name", "metric", "target", "startDate", "endDate"}
    if not required.issubset(body.keys()):
        raise HTTPException(400, f"required: {sorted(required)}")
    doc = {
        "id": str(uuid.uuid4()),
        "name": body["name"],
        "description": body.get("description", ""),
        "metric": body["metric"],
        "target": float(body["target"]),
        "startDate": body["startDate"],
        "endDate": body["endDate"],
        "reward": body.get("reward") or {},
        "active": True,
        "createdBy": user.get("email"),
        "createdAt": _now(),
        "businessId": user.get("businessId"),
    }
    await db.loyalty_challenges.insert_one(dict(doc))
    return doc


@router.delete("/challenges/{cid}")
async def delete_challenge(cid: str, user: dict = Depends(require_owner_or_manager)):
    guard = await db.loyalty_challenges.find_one({"$and": [{"id": cid}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0, "id": 1, "businessId": 1})
    if guard is None or not tenant_owns_strict(guard.get("businessId"), user.get("businessId")):
        raise HTTPException(404, "not found")
    r = await db.loyalty_challenges.delete_one({"$and": [{"id": cid}, tenant_scope_filter(user.get("businessId"))]})
    if not r.deleted_count:
        raise HTTPException(404, "not found")
    return {"deleted": True}


@router.patch("/challenges/{cid}")
async def update_challenge(cid: str, body: dict, user: dict = Depends(require_owner_or_manager)):
    guard = await db.loyalty_challenges.find_one({"$and": [{"id": cid}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0, "id": 1, "businessId": 1})
    if guard is None or not tenant_owns_strict(guard.get("businessId"), user.get("businessId")):
        raise HTTPException(404, "not found")
    allowed = {"name", "description", "target", "startDate", "endDate", "reward", "active"}
    update = {k: v for k, v in body.items() if k in allowed}
    if not update:
        raise HTTPException(400, "no updatable fields provided")
    update["updatedAt"] = _now()
    r = await db.loyalty_challenges.find_one_and_update(
        {"$and": [{"id": cid}, tenant_scope_filter(user.get("businessId"))]}, {"$set": update}, return_document=True,
    )
    if not r:
        raise HTTPException(404, "not found")
    r.pop("_id", None)
    return r


@router.get("/progress/{customer_id}")
async def get_progress(customer_id: str, user: dict = Depends(get_user)):
    guard = await db.customers.find_one({**tenant_scope_filter(user.get("businessId")), "id": customer_id}, {"_id": 0, "id": 1, "businessId": 1})
    if guard is None or not tenant_owns(guard.get("businessId"), user.get("businessId")):
        raise HTTPException(404, "Customer not found")
    return await get_customer_progress(customer_id)


@router.get("/passport/{customer_id}")
async def get_passport(customer_id: str, user: dict = Depends(get_user)):
    """Staff-facing: does this customer have loyalty accounts at sibling
    locations (same owner), and what does their combined picture look
    like? Anchors the group lookup on this customer's own record rather
    than the caller's business context, so it works the same whichever
    location's staff happen to be looking — deliberately unrestricted by
    the caller's own business (see test_loyalty_passport.py's
    test_staff_passport_endpoint_resolves_from_the_customer_record,
    which exercises exactly this: an arbitrary caller resolving an
    unrelated customer's passport). The aggregation itself still only
    ever combines businesses that share an owner
    (services/loyalty_group.py) — a phone matching across genuinely
    unrelated owners is never aggregated, which is the privacy boundary
    this endpoint actually needs to hold.
    """
    from services import loyalty_group
    customer = await db.customers.find_one({**tenant_scope_filter(user.get("businessId")), "id": customer_id}, {"_id": 0, "phone": 1, "businessId": 1})
    if not customer:
        raise HTTPException(404, "Customer not found")
    if not customer.get("phone"):
        return {"found": False}
    return await loyalty_group.passport_view(customer["phone"], customer.get("businessId"))


GUEST_OTP_TTL_SECONDS = 300      # code is texted, so 5 minutes is generous but not loose
GUEST_OTP_MAX_ATTEMPTS = 5


def _clean_guest_phone(raw: Any) -> str:
    return "".join(ch for ch in str(raw or "") if ch.isdigit() or ch == "+").strip()


def _hash_guest_otp(phone: str, code: str) -> str:
    return hashlib.sha256(f"{phone}:{code}".encode()).hexdigest()


@router.post("/guest-lookup/request-code")
async def guest_lookup_request_code(body: Dict[str, Any]):
    """Step 1 of guest lookup: text a one-time code before revealing anything.

    Before this, /guest-lookup returned name + points + badges to anyone who
    typed in a phone number — the per-IP rate limit slowed down scraping but
    never actually proved the caller owns the phone. This closes that: the
    code has to arrive on that phone before the account details do.

    Always responds the same way regardless of whether the number matches a
    real account, so this endpoint itself can't be used to enumerate which
    numbers are registered customers.
    """
    phone = _clean_guest_phone((body or {}).get("phone"))
    if not phone:
        raise HTTPException(400, "phone is required")

    code = f"{secrets.randbelow(1_000_000):06d}"
    await db.loyalty_guest_otp.update_one(
        {"phone": phone},
        {"$set": {
            "phone": phone,
            "codeHash": _hash_guest_otp(phone, code),
            "attempts": 0,
            "createdAt": datetime.now(timezone.utc),
            "expiresAt": datetime.now(timezone.utc) + timedelta(seconds=GUEST_OTP_TTL_SECONDS),
        }},
        upsert=True,
    )
    # Best-effort — send_sms no-ops (and logs) when Twilio isn't configured,
    # same graceful-degrade posture as every other notification channel here.
    await send_sms(phone, f"Your NUA rewards code is {code}. It expires in 5 minutes.")
    return {"sent": True}


@router.post("/guest-lookup")
async def guest_lookup(body: Dict[str, Any]):
    """Unauthenticated counterpart to /progress/{customer_id} — lets a
    customer check their own points, tier and badges from their phone
    without asking staff to look it up on a register. No login exists for
    a guest, so phone number is the identifier (the same one checkout
    already keys loyalty accounts on).

    Now requires a `code` from /guest-lookup/request-code first — proof the
    caller actually holds the phone, not just knows the number.

    Deliberately minimal, same posture as /vouchers/public-check: an
    unauthenticated caller gets first name only, never the full customer
    record (email, address, full name, id). A phone that matches nothing
    gets the same generic response as a genuine miss, so this can't be
    used to enumerate which numbers are registered customers.
    """
    phone = _clean_guest_phone((body or {}).get("phone"))
    code = "".join(ch for ch in str((body or {}).get("code", "")) if ch.isdigit())
    if not phone:
        raise HTTPException(400, "phone is required")
    if not code:
        raise HTTPException(400, "code is required")

    otp = await db.loyalty_guest_otp.find_one({"phone": phone})
    if not otp:
        raise HTTPException(401, "Enter the code we texted you, or request a new one")
    if otp.get("attempts", 0) >= GUEST_OTP_MAX_ATTEMPTS:
        raise HTTPException(401, "Too many attempts — request a new code")
    expires = otp.get("expiresAt")
    if hasattr(expires, "tzinfo") and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if not expires or expires < datetime.now(timezone.utc):
        raise HTTPException(401, "That code expired — request a new one")
    if otp.get("codeHash") != _hash_guest_otp(phone, code):
        await db.loyalty_guest_otp.update_one({"phone": phone}, {"$inc": {"attempts": 1}})
        raise HTTPException(401, "That code didn't match")

    # Single use — burn it the moment it's spent, win or lose.
    await db.loyalty_guest_otp.delete_one({"phone": phone})

    from routes.online_orders import resolve_or_require_business_id
    business_id = await resolve_or_require_business_id(body.get("business"))
    customer = await db.customers.find_one({**tenant_scope_filter(business_id), "phone": phone}, {"_id": 0, "id": 1, "name": 1, "businessId": 1})
    if not customer:
        return {"found": False}

    progress = await get_customer_progress(customer["id"], business_id=business_id)
    if progress.get("error"):
        return {"found": False}

    # If this phone also has an account at a sibling location (same owner,
    # different venue), surface the combined picture instead of leaving the
    # guest to think the one record found here is their whole relationship.
    from services import loyalty_group
    business_id = customer.get("businessId")
    passport = await loyalty_group.passport_view(phone, business_id)

    # Points/tier/badges/milestones and any paid membership are two
    # separate systems (routes/v25_suite.py's subscriptions) linked only
    # by customerId, not to each other — folded into this one guest
    # response so "my rewards" is a single place to look rather than
    # requiring the guest to know a paid plan is a whole different thing
    # to check. Read-only here: enrollment/cancellation stays a staff
    # action (routes/v25_suite.py), this only ever surfaces status.
    subscription = None
    sub = await db.subscriptions.find_one(
        {"$and": [tenant_scope_filter(business_id),
                  {"customerId": customer["id"], "status": "active"}]},
        {"_id": 0},
    )
    if sub:
        plan = await db.subscription_plans.find_one(
            {"$and": [tenant_scope_filter(business_id), {"id": sub.get("planId")}]},
            {"_id": 0, "name": 1, "perks": 1},
        )
        subscription = {"planName": (plan or {}).get("name"), "perks": (plan or {}).get("perks") or []}

    first_name = (customer.get("name") or "").strip().split(" ")[0] or "there"
    return {
        "found": True,
        "firstName": first_name,
        "points": progress["points"],
        "tier": progress["tier"],
        "tierProgress": progress["tierProgress"],
        "badges": [b for b in progress["badges"] if b["earned"]],
        "passport": passport if passport.get("isMultiLocation") else None,
        "milestones": progress["milestones"],
        "subscription": subscription,
    }


@router.post("/evaluate/{customer_id}")
async def evaluate(customer_id: str, user: dict = Depends(get_user)):
    guard = await db.customers.find_one({**tenant_scope_filter(user.get("businessId")), "id": customer_id}, {"_id": 0, "id": 1, "businessId": 1})
    if guard is None or not tenant_owns(guard.get("businessId"), user.get("businessId")):
        raise HTTPException(404, "Customer not found")
    return await evaluate_customer(customer_id)


# ═════════════════════════════════════════════════════════════════════════
# Loyalty 2.0 phase-2 — Referrals + Leaderboard
# ═════════════════════════════════════════════════════════════════════════

REFERRAL_REWARD_REFERRER = {"type": "voucher", "value": 20, "label": "$20 referrer voucher"}
REFERRAL_REWARD_REFEREE = {"type": "voucher", "value": 10, "label": "$10 welcome voucher"}


@router.post("/referrals")
async def create_referral(body: dict, user: dict = Depends(get_user)):
    """Referrer invites a friend. Body: {referrerId, refereeEmail} or
    {referrerId, refereeId}. Creates a pending referral; when the referee's
    first transaction posts (see `/api/loyalty/v2/referrals/{id}/complete`),
    both parties collect their voucher and Insight #14 gets refreshed."""
    referrer_id = body.get("referrerId")
    referee_email = body.get("refereeEmail")
    referee_id = body.get("refereeId")
    if not referrer_id or not (referee_email or referee_id):
        raise HTTPException(400, "referrerId + refereeEmail (or refereeId) required")
    business_id = user.get("businessId")
    referrer = await db.customers.find_one({**tenant_scope_filter(user.get("businessId")), "id": referrer_id}, {"_id": 0})
    if not referrer or not tenant_owns(referrer.get("businessId"), business_id):
        raise HTTPException(404, "referrer not found")
    if referee_id:
        referee_guard = await db.customers.find_one({**tenant_scope_filter(user.get("businessId")), "id": referee_id}, {"_id": 0, "id": 1, "businessId": 1})
        if referee_guard is None or not tenant_owns(referee_guard.get("businessId"), business_id):
            raise HTTPException(404, "referee not found")

    # De-dup: same referrer + referee pending / active
    dup_q: Dict[str, Any] = {"referrerId": referrer_id}
    if referee_id: dup_q["refereeId"] = referee_id
    elif referee_email: dup_q["refereeEmail"] = referee_email
    existing = await db.loyalty_referrals.find_one(dup_q, {"_id": 0})
    if existing:
        return existing

    doc = {
        "id": str(uuid.uuid4()),
        "referrerId": referrer_id,
        "referrerName": referrer.get("name"),
        "refereeId": referee_id,
        "refereeEmail": referee_email,
        "code": (referrer.get("name") or "friend")[:6].upper().replace(" ", "") + "-" + str(uuid.uuid4())[:4].upper(),
        "status": "pending",
        "referrerRewardId": None,
        "refereeRewardId": None,
        "createdAt": _now(),
        "createdBy": user.get("email"),
        "businessId": business_id,
    }
    await db.loyalty_referrals.insert_one(dict(doc))
    return doc


@router.get("/referrals")
async def list_referrals(referrerId: Optional[str] = None, status: Optional[str] = None,
                          user: dict = Depends(get_user)):
    q: Dict[str, Any] = {}
    if referrerId: q["referrerId"] = referrerId
    if status: q["status"] = status
    q = {"$and": [q, tenant_scope_filter(user.get("businessId"))]} if q else tenant_scope_filter(user.get("businessId"))
    return await db.loyalty_referrals.find(q, {"_id": 0}).sort("createdAt", -1).to_list(200)


@router.post("/referrals/{ref_id}/complete")
async def complete_referral(ref_id: str, body: dict, user: dict = Depends(get_user)):
    """Fire once the referee has made their qualifying first transaction.
    Body optionally { refereeId } — used when the invite was email-only."""
    business_id = user.get("businessId")
    r = await db.loyalty_referrals.find_one({"$and": [{"id": ref_id}, tenant_scope_filter(business_id)]}, {"_id": 0})
    if r is None or not tenant_owns_strict(r.get("businessId"), business_id):
        raise HTTPException(404, "referral not found")
    if r["status"] == "completed":
        return r

    referee_id = body.get("refereeId") or r.get("refereeId")
    if not referee_id:
        raise HTTPException(400, "refereeId is required")
    referee_guard = await db.customers.find_one({**tenant_scope_filter(user.get("businessId")), "id": referee_id}, {"_id": 0, "id": 1, "businessId": 1})
    if referee_guard is None or not tenant_owns(referee_guard.get("businessId"), business_id):
        raise HTTPException(404, "referee not found")

    from routes.commerce_v29 import _issue_voucher

    async def _issue_referral_voucher(cust_id: str, reward: Dict[str, Any]) -> Dict[str, Any]:
        cust = await db.customers.find_one({**tenant_scope_filter(user.get("businessId")), "id": cust_id}, {"_id": 0, "businessId": 1})
        return await _issue_voucher({
            "sourceType": "loyalty_referral", "sourceRef": ref_id,
            "label": reward.get("label"), "valueType": "amount",
            "value": float(reward.get("value") or 0),
            "customerId": cust_id, "businessId": (cust or {}).get("businessId"),
        })
    referrer_v = await _issue_referral_voucher(r["referrerId"], REFERRAL_REWARD_REFERRER)
    referee_v = await _issue_referral_voucher(referee_id, REFERRAL_REWARD_REFEREE)

    await db.customers.update_one({**tenant_scope_filter(user.get("businessId")), "id": r["referrerId"]}, {"$inc": {"referrals": 1}})
    await db.loyalty_referrals.update_one({"$and": [{"id": ref_id}, tenant_scope_filter(business_id)]}, {"$set": {
        "status": "completed", "refereeId": referee_id,
        "referrerRewardId": referrer_v["id"], "refereeRewardId": referee_v["id"],
        "completedAt": _now(), "completedBy": user.get("email"),
    }})

    # Re-evaluate referrer — 3 referrals unlocks the Community Builder badge
    await evaluate_customer(r["referrerId"])

    try:
        from services import notification_service as ns
        await ns.send(role="marketing", kind="referral", severity="notice",
                        title=f"Referral completed by {r.get('referrerName')}",
                        body=f"Both parties earned vouchers (${REFERRAL_REWARD_REFERRER['value']} / ${REFERRAL_REWARD_REFEREE['value']}).",
                        link="/loyalty-progress",
                        data={"referralId": ref_id})
    except Exception:
        pass
    return await db.loyalty_referrals.find_one({"$and": [{"id": ref_id}, tenant_scope_filter(business_id)]}, {"_id": 0})


@router.get("/leaderboard")
async def leaderboard(metric: str = "points", limit: int = 20, user: dict = Depends(get_user)):
    """Top customers by metric ∈ {points, visits, spend, referrals}.

    field_map previously pointed at loyaltyPoints/totalVisits/totalSpend —
    none of which exist on the Customer model (models/customer.py has
    points/visits/totalSpent) — so `{field: {"$gt": 0}}` matched zero real
    customers for 3 of the 4 metrics. The leaderboard has been effectively
    empty since it was built. Response keys are kept as-is (the frontend
    already reads totalVisits/totalSpend/loyaltyPoints) — only the Mongo
    field names driving the query/sort/projection needed fixing.
    """
    field_map = {
        "points": "points", "visits": "visits",
        "spend": "totalSpent", "referrals": "referrals",
    }
    field = field_map.get(metric, "points")
    query = {"$and": [tenant_scope_filter(user.get("businessId")), {field: {"$gt": 0}}]}
    rows = await db.customers.find(
        query,
        {"_id": 0, "id": 1, "name": 1, "email": 1, "membershipTier": 1,
          "points": 1, "visits": 1, "totalSpent": 1, "referrals": 1},
    ).sort(field, -1).limit(limit).to_list(limit)
    return {
        "metric": metric,
        "entries": [
            {"rank": i + 1, "customerId": r["id"], "name": r.get("name") or r.get("email"),
             "tier": r.get("membershipTier"),
             "value": r.get(field, 0),
             "loyaltyPoints": r.get("points", 0),
             "totalVisits": r.get("visits", 0),
             "totalSpend": r.get("totalSpent", 0),
             "referrals": r.get("referrals", 0)}
            for i, r in enumerate(rows)
        ],
    }
