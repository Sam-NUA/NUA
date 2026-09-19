from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from deps import get_user, optional_user, require_owner, require_owner_or_manager
from database import db
from middleware.actor_context import tenant_scope_filter, tenant_owns_strict
from datetime import datetime, timezone
import uuid

router = APIRouter()

# ============ TABLE COMBINATIONS ============
@router.get("/tables/combinations")
async def get_table_combinations(user: dict = Depends(get_user)):
    combos = await db.table_combinations.find(tenant_scope_filter(user.get("businessId")), {"_id": 0}).to_list(200)
    return combos

@router.post("/tables/combinations")
async def create_table_combination(data: dict, user: dict = Depends(require_owner_or_manager)):
    combo = {
        "id": f"COMBO-{str(uuid.uuid4())[:8].upper()}",
        "name": data.get("name", f"Combo {data.get('tableIds', [])}"),
        "tableIds": data.get("tableIds", []),
        "maxCovers": data.get("maxCovers", 0),
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "businessId": user.get("businessId"),
    }
    await db.table_combinations.insert_one(combo)
    combo.pop("_id", None)
    return combo

@router.delete("/tables/combinations/{combo_id}")
async def delete_table_combination(combo_id: str, user: dict = Depends(require_owner_or_manager)):
    existing = await db.table_combinations.find_one({"$and": [{"id": combo_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0, "businessId": 1})
    if not existing or not tenant_owns_strict(existing.get("businessId"), user.get("businessId")):
        return {"message": "Combination deleted"}  # matches the prior no-op-on-missing-id behavior
    await db.table_combinations.delete_one({"$and": [{"id": combo_id}, tenant_scope_filter(user.get("businessId"))]})
    return {"message": "Combination deleted"}

# ============ BOOKING RULES & SETTINGS ============
@router.get("/booking/rules")
async def get_booking_rules(business: Optional[str] = None, user: dict = Depends(optional_user)):
    from services.booking_rules_engine import get_rules
    from routes.online_orders import resolve_or_require_business_id
    business_id = user["businessId"] if user else await resolve_or_require_business_id(business)
    return await get_rules(business_id=business_id)

@router.post("/booking/rules")
async def save_booking_rules(data: dict, user: dict = Depends(require_owner)):
    from services.tenant_settings import get_setting, set_setting
    before = await get_setting("booking_rules", user["businessId"])
    await set_setting("booking_rules", data, user["businessId"])
    from services import audit_service
    await audit_service.log_event(
        entity_type="booking_rules", entity_id="booking_rules", action="updated",
        before=before, after=data,
        memo=f"Booking rules updated by {user.get('email', 'owner')}", severity="notice",
        tags=["booking_rules"],
    )
    return {"message": "Booking rules saved"}

# ============ BOOKING SCHEDULE (Shifts) ============
@router.get("/booking/schedule")
async def get_booking_schedule(user: dict = Depends(get_user)):
    shifts = await db.booking_shifts.find(tenant_scope_filter(user.get("businessId")), {"_id": 0}).to_list(50)
    if not shifts:
        return [
            {"id": "shift-breakfast", "name": "Breakfast", "startTime": "07:00", "endTime": "11:00", "interval": 30, "tables": [], "enabled": True},
            {"id": "shift-lunch", "name": "Lunch", "startTime": "11:30", "endTime": "15:00", "interval": 30, "tables": [], "enabled": True},
            {"id": "shift-dinner", "name": "Dinner", "startTime": "17:00", "endTime": "22:00", "interval": 30, "tables": [], "enabled": True},
        ]
    return shifts

@router.post("/booking/schedule")
async def save_booking_schedule(data: dict, user: dict = Depends(require_owner_or_manager)):
    shifts = data.get("shifts", [])
    biz = user.get("businessId")
    # Only replaces this business's own shifts — the old delete_many({})
    # wiped every business's schedule on the deployment every time any one
    # of them saved theirs.
    await db.booking_shifts.delete_many(tenant_scope_filter(biz))
    for s in shifts:
        if not s.get("id"):
            s["id"] = f"shift-{str(uuid.uuid4())[:8]}"
        s["businessId"] = biz
        await db.booking_shifts.insert_one(s)
    return {"message": f"{len(shifts)} shifts saved"}

# ============ BOOKING EXPERIENCES ============
@router.get("/booking/experiences")
async def get_experiences(business: Optional[str] = None, user=Depends(optional_user)):
    from routes.online_orders import resolve_or_require_business_id
    biz = user["businessId"] if user else await resolve_or_require_business_id(business)
    exps = await db.booking_experiences.find(tenant_scope_filter(biz), {"_id": 0}).to_list(50)
    return exps

@router.post("/booking/experiences")
async def create_experience(data: dict, user: dict = Depends(require_owner_or_manager)):
    exp = {
        "id": f"EXP-{str(uuid.uuid4())[:8].upper()}",
        "name": data.get("name", ""), "description": data.get("description", ""),
        "days": data.get("days", []),  # ["Monday","Friday",...]
        "startDate": data.get("startDate"), "endDate": data.get("endDate"),
        "pricePerPerson": data.get("pricePerPerson", 0),
        "maxBookings": data.get("maxBookings", 50),
        "active": data.get("active", True),
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "businessId": user.get("businessId"),
    }
    await db.booking_experiences.insert_one(exp)
    exp.pop("_id", None)
    return exp

@router.put("/booking/experiences/{exp_id}")
async def update_experience(exp_id: str, data: dict, user: dict = Depends(require_owner_or_manager)):
    existing = await db.booking_experiences.find_one({"$and": [{"id": exp_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0, "businessId": 1})
    if not existing or not tenant_owns_strict(existing.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Not found")
    data = {k: v for k, v in data.items() if k not in ("id", "_id", "businessId", "_ownershipQuarantined")}
    result = await db.booking_experiences.find_one_and_update({"$and": [{"id": exp_id}, tenant_scope_filter(user.get("businessId"))]}, {"$set": data}, return_document=True)
    if not result:
        raise HTTPException(status_code=404, detail="Not found")
    result.pop("_id", None)
    return result

@router.delete("/booking/experiences/{exp_id}")
async def delete_experience(exp_id: str, user: dict = Depends(require_owner_or_manager)):
    existing = await db.booking_experiences.find_one({"$and": [{"id": exp_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0, "businessId": 1})
    if existing and tenant_owns_strict(existing.get("businessId"), user.get("businessId")):
        await db.booking_experiences.delete_one({"$and": [{"id": exp_id}, tenant_scope_filter(user.get("businessId"))]})
    return {"message": "Experience deleted"}

# ============ CLUBMEMBER OFFERS (EatClub-style) ============
@router.get("/clubmember/offers")
async def get_club_offers(user=Depends(optional_user)):
    # Also guest-reachable (claim below is fully public) — same
    # unscoped-for-guests caveat as booking/experiences above.
    biz = user.get("businessId") if user else None
    offers = await db.club_offers.find(tenant_scope_filter(biz), {"_id": 0}).to_list(100)
    return offers

@router.post("/clubmember/offers")
async def create_club_offer(data: dict, user: dict = Depends(require_owner)):
    discount = data.get("discount", 20)
    if discount < 20 or discount > 50:
        raise HTTPException(status_code=400, detail="Discount must be between 20% and 50%")
    offer = {
        "id": f"CLUB-{str(uuid.uuid4())[:8].upper()}",
        "title": data.get("title", ""), "description": data.get("description", ""),
        "discount": discount,
        "startDate": data.get("startDate"), "startTime": data.get("startTime", "00:00"),
        "endDate": data.get("endDate"), "endTime": data.get("endTime", "23:59"),
        "totalSlots": data.get("totalSlots", 10),
        "claimedSlots": 0, "active": data.get("active", True),
        "socialPlatforms": data.get("socialPlatforms", ["instagram", "facebook"]),
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "businessId": user.get("businessId"),
    }
    await db.club_offers.insert_one(offer)
    offer.pop("_id", None)
    return offer

@router.put("/clubmember/offers/{offer_id}")
async def update_club_offer(offer_id: str, data: dict, user: dict = Depends(require_owner)):
    existing = await db.club_offers.find_one({"$and": [{"id": offer_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0, "businessId": 1})
    if not existing or not tenant_owns_strict(existing.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Not found")
    allowed = {"title", "description", "discount", "startDate", "startTime", "endDate", "endTime", "totalSlots", "active", "socialPlatforms"}
    update = {k: v for k, v in data.items() if k in allowed}
    result = await db.club_offers.find_one_and_update({"$and": [{"id": offer_id}, tenant_scope_filter(user.get("businessId"))]}, {"$set": update}, return_document=True)
    if not result:
        raise HTTPException(status_code=404, detail="Not found")
    result.pop("_id", None)
    return result

@router.delete("/clubmember/offers/{offer_id}")
async def delete_club_offer(offer_id: str, user: dict = Depends(require_owner)):
    existing = await db.club_offers.find_one({"$and": [{"id": offer_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0, "businessId": 1})
    if existing and tenant_owns_strict(existing.get("businessId"), user.get("businessId")):
        await db.club_offers.delete_one({"$and": [{"id": offer_id}, tenant_scope_filter(user.get("businessId"))]})
    return {"message": "Offer deleted"}

# Public endpoint for members to claim
@router.post("/clubmember/offers/{offer_id}/claim")
async def claim_club_offer(offer_id: str, data: dict):
    offer = await db.club_offers.find_one({"id": offer_id})
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")
    if not offer.get("active"):
        raise HTTPException(status_code=400, detail="Offer is no longer active")
    if offer.get("claimedSlots", 0) >= offer.get("totalSlots", 0):
        raise HTTPException(status_code=400, detail="Offer is fully claimed")
    await db.club_offers.update_one({"id": offer_id}, {"$inc": {"claimedSlots": 1}})
    claim = {
        "id": f"CLAIM-{str(uuid.uuid4())[:8].upper()}",
        "offerId": offer_id, "memberName": data.get("name", ""), "memberEmail": data.get("email", ""),
        "discount": offer.get("discount"), "claimedAt": datetime.now(timezone.utc).isoformat(),
    }
    await db.club_claims.insert_one(claim)
    claim.pop("_id", None)
    return claim


# ============ BOOKING ANALYTICS ============
@router.get("/booking/analytics")
async def get_booking_analytics(user: dict = Depends(require_owner_or_manager)):

    reservations = await db.reservations.find(tenant_scope_filter(user.get("businessId")), {"_id": 0}).to_list(50000)
    total = len(reservations)
    no_shows = len([r for r in reservations if r.get("status") == "no_show"])
    no_show_rate = round((no_shows / max(total, 1)) * 100, 1)
    avg_party = round(sum(r.get("partySize", 2) for r in reservations) / max(total, 1), 1)

    # By shift
    by_shift = {}
    for r in reservations:
        t = r.get("time", "12:00")
        if t < "11:00":
            shift = "Breakfast"
        elif t < "15:00":
            shift = "Lunch"
        else:
            shift = "Dinner"
        by_shift[shift] = by_shift.get(shift, {"count": 0, "covers": 0})
        by_shift[shift]["count"] += 1
        by_shift[shift]["covers"] += r.get("partySize", 2)

    # Peak days
    by_day = {}
    for r in reservations:
        day = r.get("date", "")
        if day:
            from datetime import datetime as dt
            try:
                day_name = dt.fromisoformat(day).strftime("%A")
            except Exception:
                day_name = "Unknown"
            by_day[day_name] = by_day.get(day_name, 0) + 1

    peak_days = sorted(by_day.items(), key=lambda x: x[1], reverse=True)[:3]

    return {
        "totalBookings": total, "noShows": no_shows, "noShowRate": no_show_rate,
        "avgPartySize": avg_party,
        "byShift": [{"shift": k, "bookings": v["count"], "covers": v["covers"]} for k, v in by_shift.items()],
        "peakDays": [{"day": d, "bookings": c} for d, c in peak_days],
    }

# ============ SOCIAL MEDIA ACCOUNTS (for Clubmember posting) ============
# These carry real OAuth accessTokens — the most serious finding in this
# file. Unscoped, any owner of any business could list every other
# business's connected social accounts, tokens included.
@router.get("/clubmember/social-accounts")
async def get_social_accounts(user: dict = Depends(require_owner)):
    accounts = await db.social_accounts.find(tenant_scope_filter(user.get("businessId")), {"_id": 0}).to_list(20)
    return accounts

@router.post("/clubmember/social-accounts")
async def add_social_account(data: dict, user: dict = Depends(require_owner)):
    account = {
        "id": f"SOC-{str(uuid.uuid4())[:8].upper()}",
        "platform": data.get("platform", ""),
        "accountName": data.get("accountName", ""),
        "accessToken": data.get("accessToken", ""),
        "connected": True,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "businessId": user.get("businessId"),
    }
    await db.social_accounts.insert_one(account)
    account.pop("_id", None)
    return account

@router.delete("/clubmember/social-accounts/{account_id}")
async def remove_social_account(account_id: str, user: dict = Depends(require_owner)):
    existing = await db.social_accounts.find_one({"$and": [{"id": account_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0, "businessId": 1})
    if existing and tenant_owns_strict(existing.get("businessId"), user.get("businessId")):
        await db.social_accounts.delete_one({"$and": [{"id": account_id}, tenant_scope_filter(user.get("businessId"))]})
    return {"message": "Account removed"}

# ============ TEST EMAIL ============
@router.post("/email/test")
async def send_test_email(data: dict, user: dict = Depends(require_owner_or_manager)):
    recipient = data.get("to", "sambhatt7@gmail.com")
    subject = data.get("subject", "NUA POS Test Email")
    body = data.get("body", "This is a test email from NUA POS system.")

    # Store email record
    email_record = {
        "id": f"EMAIL-{str(uuid.uuid4())[:8].upper()}",
        "to": recipient, "subject": subject, "body": body,
        "status": "sent", "sentAt": datetime.now(timezone.utc).isoformat(),
        "sentBy": user["id"],
        "businessId": user.get("businessId"),
    }
    await db.email_log.insert_one(email_record)
    email_record.pop("_id", None)
    return {"message": f"Test email logged (recipient: {recipient})", "emailId": email_record["id"]}

@router.get("/email/settings")
async def get_email_settings(user: dict = Depends(require_owner)):
    from services.tenant_settings import get_setting
    value = await get_setting("email_config", user.get("businessId"))
    return value or {"testEmail": "sambhatt7@gmail.com", "senderName": "NUA POS", "senderEmail": ""}

@router.post("/email/settings")
async def save_email_settings(data: dict, user: dict = Depends(require_owner)):
    from services.tenant_settings import set_setting
    await set_setting("email_config", data, user.get("businessId"))
    return {"message": "Email settings saved"}
