from fastapi import APIRouter, HTTPException, Depends
from typing import Optional
from datetime import datetime
from database import db
from deps import get_user, require_owner, require_owner_or_manager
from middleware.actor_context import tenant_scope_filter, tenant_owns_strict
from models.loyalty import Event, EventCreate
import uuid

router = APIRouter()

# ============ LOYALTY PROGRAM API ============
@router.get("/loyalty/rewards")
async def get_loyalty_rewards(user: dict = Depends(get_user)):
    rewards = await db.loyalty_rewards.find(tenant_scope_filter(user.get("businessId")), {"_id": 0}).to_list(100)
    return rewards

@router.post("/loyalty/rewards")
async def create_loyalty_reward(reward: dict, user: dict = Depends(require_owner_or_manager)):
    reward_id = f"REWARD-{str(uuid.uuid4())[:8].upper()}"
    reward_doc = {"id": reward_id, **{k: v for k, v in reward.items() if k != "id"},
                  "createdAt": datetime.utcnow().isoformat(), "businessId": user.get("businessId")}
    await db.loyalty_rewards.insert_one(reward_doc)
    reward_doc.pop("_id", None)
    return reward_doc

@router.delete("/loyalty/rewards/{reward_id}")
async def delete_loyalty_reward(reward_id: str, user: dict = Depends(require_owner_or_manager)):
    existing = await db.loyalty_rewards.find_one({"$and": [{"id": reward_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0, "businessId": 1})
    if existing and tenant_owns_strict(existing.get("businessId"), user.get("businessId")):
        await db.loyalty_rewards.delete_one({"$and": [{"id": reward_id}, tenant_scope_filter(user.get("businessId"))]})
    return {"message": "Reward deleted"}

# NOTE: POST /loyalty/redeem is owned by routes/loyalty_engine.py (the modern,
# auth-protected earn/redeem engine). The legacy unprotected redeem handler
# that used to live here was removed in iteration 36 — it was being registered
# first by server.py and shadowing the protected version, creating a points
# bypass. Do not re-add it here. If you need anonymous redemption (e.g. via
# QR code), wire it through a signed redemption token instead.

# discountPercent below matches what routes/transactions.py has hardcoded at
# checkout for as long as that hardcoding has existed (Bronze/Gold had no
# discount perk text at all despite Gold silently getting 5% off in code) —
# seeding it here first, rather than starting everyone at 0%, means turning
# on the tiers-drive-checkout wiring doesn't change anyone's pricing on day one.
@router.get("/loyalty/tiers")
async def get_loyalty_tiers(user: dict = Depends(require_owner_or_manager)):
    biz = user.get("businessId")
    tiers = await db.loyalty_tiers.find(tenant_scope_filter(biz), {"_id": 0}).to_list(20)
    if not tiers:
        # Seed defaults. Note the tier ids ("tier-bronze" etc.) are fixed,
        # shared literals, not unique per business — businessId is what
        # keeps two businesses' seeded copies from colliding on the same
        # document once each has seeded their own.
        defaults = [
            {"id": "tier-bronze", "name": "Bronze", "minPoints": 0, "multiplier": 1.0, "discountPercent": 0, "perks": ["1x points earning", "Birthday reward"]},
            {"id": "tier-silver", "name": "Silver", "minPoints": 500, "multiplier": 1.25, "discountPercent": 3, "perks": ["1.25x points", "3% discount", "Priority waitlist"]},
            {"id": "tier-gold", "name": "Gold", "minPoints": 2000, "multiplier": 1.5, "discountPercent": 5, "perks": ["1.5x points", "5% discount", "Free dessert monthly", "VIP section access", "Early event booking"]},
            {"id": "tier-platinum", "name": "Platinum", "minPoints": 5000, "multiplier": 2.0, "discountPercent": 10, "perks": ["2x points", "10% discount", "Personal host", "Chef's table access", "Complimentary valet"]},
        ]
        for d in defaults:
            await db.loyalty_tiers.insert_one({**d, "businessId": biz})
        return defaults
    return tiers

@router.put("/loyalty/tiers/{tier_id}")
async def update_loyalty_tier(tier_id: str, data: dict, user: dict = Depends(require_owner)):
    allowed = {"name", "minPoints", "multiplier", "discountPercent", "perks"}
    update = {k: v for k, v in data.items() if k in allowed}
    result = await db.loyalty_tiers.find_one_and_update(
        {"id": tier_id, **tenant_scope_filter(user.get("businessId"))}, {"$set": update}, return_document=True
    )
    if not result:
        raise HTTPException(status_code=404, detail="Tier not found")
    result.pop("_id", None)
    return result

@router.put("/loyalty/rewards/{reward_id}")
async def update_loyalty_reward(reward_id: str, data: dict, user: dict = Depends(require_owner_or_manager)):
    allowed = {"name", "description", "pointsCost", "rewardType", "discountAmount", "startDate", "startTime", "endDate", "endTime"}
    update = {k: v for k, v in data.items() if k in allowed}
    result = await db.loyalty_rewards.find_one_and_update(
        {"id": reward_id, **tenant_scope_filter(user.get("businessId"))}, {"$set": update}, return_document=True
    )
    if not result:
        raise HTTPException(status_code=404, detail="Reward not found")
    result.pop("_id", None)
    return result

# ============ EVENTS & EXPERIENCES API ============
# All four of these had no Depends at all — create/update in particular
# meant anyone with any valid staff token, of any business, could create
# or modify any other business's events, and every business's event list
# was mixed together with no scoping.
@router.get("/events")
async def get_events(active_only: bool = True, user: dict = Depends(get_user)):
    query = tenant_scope_filter(user.get("businessId"))
    if active_only:
        query["isActive"] = True
    events = await db.events.find(query, {"_id": 0}).to_list(100)
    return events

@router.post("/events")
async def create_event(event: EventCreate, user: dict = Depends(require_owner_or_manager)):
    event_obj = Event(**event.dict())
    doc = {**event_obj.dict(), "businessId": user.get("businessId")}
    await db.events.insert_one(doc)
    doc.pop("_id", None)
    return doc

@router.put("/events/{event_id}")
async def update_event(event_id: str, update: dict, user: dict = Depends(require_owner_or_manager)):
    update_data = {k: v for k, v in update.items() if k != "id"}
    result = await db.events.find_one_and_update(
        {"id": event_id, **tenant_scope_filter(user.get("businessId"))}, {"$set": update_data}, return_document=True
    )
    if not result:
        raise HTTPException(status_code=404, detail="Event not found")
    result.pop("_id", None)
    return result

@router.post("/events/{event_id}/book")
async def book_event_ticket(event_id: str, customer_id: Optional[str] = None, quantity: int = 1,
                              user: dict = Depends(get_user)):
    result = await db.events.find_one_and_update(
        {"id": event_id, **tenant_scope_filter(user.get("businessId"))},
        {"$inc": {"ticketsBooked": quantity}},
        return_document=True
    )
    if not result:
        raise HTTPException(status_code=404, detail="Event not found")
    result.pop("_id", None)
    return {"message": f"{quantity} ticket(s) booked", "event": result}

# ============ QR MENU GENERATOR API ============
@router.get("/menu/qr-data")
async def get_qr_menu_data(user: dict = Depends(get_user)):
    products = await db.products.find(tenant_scope_filter(user.get("businessId")), {"_id": 0}).to_list(1000)
    categories = {}
    for p in products:
        cat = p.get("category", "Other")
        if cat not in categories:
            categories[cat] = {"name": cat, "items": []}
        categories[cat]["items"].append({
            "name": p["name"], "price": p.get("price", 0),
            "description": p.get("description", ""),
            "dietary": p.get("dietary", []),
            "allergens": p.get("allergens", []),
            "available": p.get("stock", 0) > 0,
        })
    return {"categories": list(categories.values()), "restaurantName": "NUA", "lastUpdated": datetime.utcnow().isoformat()}
