"""Beauty/services appointment booking: staff-as-resource + a service
catalog with durations, kept deliberately separate from reservations.py
(restaurant tables/floor plans/sections — a different booking shape
entirely, not something this should get bolted onto).

The overlap check below mirrors bookings-api/allocation.py's
resource_is_free exactly (same "existing.start < end AND existing.end >
start" rule) — same problem, same proven answer, just running natively
against this app's own `db.appointments` instead of a separate service,
since staff live in `db.auth_users` here and there was no clean bridge
between the two systems (see this phase's own investigation).
"""
from fastapi import APIRouter, HTTPException, Depends
from typing import List, Optional
from datetime import datetime, timedelta

from database import db
from deps import get_user, require_owner_or_manager
from middleware.actor_context import tenant_scope_filter, tenant_owns_strict
from models.service_catalog import Service, ServiceCreate, ServiceUpdate
from models.appointment import Appointment, AppointmentCreate, AppointmentUpdate
from models.client_intake import IntakeNote, IntakeNoteCreate

router = APIRouter()

ACTIVE_STATUSES = ("confirmed",)


# ============ SERVICE CATALOG ============

@router.get("/services", response_model=List[Service])
async def list_services(active_only: bool = True, user=Depends(get_user)):
    query: dict = {} if not active_only else {"active": True}
    tenant_filter = tenant_scope_filter(user.get("businessId"))
    if tenant_filter:
        query = {"$and": [query, tenant_filter]} if query else tenant_filter
    rows = await db.services.find(query).to_list(500)
    return [Service(**r) for r in rows]


@router.post("/services", response_model=Service)
async def create_service(data: ServiceCreate, user: dict = Depends(require_owner_or_manager)):
    service = Service(**data.dict(), businessId=user.get("businessId"))
    await db.services.insert_one(service.dict())
    return service


@router.put("/services/{service_id}", response_model=Service)
async def update_service(service_id: str, data: ServiceUpdate, user: dict = Depends(require_owner_or_manager)):
    existing = await db.services.find_one({"$and": [{"id": service_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0, "businessId": 1})
    if not existing or not tenant_owns_strict(existing.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Service not found")
    update_data = {k: v for k, v in data.dict().items() if v is not None}
    update_data["updatedAt"] = datetime.utcnow().isoformat()
    result = await db.services.find_one_and_update(
        {"$and": [{"id": service_id}, tenant_scope_filter(user.get("businessId"))]}, {"$set": update_data}, return_document=True,
    )
    return Service(**{k: v for k, v in result.items() if k != "_id"})


@router.delete("/services/{service_id}")
async def delete_service(service_id: str, user: dict = Depends(require_owner_or_manager)):
    existing = await db.services.find_one({"$and": [{"id": service_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0, "businessId": 1})
    if not existing or not tenant_owns_strict(existing.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Service not found")
    await db.services.update_one({"$and": [{"id": service_id}, tenant_scope_filter(user.get("businessId"))]}, {"$set": {"active": False}})
    return {"message": "Service deactivated", "id": service_id}


# ============ APPOINTMENTS ============

def _window(date: str, time: str, duration_minutes: int) -> tuple[str, str]:
    start = datetime.fromisoformat(f"{date}T{time}:00")
    end = start + timedelta(minutes=duration_minutes)
    return start.isoformat(), end.isoformat()


async def _staff_is_free(staff_id: str, start: str, end: str, exclude_id: Optional[str] = None) -> bool:
    query = {
        "staffId": staff_id,
        "status": {"$in": list(ACTIVE_STATUSES)},
        "_start": {"$lt": end},
        "_end": {"$gt": start},
    }
    if exclude_id:
        query["id"] = {"$ne": exclude_id}
    clash = await db.appointments.find_one(query, {"_id": 0, "id": 1})
    return clash is None


@router.get("/appointments", response_model=List[Appointment])
async def list_appointments(date: Optional[str] = None, staffId: Optional[str] = None,
                             status: Optional[str] = None, user=Depends(get_user)):
    and_clauses = []
    tenant_filter = tenant_scope_filter(user.get("businessId"))
    if tenant_filter:
        and_clauses.append(tenant_filter)
    if date:
        and_clauses.append({"date": date})
    if staffId:
        and_clauses.append({"staffId": staffId})
    if status:
        and_clauses.append({"status": status})
    query = {"$and": and_clauses} if and_clauses else {}
    rows = await db.appointments.find(query).sort([("date", 1), ("time", 1)]).to_list(1000)
    return [Appointment(**{k: v for k, v in r.items() if not k.startswith("_")}) for r in rows]


@router.get("/appointments/availability")
async def get_availability(staffId: str, serviceId: str, date: str, user=Depends(get_user)):
    """Every free start time for this staff member + service on this date,
    on the service's own duration, walked in 15-minute steps across a
    9am-6pm business day. A fixed default day is a real limitation — actual
    opening-hours-aware slotting is future work — but it's honest about
    what it checks: real conflicts against this staff member's existing
    appointments, not just a static grid.
    """
    service = await db.services.find_one({"id": serviceId}, {"_id": 0})
    if not service:
        raise HTTPException(status_code=404, detail="Service not found")
    duration = service.get("durationMinutes", 30)

    day_start = datetime.fromisoformat(f"{date}T09:00:00")
    day_end = datetime.fromisoformat(f"{date}T18:00:00")

    existing = await db.appointments.find({
        "staffId": staffId, "date": date, "status": {"$in": list(ACTIVE_STATUSES)},
    }, {"_id": 0, "_start": 1, "_end": 1}).to_list(200)
    busy = [(e["_start"], e["_end"]) for e in existing if e.get("_start") and e.get("_end")]

    slots = []
    cursor = day_start
    step = timedelta(minutes=15)
    dur = timedelta(minutes=duration)
    while cursor + dur <= day_end:
        s, e = cursor.isoformat(), (cursor + dur).isoformat()
        if all(not (bs < e and be > s) for bs, be in busy):
            slots.append(cursor.strftime("%H:%M"))
        cursor += step
    return {"date": date, "staffId": staffId, "serviceId": serviceId, "durationMinutes": duration, "slots": slots}


@router.post("/appointments", response_model=Appointment)
async def create_appointment(data: AppointmentCreate, user: dict = Depends(get_user)):
    service = await db.services.find_one({"id": data.serviceId}, {"_id": 0})
    if not service:
        raise HTTPException(status_code=404, detail="Service not found")
    staff = await db.auth_users.find_one({"id": data.staffId}, {"_id": 0, "name": 1})
    if not staff:
        raise HTTPException(status_code=404, detail="Staff member not found")

    start, end = _window(data.date, data.time, service.get("durationMinutes", 30))
    if not await _staff_is_free(data.staffId, start, end):
        raise HTTPException(status_code=409, detail=f"{staff.get('name')} already has an appointment then")

    appt = Appointment(
        **data.dict(), staffName=staff.get("name", ""), serviceName=service.get("name", ""),
        durationMinutes=service.get("durationMinutes", 30), price=service.get("price", 0.0),
        businessId=user.get("businessId"),
    )
    doc = appt.dict()
    doc["_start"], doc["_end"] = start, end
    # Re-check-and-insert isn't atomic against a second caller racing the
    # same slot between the check above and this insert; acceptable here
    # since appointment double-booking (unlike stock, unlike payment) is a
    # same-business staff/reception mistake to catch and reschedule, not a
    # money-safety issue — matches this app's existing reservations.py,
    # which has the same property.
    await db.appointments.insert_one(dict(doc))
    return appt


@router.put("/appointments/{appointment_id}", response_model=Appointment)
async def update_appointment(appointment_id: str, data: AppointmentUpdate, user: dict = Depends(get_user)):
    existing = await db.appointments.find_one({"$and": [{"id": appointment_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0})
    if not existing or not tenant_owns_strict(existing.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Appointment not found")

    update_data = {k: v for k, v in data.dict().items() if v is not None}
    reschedule = any(k in update_data for k in ("date", "time", "staffId", "serviceId"))

    duration = existing.get("durationMinutes", 30)
    if "serviceId" in update_data:
        service = await db.services.find_one({"id": update_data["serviceId"]}, {"_id": 0})
        if not service:
            raise HTTPException(status_code=404, detail="Service not found")
        duration = service.get("durationMinutes", 30)
        update_data["serviceName"] = service.get("name", "")
        update_data["durationMinutes"] = duration
        update_data["price"] = service.get("price", 0.0)
    if "staffId" in update_data:
        staff = await db.auth_users.find_one({"id": update_data["staffId"]}, {"_id": 0, "name": 1})
        if not staff:
            raise HTTPException(status_code=404, detail="Staff member not found")
        update_data["staffName"] = staff.get("name", "")

    if reschedule:
        new_date = update_data.get("date", existing.get("date"))
        new_time = update_data.get("time", existing.get("time"))
        new_staff = update_data.get("staffId", existing.get("staffId"))
        start, end = _window(new_date, new_time, duration)
        if not await _staff_is_free(new_staff, start, end, exclude_id=appointment_id):
            raise HTTPException(status_code=409, detail="That staff member already has an appointment then")
        update_data["_start"], update_data["_end"] = start, end

    update_data["updatedAt"] = datetime.utcnow().isoformat()
    result = await db.appointments.find_one_and_update(
        {"$and": [{"id": appointment_id}, tenant_scope_filter(user.get("businessId"))]}, {"$set": update_data}, return_document=True,
    )
    return Appointment(**{k: v for k, v in result.items() if not k.startswith("_") and k != "_id"})


async def _set_status(appointment_id: str, status: str, user: dict) -> Appointment:
    existing = await db.appointments.find_one({"$and": [{"id": appointment_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0})
    if not existing or not tenant_owns_strict(existing.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Appointment not found")
    now_iso = datetime.utcnow().isoformat()
    result = await db.appointments.find_one_and_update(
        {"$and": [{"id": appointment_id}, tenant_scope_filter(user.get("businessId"))]}, {"$set": {"status": status, "updatedAt": now_iso}}, return_document=True,
    )
    return Appointment(**{k: v for k, v in result.items() if not k.startswith("_") and k != "_id"})


@router.post("/appointments/{appointment_id}/complete", response_model=Appointment)
async def complete_appointment(appointment_id: str, user: dict = Depends(get_user)):
    return await _set_status(appointment_id, "completed", user)


@router.post("/appointments/{appointment_id}/cancel", response_model=Appointment)
async def cancel_appointment(appointment_id: str, user: dict = Depends(get_user)):
    return await _set_status(appointment_id, "cancelled", user)


@router.post("/appointments/{appointment_id}/no-show", response_model=Appointment)
async def no_show_appointment(appointment_id: str, fee: float = 0, user: dict = Depends(get_user)):
    """Same record-keeping pattern as reservations.py's mark_no_show — this
    doesn't charge a card itself (no payment integration here), it records
    what the no-show cost and tallies it against the client's history, the
    way a front-desk ledger would."""
    existing = await db.appointments.find_one({"$and": [{"id": appointment_id}, tenant_scope_filter(user.get("businessId"))]}, {"_id": 0})
    if not existing or not tenant_owns_strict(existing.get("businessId"), user.get("businessId")):
        raise HTTPException(status_code=404, detail="Appointment not found")
    now_iso = datetime.utcnow().isoformat()
    result = await db.appointments.find_one_and_update(
        {"$and": [{"id": appointment_id}, tenant_scope_filter(user.get("businessId"))]},
        {"$set": {"status": "no_show", "noShowFee": fee, "updatedAt": now_iso}},
        return_document=True,
    )
    if existing.get("customerId"):
        await db.customers.update_one({**tenant_scope_filter(user.get("businessId")), "id": existing["customerId"]}, {"$inc": {"noShowCount": 1}})
    return Appointment(**{k: v for k, v in result.items() if not k.startswith("_") and k != "_id"})


# ============ CLIENT INTAKE / CONSULTATION NOTES ============
# One record per visit (allergies/skin type/notes), not a single mutable
# profile — a chart-style history a stylist or therapist can read back
# through, the same way a medical intake form accumulates over time rather
# than being overwritten each visit.

@router.get("/client-intake", response_model=List[IntakeNote])
async def list_intake_notes(customerPhone: Optional[str] = None, customerId: Optional[str] = None,
                             user=Depends(get_user)):
    if not customerPhone and not customerId:
        raise HTTPException(status_code=400, detail="customerPhone or customerId is required")
    and_clauses = []
    tenant_filter = tenant_scope_filter(user.get("businessId"))
    if tenant_filter:
        and_clauses.append(tenant_filter)
    if customerId:
        and_clauses.append({"customerId": customerId})
    elif customerPhone:
        and_clauses.append({"customerPhone": customerPhone})
    rows = await db.client_intake.find({"$and": and_clauses}).sort("createdAt", -1).to_list(200)
    return [IntakeNote(**r) for r in rows]


@router.post("/client-intake", response_model=IntakeNote)
async def create_intake_note(data: IntakeNoteCreate, user: dict = Depends(get_user)):
    note = IntakeNote(**data.dict(), staffId=user.get("id"), staffName=user.get("name", ""),
                       businessId=user.get("businessId"))
    await db.client_intake.insert_one(note.dict())
    return note
