from fastapi import APIRouter, HTTPException, Depends
from datetime import datetime
from typing import Optional
from database import db
from services import reservation_store
from deps import get_user
import uuid
import random

router = APIRouter()


def _public_tenant_filter(business_id: Optional[str]) -> dict:
    from middleware.actor_context import tenant_scope_filter
    return tenant_scope_filter(business_id or "")



# ============ PUBLIC BOOKING PORTAL API ============
@router.get("/public/menu")
async def get_public_menu(business: Optional[str] = None):
    # Reuses routes/online_orders.py's already-shipped, already-proven
    # ?business=<slug-or-id> resolution (the /order-online storefront's own
    # mechanism — see that module's _resolve_business_id docstring) rather
    # than inventing a second one. Resolves to None (fully unscoped, today's
    # exact behavior) when the param is absent or doesn't match any
    # business, so a single-business deployment — the common case — is
    # completely unaffected either way. Imported lazily (matches this
    # codebase's convention for cross-route helpers, e.g.
    # routes/bill_split.py's import of _create_stripe_session) rather than
    # at module load, so router import order at startup can't matter.
    from routes.online_orders import _resolve_business_id
    business_id = await _resolve_business_id(business)
    products = await db.products.find(_public_tenant_filter(business_id), {"_id": 0}).to_list(1000)
    categories = {}
    for p in products:
        cat = p.get("category", "Other")
        if cat not in categories:
            categories[cat] = {"name": cat, "items": []}
        categories[cat]["items"].append({
            "name": p["name"], "price": p.get("price", 0),
            "description": p.get("description", ""),
        })
    return {"categories": list(categories.values())}

@router.get("/public/available-slots")
async def get_available_slots(date: str, party_size: int = 2, business: Optional[str] = None):
    from datetime import date as date_cls
    from services.booking_rules_engine import get_rules, capacity_for_slot, in_time_range
    from routes.online_orders import _resolve_business_id

    business_id = await _resolve_business_id(business)
    biz_filter = _public_tenant_filter(business_id)
    rules = await get_rules(business_id)

    # A whole-day block (blackout or a blocked weekday) means no slot is
    # offered at all — matches what POST /public/book would reject anyway,
    # so the guest sees why up front instead of picking a time and then
    # hitting a 409.
    blackout = await db.booking_blackouts.find_one({"date": date, **biz_filter}, {"_id": 0})
    if blackout:
        return {"date": date, "partySize": party_size, "slots": [], "closed": blackout.get("reason") or "closed"}
    try:
        weekday_name = date_cls.fromisoformat(date).strftime("%A")
    except Exception:
        weekday_name = None
    if weekday_name and weekday_name in (rules.get("blockedWeekdays") or []):
        return {"date": date, "partySize": party_size, "slots": [], "closed": f"Closed on {weekday_name}s"}

    floor_plans = await db.floor_plans.find(biz_filter, {"_id": 0}).to_list(10)
    all_tables = []
    for fp in floor_plans:
        all_tables.extend(fp.get("tables", []))
    suitable_tables = [t for t in all_tables if t.get("maxCovers", 2) >= party_size and t.get("isActive", True)]
    if not suitable_tables:
        suitable_tables = [{"id": "virtual", "maxCovers": 20}]
    reservations = await db.reservations.find({"date": date, **biz_filter}, {"_id": 0}).to_list(500)
    open_t = rules.get("bookingOpenTime") or "00:00"
    close_t = rules.get("bookingCloseTime") or "23:59"
    # If `date` is today, don't offer a time that's already passed — POST
    # /public/book would reject it anyway (see booking_rules_engine's
    # "already passed" check, which uses this same venue-local-time
    # convention, services.venue_time), so showing it as pickable just sets
    # the guest up for a confirm-time 409 instead of a clean slot list.
    from services.venue_time import venue_now_for_business
    now = await venue_now_for_business(business_id)
    is_today = date == now.strftime("%Y-%m-%d")
    now_hhmm = now.strftime("%H:%M")
    slots = []
    for hour in range(11, 22):
        for minute in [0, 30]:
            time_str = f"{hour:02d}:{minute:02d}"
            if is_today and time_str <= now_hhmm:
                continue
            if not in_time_range(time_str, open_t, close_t):
                continue
            occupied = len([r for r in reservations if r.get("time") == time_str and r.get("status") in ("confirmed", "seated")])
            available = len(suitable_tables) - occupied
            if available <= 0:
                continue
            if rules.get("enforceCapacity"):
                cap_info = await capacity_for_slot(date, time_str, rules, business_id=business_id)
                if cap_info["available"] < party_size:
                    continue
            slots.append({"time": time_str, "available": available})
    return {"date": date, "partySize": party_size, "slots": slots}

@router.post("/public/book")
async def public_book_reservation(data: dict):
    """Customer self-service booking — must run through the exact same
    booking_rules_engine as staff's POST /reservations. Previously this path
    had NO rule enforcement at all (not even the blackout-date check the
    staff path already had), so a guest could book straight through a
    closed date or a large-party set-menu requirement just by using the
    public form instead of calling the restaurant.

    The `business` field (same slug-or-id the storefront and the other
    /public/* routes in this file accept) scopes the created reservation to
    a real business and checks rules/capacity/blackouts against that
    business specifically. Previously this was optional and, absent or
    unresolved, silently created an untagged reservation checked against
    rules/capacity pooled across every business on the deployment — whose
    tables and kitchen a guest's booking actually held was genuinely
    ambiguous on any multi-tenant deployment. Now resolved via
    resolve_or_require_business_id: an explicit ?business= still works
    exactly as before; a single-business deployment with no reason to ever
    pass it is unaffected (auto-resolves to that one business); only a
    deployment with more than one business and no ?business= to
    disambiguate is refused (400) rather than guessed."""
    from models.reservation import Reservation
    from services.booking_rules_engine import validate_and_enrich_booking, BookingRuleViolation, capacity_lock
    from services.cancellation_policy import snapshot_cutoff_hours
    from routes.online_orders import resolve_or_require_business_id

    business_id = await resolve_or_require_business_id(data.get("business"))
    party_size = int(data.get("partySize") or 2)
    date = data.get("date", "")
    time = data.get("time", "")
    experience_id = data.get("experienceId")

    try:
        async with capacity_lock(business_id, date):
            enrichment = await validate_and_enrich_booking(
                date=date, time=time, party_size=party_size, source="online",
                experience_id=experience_id, business_id=business_id,
            )
            cutoff_hours = await snapshot_cutoff_hours(business_id)
            res_obj = Reservation(
                cancellationCutoffHours=cutoff_hours,
                guestName=data.get("guestName", "Guest"),
                guestPhone=data.get("guestPhone", ""),
                guestEmail=data.get("guestEmail", ""),
                partySize=party_size,
                date=date,
                time=time,
                duration=data.get("duration", 90),
                specialRequests=data.get("specialRequests", ""),
                source="online",
                businessId=business_id,
                **enrichment,
            )
            await reservation_store.insert_one(res_obj.dict())
    except BookingRuleViolation as e:
        raise HTTPException(status_code=409, detail=str(e))
    except TimeoutError as e:
        raise HTTPException(status_code=409, detail=str(e))
    if res_obj.isLargeBooking:
        from services import audit_service
        await audit_service.log_event(
            entity_type="reservation", entity_id=res_obj.id, action="created",
            after=res_obj.dict(), memo=f"Large booking ({res_obj.partySize} guests) via online booking — "
                                        f"tier: {res_obj.bookingTierLabel}",
            severity="notice", tags=["large_booking"],
        )
    message = "Reservation booked successfully!"
    if res_obj.isLargeBooking:
        message = f"Booked with {res_obj.experienceName or res_obj.bookingTierLabel}. " + message
    return {
        "reservationId": res_obj.id, "status": "confirmed", "message": message,
        "isLargeBooking": res_obj.isLargeBooking, "bookingTierLabel": res_obj.bookingTierLabel,
        "experienceName": res_obj.experienceName, "depositRequired": res_obj.depositRequired,
        "preOrderRequired": res_obj.preOrderRequired, "approvalRequired": res_obj.approvalRequired,
    }

@router.post("/public/join-waitlist")
async def public_join_waitlist(data: dict):
    # The `business` field (same slug-or-id as the rest of this file's
    # routes) scopes both the created entry and the queue-position
    # calculation to a real business — previously optional, which meant an
    # absent/unresolved value silently created an untagged entry pooled
    # into every business's waitlist. Now resolved the same way booking is
    # (resolve_or_require_business_id): a single-business deployment is
    # unaffected; an ambiguous multi-business one without ?business= is
    # refused (400) instead of pooled.
    from models.waitlist import WaitlistEntry
    from routes.online_orders import resolve_or_require_business_id

    business_id = await resolve_or_require_business_id(data.get("business"))
    waiting_query = {"status": "waiting", **_public_tenant_filter(business_id)}
    last = await db.waitlist.find(waiting_query).sort("position", -1).to_list(1)
    next_pos = (last[0]["position"] + 1) if last else 1
    entry = WaitlistEntry(
        guestName=data.get("guestName", "Guest"),
        guestPhone=data.get("guestPhone", ""),
        partySize=data.get("partySize", 2),
        preferences=data.get("preferences", ""),
        position=next_pos,
        businessId=business_id,
    )
    await db.waitlist.insert_one(entry.dict())
    # id is the guest's tracking code for GET /waitlist/track/{id} — without
    # it there was no way to hand the guest anything to check their status
    # with later, only the one-time position/estimate from this response.
    return {"id": entry.id, "position": next_pos, "estimatedWait": next_pos * random.randint(8, 15)}

@router.get("/public/events")
async def get_public_events(business: Optional[str] = None):
    from routes.online_orders import _resolve_business_id
    business_id = await _resolve_business_id(business)
    events = await db.events.find({"isActive": True, **_public_tenant_filter(business_id)}, {"_id": 0}).to_list(50)
    return events

# ============ QR PAYMENT API ============
# Despite living in this file, these three routes carry no "/public/" path
# segment (router has no prefix), so they're NOT on PUBLIC_API_PREFIXES/
# PUBLIC_API_PATHS and RequireAuthMiddleware already 401s a request with no
# credential at all. The gap found during the final readiness audit was
# narrower but still real: with some valid staff token (any business) and
# no businessId anywhere on db.payments/db.split_payments, a staff member
# at business A could list, guess, or enumerate business B's QR-UPI payment
# or split-payment record by its id — an 8-hex/~32-bit value, weak enough
# to make guessing practical. Fixed: explicit Depends(get_user) (defense in
# depth on top of the middleware), businessId stamped at creation and
# required on every lookup/mutation, and ids widened to a full uuid4 hex.
@router.post("/payments/generate-qr")
async def generate_payment_qr(data: dict, user: dict = Depends(get_user)):
    amount = data.get("amount", 0)
    transaction_id = data.get("transactionId", f"TXN-{uuid.uuid4().hex.upper()}")
    method = data.get("method", "upi")
    merchant_upi = data.get("merchantUpi", "nua@upi")
    merchant_name = data.get("merchantName", "NUA Restaurant")
    note = data.get("note", f"Payment for order {transaction_id}")
    upi_string = f"upi://pay?pa={merchant_upi}&pn={merchant_name}&am={amount:.2f}&tn={note}&tr={transaction_id}"
    payment_record = {
        "id": f"PAY-{uuid.uuid4().hex.upper()}", "businessId": user.get("businessId"),
        "transactionId": transaction_id,
        "amount": amount, "method": method, "status": "pending",
        "upiString": upi_string, "merchantUpi": merchant_upi,
        "createdAt": datetime.utcnow().isoformat(),
    }
    await db.payments.insert_one(payment_record)
    payment_record.pop("_id", None)
    return {
        "paymentId": payment_record["id"], "upiString": upi_string,
        "amount": amount, "transactionId": transaction_id,
        "qrData": upi_string, "status": "pending", "merchantUpi": merchant_upi,
    }

@router.post("/payments/split")
async def create_split_payment(data: dict, user: dict = Depends(get_user)):
    total = data.get("totalAmount", 0)
    splits = data.get("splits", [])
    transaction_id = data.get("transactionId", f"TXN-{uuid.uuid4().hex.upper()}")
    business_id = user.get("businessId")
    split_records = []
    for i, split in enumerate(splits):
        record = {
            "id": f"SPLIT-{uuid.uuid4().hex.upper()}", "businessId": business_id,
            "transactionId": transaction_id,
            "splitIndex": i + 1, "amount": split.get("amount", 0),
            "method": split.get("method", "card"),
            "payerName": split.get("payerName", f"Guest {i + 1}"),
            "status": "pending", "createdAt": datetime.utcnow().isoformat(),
        }
        split_records.append(record)
    if split_records:
        await db.split_payments.insert_many(split_records)
        for r in split_records:
            r.pop("_id", None)
    return {"transactionId": transaction_id, "totalAmount": total, "splits": split_records, "splitCount": len(split_records)}

@router.post("/payments/{payment_id}/confirm")
async def confirm_payment(payment_id: str, user: dict = Depends(get_user)):
    business_id = user.get("businessId")
    result = await db.payments.find_one_and_update(
        {"id": payment_id, "businessId": business_id},
        {"$set": {"status": "confirmed", "confirmedAt": datetime.utcnow().isoformat()}},
        return_document=True
    )
    if not result:
        result = await db.split_payments.find_one_and_update(
            {"id": payment_id, "businessId": business_id},
            {"$set": {"status": "confirmed", "confirmedAt": datetime.utcnow().isoformat()}},
            return_document=True
        )
    if not result:
        raise HTTPException(status_code=404, detail="Payment not found")
    result.pop("_id", None)
    return result
