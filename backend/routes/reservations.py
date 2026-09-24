from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import StreamingResponse
from typing import List, Optional
from datetime import datetime
from database import db
from services import reservation_store
from deps import get_user, require_owner_or_manager, optional_user
from services import floor_tables
from models.reservation import Reservation, ReservationCreate, ReservationUpdate
from models.floor_plan import FloorPlan, FloorPlanCreate, FloorPlanUpdate
from models.waitlist import WaitlistEntry, WaitlistEntryCreate, WaitlistEntryUpdate
from middleware.actor_context import tenant_scope_filter, tenant_owns_strict
import asyncio
import json
import logging
import os

router = APIRouter()

# ============ GUEST LOOKUP (booking desk + NUA phone agent) ============
# This endpoint (staff booking-dialog lookup) and the phone agent both go
# through services.guest_intel.lookup, but only this HTTP route needs an
# auth dependency — the phone agent (routes/phase_ef.py's simulate_call)
# calls the service function directly, never over HTTP, and passes its own
# business_id. find_customers()/build_guest_intel() previously had zero
# businessId scoping at all — any authenticated staff member of any
# business could search and read booking-desk intel (name, phone, email,
# spend, standing requests) for every other business's customers.
@router.get("/reservations/guest-lookup")
async def guest_lookup(q: Optional[str] = None, phone: Optional[str] = None,
                       email: Optional[str] = None, limit: int = 8,
                       intel: bool = True, user: dict = Depends(get_user)):
    """Resolve a caller/typed guest to CRM records, with the booking-desk
    summary attached (last booking, last visit, what they had, what they
    order most, standing requests).

    Two front doors, one endpoint:
      - staff typing a name/phone/email into the New Reservation dialog
      - the NUA phone agent resolving an inbound caller ID (?phone=...)
    """
    from services.guest_intel import lookup
    if not any([q, phone, email]):
        return {"matches": []}
    matches = await lookup(query=q or "", phone=phone or "", email=email or "",
                           limit=max(1, min(limit, 25)), with_intel=intel,
                           business_id=user.get("businessId"))
    return {"matches": matches}


@router.get("/reservations/guest-intel/{customer_id}")
async def guest_intel(customer_id: str, user: dict = Depends(get_user)):
    """Full booking-desk summary for one known guest."""
    from services.guest_intel import build_guest_intel
    customer = await db.customers.find_one({**tenant_scope_filter(user.get("businessId")), "id": customer_id}, {"_id": 0})
    if not customer or not tenant_owns_strict(customer.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Customer not found")
    return await build_guest_intel(customer, business_id=user.get("businessId"))


# ============ RESERVATIONS API ============
@router.get("/reservations", response_model=List[Reservation])
async def get_reservations(date: Optional[str] = None, status: Optional[str] = None, section: Optional[str] = None,
                           user: dict = Depends(get_user)):
    query = {}
    if date:
        query["date"] = date
    if status:
        query["status"] = status
    if section:
        query["section"] = section
    # Guest name/phone/party-size reservation data had no tenant filter —
    # comparable to v15_features.py's drawer events, which already scopes.
    query.update(tenant_scope_filter(user.get("businessId")))
    reservations = await db.reservations.find(query, {"_id": 0}).sort("time", 1).to_list(1000)
    return [Reservation(**r) for r in reservations]


# NOTE: these two GET routes MUST come before /reservations/{reservation_id}
# — otherwise FastAPI treats "day-counts" / "blackouts" as a reservation id.
@router.get("/reservations/day-counts")
async def day_counts(fromDate: str, toDate: str, user: dict = Depends(get_user)):
    """Return {date: count} for the calendar dots + blackout state per date.
    Range is inclusive; capped at ~120 days to keep the response small."""
    from datetime import date as _date
    d0 = _date.fromisoformat(fromDate); d1 = _date.fromisoformat(toDate)
    if (d1 - d0).days > 120:
        raise HTTPException(status_code=400, detail="Range too wide (max 120 days)")
    scope = tenant_scope_filter(user.get("businessId"))
    reservations = await db.reservations.find(
        {"$and": [scope, {"date": {"$gte": fromDate, "$lte": toDate}}]},
        {"_id": 0, "date": 1, "status": 1, "partySize": 1},
    ).to_list(5000)
    counts: dict = {}
    covers: dict = {}
    for r in reservations:
        d = r.get("date")
        if not d: continue
        counts[d] = counts.get(d, 0) + 1
        covers[d] = covers.get(d, 0) + int(r.get("partySize") or 0)
    blackouts = await db.booking_blackouts.find(
        {"$and": [scope, {"date": {"$gte": fromDate, "$lte": toDate}}]},
        {"_id": 0},
    ).to_list(500)
    black_map = {b["date"]: {"reason": b.get("reason"), "blockUntil": b.get("blockUntil")} for b in blackouts}
    return {"counts": counts, "covers": covers, "blackouts": black_map}


@router.get("/reservations/blackouts")
async def list_blackouts(fromDate: Optional[str] = None, toDate: Optional[str] = None,
                         user: dict = Depends(get_user)):
    q: dict = {}
    if fromDate or toDate:
        q["date"] = {}
        if fromDate: q["date"]["$gte"] = fromDate
        if toDate:   q["date"]["$lte"] = toDate
    docs = await db.booking_blackouts.find(
        {"$and": [tenant_scope_filter(user.get("businessId")), q]}, {"_id": 0}
    ).sort("date", 1).to_list(1000)
    return docs


@router.get("/reservations/cancellation-policy")
async def get_cancellation_policy_route(user: dict = Depends(get_user)):
    from services.cancellation_policy import get_policy
    return await get_policy(user.get("businessId"))


@router.put("/reservations/cancellation-policy")
async def update_cancellation_policy_route(data: dict, user: dict = Depends(require_owner_or_manager)):
    try:
        cutoff = float(data.get("cutoffHours"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="cutoffHours must be a number")
    if cutoff < 0:
        raise HTTPException(status_code=400, detail="cutoffHours must be non-negative")
    business_id = user.get("businessId")
    await db.cancellation_policies.update_one(
        {"businessId": business_id}, {"$set": {"businessId": business_id, "cutoffHours": cutoff}}, upsert=True,
    )
    return {"businessId": business_id, "cutoffHours": cutoff}


@router.get("/reservations/{reservation_id}", response_model=Reservation)
async def get_reservation(reservation_id: str, user: dict = Depends(get_user)):
    res = await db.reservations.find_one({"$and": [{"id": reservation_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0})
    if not res or not tenant_owns_strict(res.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Reservation not found")
    return Reservation(**res)

@router.post("/reservations", response_model=Reservation)
async def create_reservation(reservation: ReservationCreate, user: Optional[dict] = Depends(optional_user)):
    # Booking capacity/size/window rules — the same engine
    # routes/public.py's customer-facing POST /public/book calls, so a rule
    # enforced on one channel can't be silently skipped by going through the
    # other. Blackout-date checking used to live here as its own inline
    # block (and only here — the customer path had none at all); it's now
    # one of several checks the engine runs for both.
    from services.booking_rules_engine import validate_and_enrich_booking, BookingRuleViolation, capacity_lock
    from services.cancellation_policy import snapshot_cutoff_hours
    business_id = (user or {}).get("businessId")
    try:
        async with capacity_lock(business_id, reservation.date):
            enrichment = await validate_and_enrich_booking(
                date=reservation.date, time=reservation.time, party_size=reservation.partySize,
                source=reservation.source, experience_id=reservation.experienceId,
                override_reason=reservation.overrideReason, override_actor=user,
                business_id=business_id,
            )
            cutoff_hours = await snapshot_cutoff_hours(business_id)
            res_obj = Reservation(**{**reservation.dict(), **enrichment, "businessId": business_id,
                                      "cancellationCutoffHours": cutoff_hours})
            doc = res_obj.dict()
            await reservation_store.insert_one(doc)
    except BookingRuleViolation as e:
        raise HTTPException(status_code=409, detail=str(e))
    except TimeoutError as e:
        raise HTTPException(status_code=409, detail=str(e))
    if res_obj.ruleOverrideReason:
        try:
            from services import audit_service
            await audit_service.log_event(
                entity_type="reservation", entity_id=res_obj.id, action="created",
                after=doc, memo=f"Booking rule override: {res_obj.ruleOverrideReason}", severity="warning",
                tags=["booking_rule_override"],
            )
        except Exception as e:
            from utils.errors import log_and_continue
            log_and_continue(logging.getLogger(__name__), f"Audit log failed for override on reservation {res_obj.id} (booking itself succeeded)", e)
    elif res_obj.isLargeBooking:
        try:
            from services import audit_service
            await audit_service.log_event(
                entity_type="reservation", entity_id=res_obj.id, action="created",
                after=doc, memo=f"Large booking ({res_obj.partySize} guests) — tier: {res_obj.bookingTierLabel}",
                severity="notice", tags=["large_booking"],
            )
        except Exception as e:
            from utils.errors import log_and_continue
            log_and_continue(logging.getLogger(__name__), f"Audit log failed for large booking {res_obj.id} (booking itself succeeded)", e)
    if reservation.tableId:
        found = await floor_tables.get_table_by_id(reservation.tableId)
        if found:
            _, plan_id = found
            await floor_tables.set_table_status(reservation.tableId, plan_id, "reserved", reservation_id=res_obj.id)
    if reservation.customerId:
        await db.customers.update_one(
            {**tenant_scope_filter(business_id), "id": reservation.customerId},
            {"$inc": {"visits": 0}, "$push": {"reservationIds": res_obj.id}}
        )
    # Rules engine emit
    try:
        from services.rules_engine import safe_emit
        rd = res_obj.dict()
        safe_emit("booking.created", {
            "id": rd.get("id"), "partySize": rd.get("partySize"),
            "time": (rd.get("dateTime") or rd.get("time") or ""),
            "customerId": rd.get("customerId"),
        })
    except Exception:
        pass
    # Free base identity layer: recognize this guest across modules.
    try:
        from services.customer_identity import record_touchpoint
        await record_touchpoint(
            phone=reservation.guestPhone, email=reservation.guestEmail,
            name=reservation.guestName, source="booking",
        )
    except Exception:
        pass
    return res_obj

@router.put("/reservations/{reservation_id}", response_model=Reservation)
async def update_reservation(reservation_id: str, update: ReservationUpdate, user: dict = Depends(get_user)):
    existing = await db.reservations.find_one({"$and": [{"id": reservation_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0})
    if not existing or not tenant_owns_strict(existing.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Reservation not found")
    update_data = {k: v for k, v in update.dict().items() if v is not None}
    update_data["updatedAt"] = datetime.utcnow().isoformat()
    # Newly linking (or re-linking) a CRM guest during an edit — same bookkeeping
    # create_reservation does, so this reservation shows up on the guest's profile.
    new_customer_id = update_data.get("customerId")
    if new_customer_id and new_customer_id != existing.get("customerId"):
        await db.customers.update_one(
            {**tenant_scope_filter(user.get("businessId")), "id": new_customer_id}, {"$push": {"reservationIds": reservation_id}}
        )

    # Re-run the same booking-rules engine creation goes through whenever an
    # edit touches a field the rules actually depend on — previously this
    # was a bare $set with no re-validation at all, so moving a confirmed
    # booking onto a blacked-out date, past the booking window, or to a
    # party size that overflows the slot's capacity (or crosses into a
    # different size tier, silently keeping the OLD tier's deposit/pre-
    # order/approval flags) all went straight through unchecked.
    rule_dependent_fields = ("date", "time", "partySize", "experienceId")
    reactivating = update_data.get("status") in ("confirmed", "seated") and existing.get("status") not in ("confirmed", "seated")
    if reactivating:
        raise HTTPException(409, "Use the restore action to recheck capacity and reconcile cancellation effects")
    if any(f in update_data for f in rule_dependent_fields):
        from services.booking_rules_engine import (
            validate_and_enrich_booking, BookingRuleViolation, capacity_lock)
        business_id = existing.get("businessId")
        new_date = update_data.get("date", existing.get("date"))
        new_time = update_data.get("time", existing.get("time"))
        new_party_size = update_data.get("partySize", existing.get("partySize"))
        new_experience_id = update_data.get("experienceId", existing.get("experienceId"))
        try:
            async with capacity_lock(business_id, new_date):
                enrichment = await validate_and_enrich_booking(
                    date=new_date, time=new_time, party_size=new_party_size,
                    source=existing.get("source") or "phone",
                    experience_id=new_experience_id,
                    reservation_id_to_exclude=reservation_id,
                    override_reason=update.overrideReason, override_actor=user,
                    business_id=business_id,
                )
                update_data.update(enrichment)
                result = await reservation_store.find_one_and_update(
                    {"$and": [{"id": reservation_id}, tenant_scope_filter(user.get("businessId"))]}, {"$set": update_data}, return_document=True
                )
        except BookingRuleViolation as e:
            raise HTTPException(status_code=409, detail=str(e))
        except TimeoutError as e:
            raise HTTPException(status_code=409, detail=str(e))
    else:
        result = await reservation_store.find_one_and_update(
            {"$and": [{"id": reservation_id}, tenant_scope_filter(user.get("businessId"))]}, {"$set": update_data}, return_document=True
        )
    if not result:
        raise HTTPException(status_code=404, detail="Reservation not found")
    result.pop("_id", None)
    return Reservation(**result)

@router.delete("/reservations/{reservation_id}")
async def delete_reservation(reservation_id: str, user: dict = Depends(require_owner_or_manager)):
    res = await db.reservations.find_one({"$and": [{"id": reservation_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0})
    if not res or not tenant_owns_strict(res.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Reservation not found")
    if res.get("tableId"):
        found = await floor_tables.get_table_by_id(res["tableId"])
        if found:
            _, plan_id = found
            await floor_tables.set_table_status(res["tableId"], plan_id, "available")
    await reservation_store.delete_one({"$and": [{"id": reservation_id}, tenant_scope_filter(user.get("businessId"))]})
    return {"message": "Reservation deleted"}

@router.post("/reservations/{reservation_id}/seat")
async def seat_reservation(reservation_id: str, table_id: Optional[str] = None, user: dict = Depends(get_user)):
    res = await db.reservations.find_one({"$and": [{"id": reservation_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0})
    if not res or not tenant_owns_strict(res.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Reservation not found")
    if res.get("status") in ("cancelled", "no_show", "completed"):
        raise HTTPException(status_code=400, detail=f"Booking is already {res.get('status')}")
    # Large-booking approval/pre-order gates (services.booking_rules_engine
    # sets these at creation time) were previously purely informational —
    # nothing stopped a booking pending manager sign-off, or one whose
    # matched tier requires a completed pre-order, from being seated
    # exactly like any ordinary confirmed booking, defeating the entire
    # point of gating a large party behind that review.
    if res.get("approvalRequired") and res.get("approvalStatus") in ("pending", "rejected"):
        raise HTTPException(
            status_code=409,
            detail=f"This booking's approval is still {res.get('approvalStatus')} — approve it before seating")
    if res.get("preOrderRequired") and not res.get("preOrderCompleted"):
        raise HTTPException(
            status_code=409, detail="This booking requires a completed pre-order before seating")
    tid = table_id or res.get("tableId")
    update_data = {"status": "seated", "seatedAt": datetime.utcnow().isoformat(), "updatedAt": datetime.utcnow().isoformat()}
    if tid:
        update_data["tableId"] = tid
        found = await floor_tables.get_table_by_id(tid)
        if found:
            _, plan_id = found
            await floor_tables.set_table_status(tid, plan_id, "occupied", reservation_id=reservation_id)
    await reservation_store.update_one({"$and": [{"id": reservation_id}, tenant_scope_filter(user.get("businessId"))]}, {"$set": update_data})
    return {"message": "Guest seated", "tableId": tid}

@router.post("/reservations/{reservation_id}/complete")
async def complete_reservation(reservation_id: str, user: dict = Depends(get_user)):
    res = await db.reservations.find_one({"$and": [{"id": reservation_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0})
    if not res or not tenant_owns_strict(res.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Reservation not found")
    await reservation_store.update_one(
        {"$and": [{"id": reservation_id}, tenant_scope_filter(user.get("businessId"))]},
        {"$set": {"status": "completed", "completedAt": datetime.utcnow().isoformat(), "updatedAt": datetime.utcnow().isoformat()}}
    )
    if res.get("tableId"):
        found = await floor_tables.get_table_by_id(res["tableId"])
        if found:
            _, plan_id = found
            await floor_tables.set_table_status(res["tableId"], plan_id, "cleaning", clear_reservation=True)
    return {"message": "Reservation completed"}


# ============ DEPOSITS — real Stripe Checkout collection ============
# Same pattern as routes/online_orders.py's create_online_order_checkout:
# its own Stripe Checkout session, tagged kind="booking_deposit" on the
# payment_transactions doc so the shared webhook/poll handlers in
# routes/integrations.py know to flip THIS reservation's depositPaid, not
# just the generic payment ledger. Before this, depositPaid was a bare
# staff-ticked checkbox (ReservationUpdate.depositPaid) with no real money
# behind it — mark_no_show's fee was pure record-keeping. This is what
# makes the deposit (and therefore a no-show fee capture — see
# mark_no_show below) real.
@router.post("/reservations/{reservation_id}/request-deposit")
async def request_deposit(reservation_id: str, data: dict, http_request: Request, user: dict = Depends(get_user)):
    res = await db.reservations.find_one({"$and": [{"id": reservation_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0})
    if not res or not tenant_owns_strict(res.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Reservation not found")
    amount = float(res.get("depositRequired") or 0)
    if amount <= 0:
        raise HTTPException(status_code=400, detail="This booking has no deposit amount set")
    if res.get("depositPaid"):
        raise HTTPException(status_code=400, detail="Deposit already paid")

    api_key = os.environ.get("STRIPE_API_KEY")
    if not api_key:
        # Not a hard failure — same graceful degradation as online-order
        # checkout: staff falls back to collecting the deposit by whatever
        # means they used before this endpoint existed (card reader, cash).
        return {"configured": False, "url": None}

    # A double-click must not create two live Stripe sessions for the same
    # deposit — reservation_id is already a stable resource identity, same
    # pattern as the other checkout endpoints' order_id-keyed claim (see
    # services/payment_idempotency.py).
    from services.payment_idempotency import claim_or_wait, record_result
    prior_result = await claim_or_wait("stripe_deposit", reservation_id)
    if prior_result is not None:
        return {"configured": True, **prior_result}

    from emergentintegrations.payments.stripe.checkout import StripeCheckout, CheckoutSessionRequest
    import uuid

    origin_url = data.get("originUrl", str(http_request.base_url).rstrip("/"))
    host_url = str(http_request.base_url).rstrip("/")
    webhook_url = f"{host_url}/api/webhook/stripe"
    stripe_checkout = StripeCheckout(api_key=api_key, webhook_url=webhook_url)

    success_url = f"{origin_url}/reservations?depositPaid={reservation_id}&session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{origin_url}/reservations"

    checkout_request = CheckoutSessionRequest(
        amount=amount, currency="aud",
        success_url=success_url, cancel_url=cancel_url,
        metadata={"reservationId": reservation_id, "source": "nua_pos", "kind": "booking_deposit"},
    )
    session = await stripe_checkout.create_checkout_session(checkout_request)

    payment_doc = {
        "id": f"SPAY-{uuid.uuid4().hex[:8].upper()}",
        "sessionId": session.session_id,
        "reservationId": reservation_id,
        "amount": amount, "currency": "aud",
        "status": "initiated", "paymentStatus": "pending",
        "provider": "stripe", "kind": "booking_deposit",
        "businessId": res.get("businessId"),
        "createdAt": datetime.utcnow().isoformat(),
    }
    await db.payment_transactions.insert_one(payment_doc)
    await reservation_store.update_one(
        {"$and": [{"id": reservation_id}, tenant_scope_filter(user.get("businessId"))]}, {"$set": {"depositSessionId": session.session_id}}
    )
    result = {"url": session.url, "sessionId": session.session_id}
    await record_result("stripe_deposit", reservation_id, result)
    return {"configured": True, **result}


@router.post("/reservations/{reservation_id}/no-show")
async def mark_no_show(reservation_id: str, fee: float = 0, user: dict = Depends(get_user)):
    """Real payment capture, not just record-keeping: if a deposit was
    actually collected through a genuine Stripe Checkout session (see
    request_deposit below) rather than staff hand-ticking "deposit paid",
    it's forfeited here — kept by the business instead of ever being
    refunded — which IS the no-show fee actually landing.

    Without a real collected deposit there is nothing to capture. NUA has
    no saved-card/off-session-charge capability (only Stripe's hosted
    Checkout, a one-time redirect flow — see routes/integrations.py), so a
    walk-in/phone/online booking that never had a deposit collected can't
    have a no-show fee actually charged after the fact; `fee` stays
    record-keeping only for that case, same as it always was. The response
    says plainly which happened — never silently reports a fee as
    collected when nothing was actually captured.
    """
    res = await db.reservations.find_one({"$and": [{"id": reservation_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0})
    if not res or not tenant_owns_strict(res.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Reservation not found")

    update_data = {"status": "no_show", "noShowFee": fee, "updatedAt": datetime.utcnow().isoformat()}
    captured = bool(res.get("depositPaid") and res.get("depositSessionId") and not res.get("depositForfeited"))
    forfeited_amount = 0.0
    if captured:
        update_data["depositForfeited"] = True
        forfeited_amount = float(res.get("depositRequired") or 0)

    await reservation_store.update_one({"$and": [{"id": reservation_id}, tenant_scope_filter(user.get("businessId"))]}, {"$set": update_data})
    if res.get("customerId"):
        await db.customers.update_one({**tenant_scope_filter(user.get("businessId")), "id": res["customerId"]}, {"$inc": {"noShowCount": 1}})
    if res.get("tableId"):
        found = await floor_tables.get_table_by_id(res["tableId"])
        if found:
            _, plan_id = found
            await floor_tables.set_table_status(res["tableId"], plan_id, "available")

    try:
        from services import audit_service
        await audit_service.log_event(
            entity_type="reservation", entity_id=reservation_id, action="updated",
            before=res, after={**res, **update_data},
            memo=(f"Marked no-show by {user.get('email', 'staff')}" + (
                f" — ${forfeited_amount:.2f} deposit forfeited as the no-show fee" if captured
                else (f" — ${fee:.2f} fee recorded (no deposit was collected to capture)" if fee else "")
            )),
            severity="notice",
        )
    except Exception as e:
        from utils.errors import log_and_continue
        log_and_continue(logging.getLogger(__name__), f"Audit log failed for no-show on reservation {reservation_id} (status change itself succeeded)", e)
    return {
        "message": "Marked as no-show",
        "depositForfeited": captured,
        "forfeitedAmount": forfeited_amount,
    }


@router.post("/reservations/{reservation_id}/cancel", response_model=Reservation)
async def cancel_reservation(reservation_id: str, body: dict = None, user: dict = Depends(require_owner_or_manager)):
    """Cancel a booking without destroying it — status only, so it can be
    restored later. This is the correct way to cancel; the hard DELETE
    endpoint is for genuinely removing a record, not everyday cancellation.
    """
    res = await db.reservations.find_one({"$and": [{"id": reservation_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0})
    if not res or not tenant_owns_strict(res.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Reservation not found")
    if res.get("status") in ("cancelled", "no_show", "completed"):
        raise HTTPException(status_code=400, detail=f"Booking is already {res.get('status')}")

    reason = (body or {}).get("reason")
    update_data = {"status": "cancelled", "cancellationReason": reason, "updatedAt": datetime.utcnow().isoformat()}
    # Cancellation-policy engine: a collected deposit is only refunded in
    # full when this cancellation lands outside the business's configured
    # cutoff window (default 24h before the booking) — inside it, the
    # deposit is forfeited as a cancellation fee instead, the same
    # forfeit-what-was-actually-collected mechanism mark_no_show uses.
    # Best-effort on the Stripe side: a failed refund never blocks the
    # cancellation itself, but is recorded so it doesn't silently vanish.
    cancellation_fee_applied = False
    if res.get("depositPaid") and res.get("depositSessionId") and not res.get("depositForfeited"):
        from services.cancellation_policy import is_within_free_cancellation_window
        if await is_within_free_cancellation_window(res, user.get("businessId")):
            from routes.integrations import refund_stripe_payment
            refunded = await refund_stripe_payment(res["depositSessionId"])
            update_data["depositPaid"] = not refunded
            update_data["depositRefunded"] = refunded
        else:
            update_data["depositForfeited"] = True
            cancellation_fee_applied = True
    await reservation_store.update_one({"$and": [{"id": reservation_id}, tenant_scope_filter(user.get("businessId"))]}, {"$set": update_data})

    if res.get("tableId"):
        found = await floor_tables.get_table_by_id(res["tableId"])
        if found:
            _, plan_id = found
            await floor_tables.set_table_status(res["tableId"], plan_id, "available")

    updated = {**res, **update_data}
    fee_memo = (f" — outside the cancellation window, ${res.get('depositRequired', 0):.2f} deposit forfeited as a cancellation fee"
                if cancellation_fee_applied else "")
    try:
        from services import audit_service
        await audit_service.log_event(
            entity_type="reservation", entity_id=reservation_id, action="updated",
            before=res, after=updated,
            memo=f"Booking cancelled by {user.get('email', 'staff')}" + (f": {reason}" if reason else "") + fee_memo,
            severity="notice",
        )
    except Exception as e:
        from utils.errors import log_and_continue
        log_and_continue(logging.getLogger(__name__), f"Audit log failed for cancel on reservation {reservation_id} (cancellation itself succeeded)", e)
    return Reservation(**updated)


@router.post("/reservations/{reservation_id}/approve", response_model=Reservation)
async def approve_large_booking(reservation_id: str, user: dict = Depends(require_owner_or_manager)):
    """Owner/manager sign-off on a large booking whose matched size tier has
    requireApproval set (services.booking_rules_engine sets approvalStatus
    to 'pending' at creation time for those)."""
    res = await db.reservations.find_one({"$and": [{"id": reservation_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0})
    if not res or not tenant_owns_strict(res.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Reservation not found")
    if not res.get("approvalRequired"):
        raise HTTPException(status_code=400, detail="This booking doesn't require approval")
    if res.get("approvalStatus") != "pending":
        raise HTTPException(status_code=400, detail=f"Approval already {res.get('approvalStatus')}")

    update_data = {
        "approvalStatus": "approved", "approvedBy": user.get("email") or user.get("id"),
        "approvedAt": datetime.utcnow().isoformat(), "updatedAt": datetime.utcnow().isoformat(),
    }
    await reservation_store.update_one({"$and": [{"id": reservation_id}, tenant_scope_filter(user.get("businessId"))]}, {"$set": update_data})
    updated = {**res, **update_data}
    try:
        from services import audit_service
        await audit_service.log_event(
            entity_type="reservation", entity_id=reservation_id, action="updated",
            before=res, after=updated, memo=f"Large booking approved by {user.get('email', 'staff')}",
            severity="notice", tags=["large_booking"],
        )
    except Exception as e:
        from utils.errors import log_and_continue
        log_and_continue(logging.getLogger(__name__), f"Audit log failed for approve on reservation {reservation_id} (approval itself succeeded)", e)
    return Reservation(**updated)


@router.post("/reservations/{reservation_id}/reject", response_model=Reservation)
async def reject_large_booking(reservation_id: str, body: dict = None, user: dict = Depends(require_owner_or_manager)):
    """Reject a pending large booking. Also cancels it — a rejected large
    booking shouldn't sit on the floor plan reading as a normal confirmed
    reservation; the guest needs to be told and re-booked under a tier that
    actually fits, not silently kept as-is."""
    res = await db.reservations.find_one({"$and": [{"id": reservation_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0})
    if not res or not tenant_owns_strict(res.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Reservation not found")
    if not res.get("approvalRequired"):
        raise HTTPException(status_code=400, detail="This booking doesn't require approval")
    if res.get("approvalStatus") != "pending":
        raise HTTPException(status_code=400, detail=f"Approval already {res.get('approvalStatus')}")

    reason = (body or {}).get("reason")
    update_data = {
        "approvalStatus": "rejected", "approvedBy": user.get("email") or user.get("id"),
        "approvedAt": datetime.utcnow().isoformat(),
        "status": "cancelled", "cancellationReason": reason or "Large booking not approved",
        "updatedAt": datetime.utcnow().isoformat(),
    }
    await reservation_store.update_one({"$and": [{"id": reservation_id}, tenant_scope_filter(user.get("businessId"))]}, {"$set": update_data})
    if res.get("tableId"):
        found = await floor_tables.get_table_by_id(res["tableId"])
        if found:
            _, plan_id = found
            await floor_tables.set_table_status(res["tableId"], plan_id, "available")
    updated = {**res, **update_data}
    try:
        from services import audit_service
        await audit_service.log_event(
            entity_type="reservation", entity_id=reservation_id, action="updated",
            before=res, after=updated,
            memo=f"Large booking rejected by {user.get('email', 'staff')}" + (f": {reason}" if reason else ""),
            severity="warning", tags=["large_booking"],
        )
    except Exception as e:
        from utils.errors import log_and_continue
        log_and_continue(logging.getLogger(__name__), f"Audit log failed for reject on reservation {reservation_id} (rejection itself succeeded)", e)
    return Reservation(**updated)


@router.post("/reservations/{reservation_id}/restore", response_model=Reservation)
async def restore_reservation(reservation_id: str, body: dict = None, user: dict = Depends(require_owner_or_manager)):
    """Bring a Cancelled or No-show booking back to Confirmed.

    Deliberately doesn't re-occupy a table — the table was already freed
    when the booking was cancelled/no-showed and may since have gone to
    someone else, so restoring status alone (not a table sight-unseen) is
    the safe default. Staff can re-run auto-assign/AI-assign afterward if
    the guest still needs seating.
    """
    res = await db.reservations.find_one({"$and": [{"id": reservation_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0})
    if not res or not tenant_owns_strict(res.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Reservation not found")
    prior_status = res.get("status")
    if prior_status not in ("cancelled", "no_show"):
        raise HTTPException(status_code=400, detail=f"Only a cancelled or no-show booking can be restored (this one is {prior_status})")

    restored_status = (body or {}).get("status") or "confirmed"
    if restored_status not in ("confirmed", "seated"):
        raise HTTPException(status_code=400, detail="Can only restore to confirmed or seated")

    update_data = {"status": restored_status, "cancellationReason": None, "updatedAt": datetime.utcnow().isoformat()}
    from services.booking_rules_engine import capacity_lock, validate_and_enrich_booking, BookingRuleViolation
    try:
        async with capacity_lock(res.get("businessId"), res["date"]):
            await validate_and_enrich_booking(
                date=res["date"], time=res["time"], party_size=res["partySize"],
                source="staff_restore", experience_id=res.get("experienceId"),
                reservation_id_to_exclude=reservation_id, business_id=res.get("businessId"))
            result = await reservation_store.update_one(
                {"$and": [{"id": reservation_id, "status": prior_status,
                            "date": res["date"], "time": res["time"], "partySize": res["partySize"]},
                           tenant_scope_filter(user.get("businessId"))]}, {"$set": update_data})
            if result.matched_count != 1:
                raise HTTPException(409, "Booking changed while restoring; refresh and retry")
    except (BookingRuleViolation, TimeoutError) as exc:
        raise HTTPException(409, str(exc)) from exc

    # A no-show that forfeited a real deposit gets that money genuinely
    # refunded on restore — "this was a mistake" must undo the actual
    # capture, not just the status label. Best-effort, same as cancel's.
    if prior_status == "no_show" and res.get("depositForfeited") and res.get("depositSessionId"):
        from routes.integrations import refund_stripe_payment
        refunded = await refund_stripe_payment(res["depositSessionId"])
        if refunded:
            update_data["depositForfeited"] = False
            update_data["depositRefunded"] = True
    if update_data.get("depositRefunded"):
        await reservation_store.update_one(
            {"$and": [{"id": reservation_id}, tenant_scope_filter(user.get("businessId"))]},
            {"$set": {"depositForfeited": False, "depositRefunded": True}})

    # Reverse the no-show penalty this booking caused, if any.
    if prior_status == "no_show" and res.get("customerId"):
        await db.customers.update_one({**tenant_scope_filter(user.get("businessId")), "id": res["customerId"]}, {"$inc": {"noShowCount": -1}})

    updated = {**res, **update_data}
    try:
        from services import audit_service
        await audit_service.log_event(
            entity_type="reservation", entity_id=reservation_id, action="restored",
            before=res, after=updated,
            memo=f"Booking restored from {prior_status} to {restored_status} by {user.get('email', 'staff')}",
            severity="notice",
        )
    except Exception as e:
        from utils.errors import log_and_continue
        log_and_continue(logging.getLogger(__name__), f"Audit log failed for restore on reservation {reservation_id} (restore itself succeeded)", e)
    return Reservation(**updated)

@router.get("/reservations/auto-assign/{reservation_id}")
async def auto_assign_table(reservation_id: str, user: dict = Depends(get_user)):
    res = await db.reservations.find_one({"$and": [{"id": reservation_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0})
    if not res or not tenant_owns_strict(res.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Reservation not found")
    party = res.get("partySize", 2)
    section_pref = res.get("section")
    all_tables = await floor_tables.list_tables()
    candidates = [
        t for t in all_tables
        if t.get("status") == "available"
        and int(t.get("maxCovers") or t.get("capacity") or 0) >= party
        and (not section_pref or t.get("section") == section_pref)
    ]
    if not candidates:
        if not all_tables:
            return {"assigned": False, "message": "No tables are configured yet"}
        return {"assigned": False, "message": "No suitable tables available"}
    candidates.sort(key=lambda t: int(t.get("maxCovers") or t.get("capacity") or 0))
    best = candidates[0]
    await reservation_store.update_one(
        {"$and": [{"id": reservation_id}, tenant_scope_filter(user.get("businessId"))]},
        {"$set": {"tableId": best["id"], "tableNumber": best.get("number", ""), "updatedAt": datetime.utcnow().isoformat()}}
    )
    await floor_tables.set_table_status(best["id"], best.get("planId"), "reserved", reservation_id=reservation_id)
    return {"assigned": True, "table": best}


# ============ BOOKING BLACKOUTS ============
# Stops new incoming reservations for a date (or a range of dates) — e.g. a
# private event, staff training day, storm closure, or a fully-booked day the
# owner wants to lock down. Existing reservations are untouched.
#
# Collection: booking_blackouts  { id, date (YYYY-MM-DD), reason, blockUntil? }
# `blockUntil` is optional — when set, the blackout auto-expires (used for
# "pause bookings for the rest of today" style toggles).
# GET endpoints for /blackouts and /day-counts are defined above the
# /reservations/{id} route to avoid FastAPI catch-all path conflict.


@router.post("/reservations/blackouts")
async def create_blackout(data: dict, user: dict = Depends(require_owner_or_manager)):
    """Create a blackout for a single date OR a `fromDate`→`toDate` inclusive range.

    The upsert key includes businessId, not just date — it didn't before,
    so two businesses blacking out the same calendar date would collide
    into one shared document, with whichever business wrote second
    silently overwriting the first business's reason/blockUntil.
    """
    import uuid
    business_id = user.get("businessId")
    reason = str(data.get("reason") or "Bookings paused").strip()
    now_iso = datetime.utcnow().isoformat()
    from datetime import date as _date, timedelta as _td
    def _parse(s):
        return _date.fromisoformat(s)
    if data.get("fromDate") and data.get("toDate"):
        d0 = _parse(data["fromDate"]); d1 = _parse(data["toDate"])
        if d1 < d0:
            raise HTTPException(status_code=400, detail="toDate must be on/after fromDate")
        created = []
        cur = d0
        while cur <= d1:
            doc = {"id": str(uuid.uuid4()), "date": cur.isoformat(), "reason": reason,
                   "blockUntil": data.get("blockUntil"), "businessId": business_id, "createdAt": now_iso}
            await db.booking_blackouts.update_one(
                {"date": cur.isoformat(), "businessId": business_id},
                {"$set": {k: v for k, v in doc.items() if k != "id"},
                 "$setOnInsert": {"id": doc["id"]}},
                upsert=True,
            )
            created.append(cur.isoformat())
            cur += _td(days=1)
        return {"created": created, "count": len(created), "reason": reason}
    single = str(data.get("date") or "").strip()
    if not single:
        raise HTTPException(status_code=400, detail="Provide 'date' or 'fromDate'+'toDate'")
    doc = {"id": str(uuid.uuid4()), "date": single, "reason": reason,
           "blockUntil": data.get("blockUntil"), "businessId": business_id, "createdAt": now_iso}
    await db.booking_blackouts.update_one(
        {"date": single, "businessId": business_id},
        {"$set": {k: v for k, v in doc.items() if k != "id"},
         "$setOnInsert": {"id": doc["id"]}},
        upsert=True,
    )
    return {"created": [single], "count": 1, "reason": reason}


@router.delete("/reservations/blackouts/{date}")
async def delete_blackout(date: str, user: dict = Depends(require_owner_or_manager)):
    scope = tenant_scope_filter(user.get("businessId"))
    r = await db.booking_blackouts.delete_many({"$and": [scope, {"date": date}]})
    return {"deleted": r.deleted_count, "date": date}


# ============ FLOOR PLANS API ============
# This whole section had no Depends at all (not even get_user) on the CRUD
# endpoints, and no businessId scoping either — a floor plan is a real
# operational asset (table layout, sections, server assignments), and
# create/update/delete were reachable by anyone holding any valid staff
# token (this router isn't behind server.py's public-prefix allowlist, so
# a token is required to get past the global auth middleware — but nothing
# beyond that: no role check, no ownership check). Fixed with get_user for
# reads and require_owner_or_manager for writes, plus businessId
# stamping/scoping throughout.
@router.get("/floor-plans", response_model=List[FloorPlan])
async def get_floor_plans(user: dict = Depends(get_user)):
    plans = await db.floor_plans.find(tenant_scope_filter(user.get("businessId")), {"_id": 0}).to_list(100)
    return [FloorPlan(**p) for p in plans]

@router.get("/floor-plans/{plan_id}", response_model=FloorPlan)
async def get_floor_plan(plan_id: str, user: dict = Depends(get_user)):
    plan = await db.floor_plans.find_one({"$and": [{"id": plan_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0})
    if not plan or not tenant_owns_strict(plan.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Floor plan not found")
    return FloorPlan(**plan)

@router.post("/floor-plans", response_model=FloorPlan)
async def create_floor_plan(plan: FloorPlanCreate, user: dict = Depends(require_owner_or_manager)):
    plan_obj = FloorPlan(**plan.dict())
    doc = {**plan_obj.dict(), "businessId": user.get("businessId")}
    await db.floor_plans.insert_one(doc)
    return plan_obj

@router.put("/floor-plans/{plan_id}", response_model=FloorPlan)
async def update_floor_plan(plan_id: str, update: FloorPlanUpdate, user: dict = Depends(require_owner_or_manager)):
    existing = await db.floor_plans.find_one({"$and": [{"id": plan_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0, "businessId": 1})
    if not existing or not tenant_owns_strict(existing.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Floor plan not found")
    update_data = {k: v for k, v in update.dict().items() if v is not None}
    update_data["updatedAt"] = datetime.utcnow().isoformat()
    result = await db.floor_plans.find_one_and_update(
        {"$and": [{"id": plan_id}, tenant_scope_filter(user.get("businessId"))]}, {"$set": update_data}, return_document=True
    )
    if not result:
        raise HTTPException(status_code=404, detail="Floor plan not found")
    result.pop("_id", None)
    try:
        from services import realtime
        await realtime.broadcast({"type": "floor_plan.updated", "planId": plan_id})
    except Exception:
        pass
    return FloorPlan(**result)

@router.delete("/floor-plans/{plan_id}")
async def delete_floor_plan(plan_id: str, user: dict = Depends(require_owner_or_manager)):
    existing = await db.floor_plans.find_one({"$and": [{"id": plan_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0, "businessId": 1})
    if not existing or not tenant_owns_strict(existing.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Floor plan not found")
    result = await db.floor_plans.delete_one({"$and": [{"id": plan_id}, tenant_scope_filter(user.get("businessId"))]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Floor plan not found")
    return {"message": "Floor plan deleted"}

@router.post("/floor-plans/tables/{table_id}/status")
async def update_table_status(table_id: str, status: str, plan_id: Optional[str] = None,
                                user: dict = Depends(get_user)):
    if plan_id:
        plan = await db.floor_plans.find_one({"$and": [{"id": plan_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0})
        if plan and tenant_owns_strict(plan.get("businessId"), user.get("businessId")):
            tables = plan.get("tables", [])
            for t in tables:
                if t.get("id") == table_id:
                    t["status"] = status
                    break
            await db.floor_plans.update_one(
                {"$and": [{"id": plan_id}, tenant_scope_filter(user.get("businessId"))]}, {"$set": {"tables": tables, "updatedAt": datetime.utcnow().isoformat()}}
            )
    try:
        from services import realtime
        await realtime.broadcast({"type": "floor_plan.updated", "planId": plan_id, "tableId": table_id, "status": status})
    except Exception:
        pass
    return {"message": f"Table {table_id} status updated to {status}"}

# ── Typed-table validation (POS dine-in) ──────────────────────────────────
# The POS accepts a hand-typed table number. These endpoints are what stop a
# typo becoming an order on a table that doesn't exist.
@router.get("/floor-plans/tables/resolve")
async def resolve_typed_table(number: str, _: dict = Depends(get_user)):
    """Resolve a typed table number against the configured floor plans.

    Returns `configured: False` when the venue has drawn no floor plan at all —
    the caller should then accept free text rather than block the sale.
    """
    configured = await floor_tables.has_floor_plan()
    if not configured:
        return {"configured": False, "found": False, "table": None,
                "suggestions": [], "message": "No floor plan configured"}

    hit = await floor_tables.resolve_table(number)
    if not hit:
        return {
            "configured": True, "found": False, "table": None,
            "suggestions": await floor_tables.suggest(number),
            "message": f"Table '{number}' is not on the floor plan",
        }
    table, plan_id = hit
    return {"configured": True, "found": True, "planId": plan_id,
            "table": table, "suggestions": [], "message": "ok"}


@router.get("/floor-plans/tables/all")
async def list_floor_tables(_: dict = Depends(get_user)):
    """Flat list of every configured table, for POS pickers and validation."""
    tables = await floor_tables.list_tables()
    return {"configured": len(tables) > 0, "tables": tables}


@router.post("/floor-plans/tables/by-number/{number}/occupy")
async def occupy_table_by_number(number: str, order_id: Optional[str] = None,
                                 _: dict = Depends(get_user)):
    """Mark the table a POS order was just assigned to as occupied.

    404s on an unknown table so the POS can surface the error instead of
    silently losing the association.
    """
    hit = await floor_tables.resolve_table(number)
    if not hit:
        raise HTTPException(status_code=404,
                            detail=f"Table '{number}' is not on the floor plan")
    table, plan_id = hit
    await floor_tables.set_table_status(table["id"], plan_id, "occupied", order_id)
    try:
        from services import realtime
        await realtime.broadcast({"type": "floor_plan.updated", "planId": plan_id, "tableId": table["id"], "status": "occupied"})
    except Exception:
        pass
    return {"ok": True, "tableId": table["id"], "planId": plan_id,
            "number": table.get("number"), "status": "occupied"}


@router.post("/floor-plans/tables/by-number/{number}/free")
async def free_table_by_number(number: str, _: dict = Depends(get_user)):
    hit = await floor_tables.resolve_table(number)
    if not hit:
        raise HTTPException(status_code=404,
                            detail=f"Table '{number}' is not on the floor plan")
    table, plan_id = hit
    await floor_tables.set_table_status(table["id"], plan_id, "available")
    try:
        from services import realtime
        await realtime.broadcast({"type": "floor_plan.updated", "planId": plan_id, "tableId": table["id"], "status": "available"})
    except Exception:
        pass
    return {"ok": True, "tableId": table["id"], "planId": plan_id,
            "number": table.get("number"), "status": "available"}


@router.post("/floor-plans/sections/{section_id}/assign")
async def assign_server_to_section(section_id: str, server_id: str, plan_id: str,
                                     user: dict = Depends(require_owner_or_manager)):
    plan = await db.floor_plans.find_one({"$and": [{"id": plan_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0})
    if not plan or not tenant_owns_strict(plan.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Floor plan not found")
    sections = plan.get("sections", [])
    for s in sections:
        if s.get("id") == section_id:
            s["serverId"] = server_id
            break
    await db.floor_plans.update_one(
        {"$and": [{"id": plan_id}, tenant_scope_filter(user.get("businessId"))]}, {"$set": {"sections": sections, "updatedAt": datetime.utcnow().isoformat()}}
    )
    return {"message": "Server assigned to section"}

# ============ WAITLIST API ============
# Tenant isolation + Silver+ "Priority waitlist" perk (found + fixed together
# while building the tier-perk enforcement half of Loyalty 3.0 — the whole
# staff-facing waitlist had zero businessId scoping or auth at all before
# this). See TENANT_ISOLATION_REMAINING_WORK.md for the full writeup.
@router.get("/waitlist", response_model=List[WaitlistEntry])
async def get_waitlist(status: Optional[str] = None, user: dict = Depends(get_user)):
    scope = tenant_scope_filter(user.get("businessId"))
    status_filter = {"status": status} if status else {"status": {"$in": ["waiting", "notified"]}}
    query = {"$and": [scope, status_filter]}
    entries = await db.waitlist.find(query, {"_id": 0}).sort([("priority", -1), ("position", 1)]).to_list(1000)
    return [WaitlistEntry(**e) for e in entries]

@router.post("/waitlist", response_model=WaitlistEntry)
async def add_to_waitlist(entry: WaitlistEntryCreate, user: dict = Depends(get_user)):
    business_id = user.get("businessId")
    scope = tenant_scope_filter(business_id)
    last = await db.waitlist.find({"$and": [scope, {"status": "waiting"}]}).sort("position", -1).to_list(1)
    next_pos = (last[0]["position"] + 1) if last else 1

    # Silver+ tier perk: a recognised member (matched by phone, within this
    # business) with "Priority waitlist" among their tier's perks jumps the
    # queue ahead of non-members — see WaitlistEntry.priority and
    # _public_waitlist_view below for how the ordering/ahead-count honours it.
    priority = False
    phone = (entry.guestPhone or "").strip()
    if phone:
        cust = await db.customers.find_one(
            {**tenant_scope_filter(user.get("businessId")), "$and": [scope, {"phone": phone}]}, {"_id": 0, "membershipTier": 1})
        if cust:
            tier_doc = await db.loyalty_tiers.find_one(
                {"$and": [scope, {"name": cust.get("membershipTier", "Bronze")}]}, {"_id": 0})
            if tier_doc and "Priority waitlist" in (tier_doc.get("perks") or []):
                priority = True

    entry_obj = WaitlistEntry(**entry.dict(), position=next_pos, businessId=business_id, priority=priority)
    doc = entry_obj.dict()
    await db.waitlist.insert_one(doc)
    return entry_obj

@router.put("/waitlist/{entry_id}", response_model=WaitlistEntry)
async def update_waitlist_entry(entry_id: str, update: WaitlistEntryUpdate, user: dict = Depends(get_user)):
    guard = await db.waitlist.find_one({"$and": [{"id": entry_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0})
    if not guard or not tenant_owns_strict(guard.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Waitlist entry not found")
    update_data = {k: v for k, v in update.dict().items() if v is not None}
    result = await db.waitlist.find_one_and_update(
        {"$and": [{"id": entry_id}, tenant_scope_filter(user.get("businessId"))]}, {"$set": update_data}, return_document=True
    )
    if not result:
        raise HTTPException(status_code=404, detail="Waitlist entry not found")
    result.pop("_id", None)

    # Real waitlist SMS: a "Notified" status used to be pure record-keeping
    # — the Waitlist.jsx "Notify" button already claimed "Guest notified"
    # in a toast with nothing actually sent. Fires once, only on the
    # waiting -> notified transition (not on a redundant re-save), and
    # only if the entry has a phone number. Best-effort: send_sms no-ops
    # (and logs) when Twilio isn't configured, same as every other SMS
    # send in this codebase — never blocks the status change on delivery.
    if update_data.get("status") == "notified" and guard.get("status") != "notified" and result.get("guestPhone"):
        from utils.notifications import send_sms
        biz = await db.businesses.find_one({"id": result.get("businessId")}, {"_id": 0, "name": 1})
        biz_name = (biz or {}).get("name") or "NUA"
        await send_sms(
            result["guestPhone"],
            f"Hi {result.get('guestName', 'there')}, your table at {biz_name} is ready! Please head to the host stand.",
        )
    return WaitlistEntry(**result)

@router.post("/waitlist/{entry_id}/seat")
async def seat_waitlist_guest(entry_id: str, table_id: Optional[str] = None, user: dict = Depends(get_user)):
    entry = await db.waitlist.find_one({"$and": [{"id": entry_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0})
    if not entry or not tenant_owns_strict(entry.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Waitlist entry not found")
    update_data = {"status": "seated", "seatedTime": datetime.utcnow().isoformat()}
    if table_id:
        update_data["tableId"] = table_id
    await db.waitlist.update_one({"$and": [{"id": entry_id}, tenant_scope_filter(user.get("businessId"))]}, {"$set": update_data})
    return {"message": "Guest seated from waitlist"}

@router.delete("/waitlist/{entry_id}")
async def remove_from_waitlist(entry_id: str, user: dict = Depends(get_user)):
    guard = await db.waitlist.find_one({"$and": [{"id": entry_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0, "businessId": 1})
    if not guard or not tenant_owns_strict(guard.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Entry not found")
    result = await db.waitlist.delete_one({"$and": [{"id": entry_id}, tenant_scope_filter(user.get("businessId"))]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Entry not found")
    return {"message": "Removed from waitlist"}


# ============ PUBLIC WAITLIST TRACKING (no auth — by entry code) ============
# public_join_waitlist (routes/public.py) hands the guest back their entry's
# own id as the tracking code — same access model as online order tracking
# (routes/online_orders.py): the code is the only credential, and it's only
# ever known to whoever joined the waitlist.
WAITLIST_SSE_INTERVAL_SECONDS = float(os.environ.get('TRACK_SSE_INTERVAL', '4'))
WAITLIST_SSE_MAX_SECONDS = float(os.environ.get('TRACK_SSE_MAX_SECONDS', '600'))


async def _public_waitlist_view(entry: dict) -> dict:
    """Position is recomputed live against everyone still actually waiting,
    not the value stamped at join time — that value goes stale the moment
    anyone ahead gets seated, cancels, or leaves.

    Scoped to the entry's own business, and priority-aware: a Silver+ member
    (entry.priority) is only ever queued behind an earlier-joined fellow
    priority member, never behind a non-member; a non-member is behind every
    currently-waiting priority member plus any earlier-joined non-member."""
    ahead = None
    if entry.get("status") == "waiting":
        scope = tenant_scope_filter(entry.get("businessId"))
        if entry.get("priority"):
            ahead_query = {"$and": [scope, {
                "status": "waiting", "priority": True, "position": {"$lt": entry.get("position", 0)},
            }]}
        else:
            ahead_query = {"$and": [scope, {
                "status": "waiting",
                "$or": [
                    {"priority": True},
                    {"priority": {"$ne": True}, "position": {"$lt": entry.get("position", 0)}},
                ],
            }]}
        ahead = await db.waitlist.count_documents(ahead_query)
    return {
        "id": entry["id"], "guestName": entry.get("guestName"),
        "partySize": entry.get("partySize"), "status": entry.get("status"),
        "position": (ahead + 1) if ahead is not None else None,
        "aheadOfYou": ahead,
        "quotedWait": entry.get("quotedWait"),
        "checkInTime": entry.get("checkInTime"),
        "seatedTime": entry.get("seatedTime"),
    }


@router.get("/waitlist/track/{code}")
async def track_waitlist(code: str):
    entry = await db.waitlist.find_one({"id": code.upper()}, {"_id": 0})
    if not entry:
        raise HTTPException(status_code=404, detail="Waitlist entry not found")
    return await _public_waitlist_view(entry)


@router.get("/waitlist/track/stream/{code}")
async def track_waitlist_stream(code: str, request: Request):
    """Server-sent events for one guest's own waitlist entry — the same
    push-instead-of-poll pattern as online order tracking, so a guest
    watching this page sees their position drop the moment a table frees
    up instead of waiting out a polling interval."""
    async def events():
        last = None
        started = asyncio.get_event_loop().time()
        while True:
            if asyncio.get_event_loop().time() - started > WAITLIST_SSE_MAX_SECONDS:
                return
            if await request.is_disconnected():
                return
            try:
                entry = await db.waitlist.find_one({"id": code.upper()}, {"_id": 0})
                if not entry:
                    yield "event: not_found\ndata: {}\n\n"
                    return
                payload = json.dumps(await _public_waitlist_view(entry), default=str)
                if payload != last:
                    last = payload
                    yield f"event: waitlist\ndata: {payload}\n\n"
                else:
                    yield ": keepalive\n\n"
            except Exception as e:
                logging.getLogger(__name__).warning("waitlist tracking stream error for %s: %s", code, e)
                yield ": error\n\n"
            await asyncio.sleep(WAITLIST_SSE_INTERVAL_SECONDS)

    return StreamingResponse(events(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    })


# ============ AI TABLE AUTO-ASSIGN ============
@router.post("/reservations/{reservation_id}/ai-assign-table")
async def ai_assign_table(reservation_id: str, user: dict = Depends(get_user)):
    """Auto-pick the best table for a reservation based on:
      • party size fits seats (smallest fit wins to save large tables for big parties)
      • current table status (prefer available > reserved-for-different-party > occupied later)
      • section preference if set on reservation
      • time conflict avoidance (skip tables booked within ±90min of this slot)
    """
    res = await db.reservations.find_one({"$and": [{"id": reservation_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0})
    if not res or not tenant_owns_strict(res.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Reservation not found")
    party = int(res.get("partySize", 2) or 2)

    tables = await floor_tables.list_tables()
    if not tables:
        return {"assigned": False, "reason": "No tables are configured yet"}

    # Time window check — pull same-day reservations conflicting with this slot
    same_day = await db.reservations.find({"$and": [{"date": res.get("date"), "id": {"$ne": reservation_id}}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0}).to_list(500)
    def conflicts(table_id: str) -> bool:
        for r in same_day:
            if r.get("tableId") != table_id:
                continue
            try:
                t1 = datetime.fromisoformat(f"{res['date']}T{res['time']}:00")
                t2 = datetime.fromisoformat(f"{r['date']}T{r['time']}:00")
                if abs((t1 - t2).total_seconds()) < 90 * 60:
                    return True
            except Exception:
                continue
        return False

    preferred_section = (res.get("section") or "").lower()
    candidates = []
    for t in tables:
        capacity = int(t.get("maxCovers") or t.get("capacity") or 0)
        if capacity < party:
            continue
        if conflicts(t["id"]):
            continue
        score = capacity - party                     # smaller fit wins
        if preferred_section and (t.get("section") or "").lower() == preferred_section:
            score -= 5                               # boost section match
        if t.get("status") == "available":
            score -= 2
        candidates.append((score, t))

    if not candidates:
        return {"assigned": False, "reason": "No table fits this party / time slot"}

    candidates.sort(key=lambda x: x[0])
    chosen = candidates[0][1]
    await reservation_store.update_one(
        {"$and": [{"id": reservation_id}, tenant_scope_filter(user.get("businessId"))]},
        {"$set": {"tableId": chosen["id"], "tableNumber": chosen.get("number") or chosen.get("name"), "updatedAt": datetime.utcnow().isoformat()}}
    )
    await floor_tables.set_table_status(chosen["id"], chosen.get("planId"), "reserved", reservation_id=reservation_id)
    return {
        "assigned": True,
        "tableId": chosen["id"],
        "tableName": chosen.get("name") or chosen.get("number"),
        "section": chosen.get("section"),
        "score": candidates[0][0],
    }

@router.post("/walkins/ai-assign")
async def ai_assign_walkin(body: dict, user: dict = Depends(get_user)):
    """Walk-in helper: recommend tables for an unscheduled walk-in right now.

    This only recommends — it does not seat anyone. The Walk-in AI Seat
    popup shows the top pick plus alternatives and lets staff confirm (or
    pick a different one) via POST /walkins/seat, which is where the table
    actually gets marked occupied.
    body: { partySize, section?, customerId? }
    """
    party = int(body.get("partySize", 1) or 1)
    section = (body.get("section") or "").lower()
    tables = await floor_tables.list_tables()
    if not tables:
        raise HTTPException(status_code=404, detail="No tables are configured yet")

    candidates = []
    for t in tables:
        if t.get("status") not in (None, "available", "cleaning"):
            continue
        cap = int(t.get("maxCovers") or t.get("capacity") or 0)
        if cap < party:
            continue
        score = cap - party
        if section and (t.get("section") or "").lower() == section:
            score -= 5
        if t.get("status") == "available":
            score -= 1
        candidates.append((score, t))

    guest = None
    customer_id = body.get("customerId")
    if customer_id:
        cust = await db.customers.find_one({**tenant_scope_filter(user.get("businessId")), "id": customer_id}, {"_id": 0})
        if cust and not tenant_owns_strict(cust.get("businessId"), user.get("businessId")):
            cust = None
        if cust:
            guest = {
                "id": cust.get("id"), "name": cust.get("name"),
                "isVip": bool(cust.get("isVip")), "visits": cust.get("visits", 0),
                "totalSpent": cust.get("totalSpent", 0),
                "dietaryRestrictions": cust.get("dietaryRestrictions") or [],
                "allergies": cust.get("allergies") or [],
            }

    if not candidates:
        return {"assigned": False, "reason": "No suitable table free right now", "guest": guest, "partySize": party}

    candidates.sort(key=lambda x: x[0])

    def _table_view(score, t):
        return {
            "tableId": t["id"], "tableNumber": t.get("number") or t.get("name"),
            "capacity": int(t.get("maxCovers") or t.get("capacity") or 0),
            "status": t.get("status") or "available",
            "section": t.get("section"), "floor": t.get("planName"), "floorId": t.get("planId"),
            "score": score,
        }

    ranked = [_table_view(s, t) for s, t in candidates[:6]]
    return {
        "assigned": True, "partySize": party, "guest": guest,
        "recommended": ranked[0], "alternatives": ranked[1:],
    }


@router.post("/walkins/seat")
async def seat_walkin(body: dict, user: dict = Depends(get_user)):
    """Commit a walk-in to a specific table — the confirm step after
    /walkins/ai-assign recommends one.

    Re-checks the table's live status right before writing, so two staff
    confirming the same recommendation in quick succession can't both seat
    a party on it — the second one gets a 409 instead of a silent overwrite.
    body: { tableId, partySize?, guestName?, customerId? }
    """
    table_id = body.get("tableId")
    if not table_id:
        raise HTTPException(status_code=400, detail="tableId required")
    found = await floor_tables.get_table_by_id(table_id)
    if not found:
        raise HTTPException(status_code=404, detail="Table not found")
    table, plan_id = found
    if table.get("status") not in (None, "available", "cleaning"):
        raise HTTPException(
            status_code=409,
            detail=f"Table {table.get('number') or table.get('name')} is already {table.get('status')} — pick another table",
        )
    walkin_id = f"WALK-{datetime.utcnow().strftime('%H%M%S')}"
    await floor_tables.set_table_status(table_id, plan_id, "occupied", reservation_id=walkin_id)
    return {
        "assigned": True, "walkinId": walkin_id,
        "tableId": table_id, "tableName": table.get("name") or table.get("number"),
        "section": table.get("section"),
    }
