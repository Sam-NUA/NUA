"""
HQ / Franchise scaffolding — cross-location roll-ups.

Uses the existing `businesses` collection with an optional `parentBrandId`
to define a franchise group. `X-Business-Id` and `X-Location-Id` headers
are honoured by the actor middleware; this router aggregates.
"""
from fastapi import APIRouter, Depends
from typing import Optional
from datetime import datetime, timezone, timedelta
from database import db
from deps import get_user

router = APIRouter(prefix="/hq")


async def _brand_scope_business_ids(user_business_id: Optional[str]) -> Optional[list]:
    """Every businessId in the CALLER's own franchise/brand group — the
    brand root (a business with no parentBrandId) plus every location
    whose parentBrandId points at it. This router's whole purpose is
    cross-LOCATION rollups within one brand, not a platform-wide view:
    none of the four endpoints below checked which brand a location
    belonged to before this fix, so /hq/kpi-roll-up and /hq/leaderboard
    aggregated db.transactions across literally every business on the
    deployment — any logged-in staff member could see every other
    (unrelated) tenant's revenue, covers, and GST, not just sibling
    locations under their own brand. None = no scoping possible (unknown
    caller), same safe-default tenant_scope_filter uses elsewhere.
    """
    if not user_business_id:
        return None
    me = await db.businesses.find_one({"id": user_business_id}, {"_id": 0})
    root_id = (me or {}).get("parentBrandId") or user_business_id
    siblings = await db.businesses.find(
        {"$or": [{"id": root_id}, {"parentBrandId": root_id}]}, {"_id": 0, "id": 1}
    ).to_list(500)
    ids = {s["id"] for s in siblings}
    ids.add(user_business_id)
    return list(ids)


@router.get("/brands")
async def brands(user: dict = Depends(get_user)):
    """The caller's own brand group only (business docs with
    `parentBrandId` = null) — not every brand on the deployment."""
    scope_ids = await _brand_scope_business_ids(user.get("businessId"))
    query = {"$or": [{"parentBrandId": None}, {"parentBrandId": {"$exists": False}}]}
    if scope_ids is not None:
        query = {"$and": [query, {"id": {"$in": scope_ids}}]}
    rows = await db.businesses.find(query, {"_id": 0}).to_list(100)
    return rows


@router.get("/locations")
async def locations(brand_id: Optional[str] = None, user: dict = Depends(get_user)):
    scope_ids = await _brand_scope_business_ids(user.get("businessId"))
    q = {"parentBrandId": brand_id} if brand_id else {}
    if scope_ids is not None:
        q = {"$and": [q, {"id": {"$in": scope_ids}}]} if q else {"id": {"$in": scope_ids}}
    rows = await db.businesses.find(q, {"_id": 0}).to_list(500)
    return rows


@router.get("/kpi-roll-up")
async def kpi_roll_up(days: int = 7, user: dict = Depends(get_user)):
    """Aggregate revenue, covers, refunds by locationId across the network."""
    scope_ids = await _brand_scope_business_ids(user.get("businessId"))
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    match = {"timestamp": {"$gte": since}}
    if scope_ids is not None:
        match["businessId"] = {"$in": scope_ids}
    pipeline = [
        {"$match": match},
        {"$group": {
            "_id": {"$ifNull": ["$locationId", "$location"]},
            "revenue": {"$sum": "$total"},
            "covers": {"$sum": 1},
            "gst": {"$sum": "$gst"},
        }},
        {"$sort": {"revenue": -1}},
    ]
    rows = await db.transactions.aggregate(pipeline).to_list(200)
    total_rev = round(sum(r.get("revenue") or 0 for r in rows), 2)
    return {
        "days": days,
        "totalRevenue": total_rev,
        "locations": [
            {"location": r["_id"] or "Unassigned", "revenue": round(r.get("revenue") or 0, 2),
             "covers": r.get("covers") or 0, "gst": round(r.get("gst") or 0, 2)}
            for r in rows
        ],
    }


@router.get("/leaderboard")
async def leaderboard(user: dict = Depends(get_user)):
    """Rank locations by 30-day revenue — within the caller's own brand."""
    scope_ids = await _brand_scope_business_ids(user.get("businessId"))
    since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    match = {"timestamp": {"$gte": since}}
    if scope_ids is not None:
        match["businessId"] = {"$in": scope_ids}
    pipeline = [
        {"$match": match},
        {"$group": {"_id": {"$ifNull": ["$locationId", "$location"]}, "revenue": {"$sum": "$total"}}},
        {"$sort": {"revenue": -1}},
        {"$limit": 10},
    ]
    rows = await db.transactions.aggregate(pipeline).to_list(10)
    return [{"rank": i + 1, "location": r["_id"] or "Unassigned", "revenue": round(r.get("revenue") or 0, 2)}
             for i, r in enumerate(rows)]
