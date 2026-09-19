"""
Loyalty passport — a guest visiting more than one location owned by the same
operator currently gets a separate, siloed `customers` record per location:
every POS/booking write is stamped with the actor's *current* businessId
(middleware/actor_context.py), and there is no cross-location lookup.
routes/loyalty_v2.py's own guest_lookup proves this is a real gap — its
`db.customers.find_one({"phone": phone})` only ever returns the FIRST
matching record, so a guest with accounts at two sibling venues only ever
sees one of them and has no idea the other exists.

This does not merge records — that's a real migration with real conflict
resolution (which name wins, which notes survive), not a one-round change.
It aggregates: given a phone number and one "anchor" business, find every
other customers record with the same phone at a business sharing the same
owner (the natural definition of "the same chain" — no new field needed,
multi_tenant.py's `businesses.ownerId` already carries that grouping), and
report combined points/spend/visits alongside the per-location breakdown.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional
from database import db


async def sibling_business_ids(business_id: Optional[str]) -> List[str]:
    """Every business sharing an owner with `business_id`, `business_id`
    itself included. Falls back to just [business_id] if the business or
    its owner can't be resolved — never silently expands to "every
    business in the database"."""
    if not business_id:
        return []
    biz = await db.businesses.find_one({"id": business_id}, {"_id": 0, "ownerId": 1})
    if not biz or not biz.get("ownerId"):
        return [business_id]
    rows = await db.businesses.find({"ownerId": biz["ownerId"]}, {"_id": 0, "id": 1}).to_list(200)
    ids = [r["id"] for r in rows]
    return ids if ids else [business_id]


async def find_group_records(phone: str, anchor_business_id: Optional[str]) -> List[Dict[str, Any]]:
    """Verified records in the anchor's ownership group; unknown owners fail closed."""
    if not phone or not anchor_business_id:
        return []
    sib_ids = await sibling_business_ids(anchor_business_id)
    q: Dict[str, Any] = {"phone": phone, "businessId": {"$in": sib_ids},
                         "_ownershipQuarantined": {"$ne": True}}
    return await db.customers.find(q, {"_id": 0}).to_list(50)


async def passport_view(phone: str, anchor_business_id: Optional[str]) -> Dict[str, Any]:
    """Combined points/spend/visits across every location record for this
    phone in the group, plus a per-location breakdown sorted by points."""
    records = await find_group_records(phone, anchor_business_id)
    if not records:
        return {"found": False}

    biz_ids = list({r.get("businessId") for r in records if r.get("businessId")})
    biz_rows = (
        await db.businesses.find({"id": {"$in": biz_ids}}, {"_id": 0, "id": 1, "name": 1}).to_list(200)
        if biz_ids else []
    )
    biz_names = {b["id"]: b["name"] for b in biz_rows}

    # Tier definitions are business-scoped (see routes/loyalty.py) — an
    # unscoped read here would compute the group's displayed tier name
    # from whichever business's tier documents the query happened to hit
    # first, not the anchor business's own. Scoped to the anchor
    # specifically (not the whole sibling group): a multi-location owner
    # could in principle set different tier ladders per venue, and the
    # guest is looking this up from one specific venue's context.
    from middleware.actor_context import tenant_scope_filter
    tiers = await db.loyalty_tiers.find(tenant_scope_filter(anchor_business_id), {"_id": 0}).sort("minPoints", 1).to_list(20)
    group_points = sum(int(r.get("points") or 0) for r in records)
    group_spent = round(sum(float(r.get("totalSpent") or 0) for r in records), 2)
    group_visits = sum(int(r.get("visits") or 0) for r in records)

    group_tier = tiers[0]["name"] if tiers else None
    for t in tiers:
        if group_points >= t["minPoints"]:
            group_tier = t["name"]

    locations = [{
        "customerId": r.get("id"), "businessId": r.get("businessId"),
        "businessName": biz_names.get(r.get("businessId"), r.get("businessId") or "Unknown location"),
        "points": int(r.get("points") or 0), "totalSpent": round(float(r.get("totalSpent") or 0), 2),
        "visits": int(r.get("visits") or 0), "tier": r.get("membershipTier"),
    } for r in records]
    locations.sort(key=lambda x: -x["points"])

    return {
        "found": True,
        "isMultiLocation": len(records) > 1,
        "groupPoints": group_points,
        "groupTotalSpent": group_spent,
        "groupVisits": group_visits,
        "groupTier": group_tier,
        "locations": locations,
    }
