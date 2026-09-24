from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pymongo.errors import DuplicateKeyError

import webhooks
from allocation import allocate_resource, availability, resource_is_free
from booking_time import window, day_window
from transactions import run_for_venue
from auth import get_partner
from database import db
from models import (
    Booking, BookingCreate, BookingUpdate, ExternalReservation,
    Resource, ResourceCreate,
    Venue, VenueCreate,
    WaitlistCreate, WaitlistEntry, WaitlistUpdate, WaitlistSeat,
)
from usage import log_usage

router = APIRouter(prefix="/v1")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _own_venue(venue_id: str, partner: dict) -> dict:
    """Every venue access goes through here — a partner can only ever touch
    venues registered under its own key."""
    venue = await db.venues.find_one({"id": venue_id, **_venue_scope(partner)}, {"_id": 0})
    if not venue:
        raise HTTPException(status_code=404, detail="Venue not found")
    return venue


def _confirmation(partner: dict, booking: dict) -> dict:
    out = dict(booking)
    out.pop("_id", None)
    out.pop("request_hash", None)
    if partner.get("branding_mode", "co-brand") == "co-brand":
        out["powered_by"] = "NUA Bookings"
    return out


def _venue_scope(partner: dict) -> dict:
    # Historical venues are live. A sandbox key must never reach them.
    return {"partner_id": partner["id"],
            "test": True if partner.get("test_mode") else {"$ne": True}}


def _data_scope(partner: dict) -> dict:
    return {"test": True if partner.get("test_mode") else {"$ne": True}}


async def _replay_booking(key: str, request_hash: str, partner: dict, session=None):
    existing = await db.bookings.find_one({"_id": key}, session=session)
    if existing is None:
        return None
    if existing.get("request_hash") != request_hash:
        raise HTTPException(409, "Idempotency-Key was already used with a different booking request")
    return _confirmation(partner, existing)


# ---- Venues & resources ----

@router.post("/venues")
async def create_venue(body: VenueCreate, partner: dict = Depends(get_partner)):
    venue = Venue(**body.dict(), partner_id=partner["id"],
                  test=partner.get("test_mode", False), created_at=_now())
    await db.venues.insert_one(venue.dict())
    return venue.dict()


@router.get("/venues")
async def list_venues(partner: dict = Depends(get_partner)):
    return await db.venues.find(_venue_scope(partner), {"_id": 0}).to_list(500)


@router.post("/venues/{venue_id}/resources")
async def create_resource(venue_id: str, body: ResourceCreate, partner: dict = Depends(get_partner)):
    await _own_venue(venue_id, partner)
    if body.capacity_min > body.capacity_max:
        raise HTTPException(status_code=400, detail="capacity_min cannot exceed capacity_max")
    resource = Resource(**body.dict(), venue_id=venue_id)
    await db.resources.insert_one(resource.dict())
    return resource.dict()


@router.get("/venues/{venue_id}/resources")
async def list_resources(venue_id: str, partner: dict = Depends(get_partner)):
    await _own_venue(venue_id, partner)
    return await db.resources.find({"venue_id": venue_id}, {"_id": 0}).to_list(500)


@router.get("/venues/{venue_id}/availability")
async def get_availability(venue_id: str, date: str, party_size: int = 2,
                           partner: dict = Depends(get_partner)):
    venue = await _own_venue(venue_id, partner)
    if venue.get("authority") == "external":
        raise HTTPException(409, "Availability is owned by the external reservation system")
    await _require_canonical(venue, partner)
    slots = await availability(venue, date, party_size)
    return {"venue_id": venue_id, "date": date, "party_size": party_size, "slots": slots}


# ---- Bookings ----

async def _require_canonical(venue, partner, session=None):
    legacy = await db.bookings.find_one({
        "venue_id": venue["id"], **_data_scope(partner),
        "status": {"$in": ["confirmed", "seated"]}, "time_format": {"$ne": "utc-v1"},
    }, {"id": 1}, session=session)
    if legacy:
        raise HTTPException(503, "Booking time migration is required before accepting more capacity")


async def _resource(venue, partner, party, start, end, target=None, exclude=None, session=None):
    await _require_canonical(venue, partner, session)
    if target:
        resource = await db.resources.find_one(
            {"id": target, "venue_id": venue["id"]}, {"_id": 0}, session=session)
        if not resource:
            raise HTTPException(404, "Resource not found")
        if not resource["capacity_min"] <= party <= resource["capacity_max"]:
            raise HTTPException(409, "Party size does not fit this resource")
        if not await resource_is_free(target, start, end, exclude,
                                      partner.get("test_mode", False), session):
            raise HTTPException(409, "Resource is already booked for that time")
        return resource
    resource = await allocate_resource(venue["id"], party, start, end, exclude,
                                       partner.get("test_mode", False), session)
    if resource is None:
        raise HTTPException(409, "No availability for that party size and time")
    return resource


async def _record_booking(body, venue, partner, session, storage_key=None, request_hash="", status="confirmed"):
    if venue.get("authority") == "external":
        raise HTTPException(409, "Reservations must be confirmed by this venue's external authority")
    start, end = window(venue, body.start_time, body.end_time)
    resource = await _resource(venue, partner, body.party_size, start, end, body.resource_id, session=session)
    booking = Booking(
        **{**body.dict(), "start_time": start, "end_time": end, "resource_id": resource["id"]},
        status=status, source_partner_id=partner["id"], test=partner.get("test_mode", False),
        created_at=_now(), updated_at=_now(),
    ).dict()
    booking["time_format"] = "utc-v1"
    doc = dict(booking)
    if storage_key:
        doc.update({"_id": storage_key, "request_hash": request_hash})
    await db.bookings.insert_one(doc, session=session)
    await log_usage(partner["id"], venue["id"], "booking.created",
                    test=partner.get("test_mode", False), session=session)
    await webhooks.emit(partner, "booking.created", booking, session=session)
    return booking


@router.post("/bookings")
async def create_booking(body: BookingCreate, partner: dict = Depends(get_partner),
                         idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key")):
    storage_key, request_hash = None, ""
    if idempotency_key is not None:
        if not idempotency_key.strip() or len(idempotency_key) > 200:
            raise HTTPException(400, "Idempotency-Key must contain 1 to 200 characters")
        scope = [partner["id"], bool(partner.get("test_mode")), idempotency_key]
        storage_key = "booking-request:" + hashlib.sha256(json.dumps(scope).encode()).hexdigest()
        request_hash = hashlib.sha256(
            json.dumps(body.dict(), sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    async def operation(venue, session):
        if storage_key:
            replay = await _replay_booking(storage_key, request_hash, partner, session)
            if replay is not None:
                return replay
        booking = await _record_booking(body, venue, partner, session, storage_key, request_hash)
        return _confirmation(partner, booking)
    try:
        return await run_for_venue(body.venue_id, partner, operation)
    except DuplicateKeyError:
        if storage_key:
            replay = await _replay_booking(storage_key, request_hash, partner)
            if replay is not None:
                return replay
        raise


@router.get("/bookings")
async def list_bookings(venue_id: str, date: str = None, partner: dict = Depends(get_partner)):
    venue = await _own_venue(venue_id, partner)
    query = {"venue_id": venue_id, **_data_scope(partner)}
    if date:
        start, end = day_window(venue, date)
        query["start_time"] = {"$gte": start, "$lt": end}
    return await db.bookings.find(query, {"_id": 0, "request_hash": 0}).sort("start_time", 1).to_list(1000)


async def _promote_waitlist(venue, partner, start, end, session):
    waiting = await db.waitlist.find(
        {"venue_id": venue["id"], "status": "waiting", **_data_scope(partner)},
        {"_id": 0}, session=session).sort("joined_at", 1).to_list(200)
    for entry in waiting:
        body = BookingCreate(venue_id=venue["id"], party_size=entry["party_size"],
                             start_time=start, end_time=end, contact_name=entry["contact_name"],
                             contact_phone=entry.get("contact_phone"))
        try:
            booking = await _record_booking(body, venue, partner, session, status="seated")
        except HTTPException as exc:
            if exc.status_code == 409:
                continue
            raise
        await db.waitlist.update_one({"id": entry["id"], "status": "waiting"}, {"$set": {
            "status": "seated", "booking_id": booking["id"], "seated_resource_id": booking["resource_id"],
        }}, session=session)
        entry.update({"status": "seated", "booking_id": booking["id"],
                      "seated_resource_id": booking["resource_id"]})
        await webhooks.emit(partner, "waitlist.seated", entry, session=session)
        return


@router.patch("/bookings/{booking_id}")
async def update_booking(booking_id: str, body: BookingUpdate, partner: dict = Depends(get_partner)):
    original = await db.bookings.find_one({"id": booking_id, **_data_scope(partner)}, {"_id": 0})
    if not original:
        raise HTTPException(404, "Booking not found")

    async def operation(venue, session):
        booking = await db.bookings.find_one(
            {"id": booking_id, "venue_id": venue["id"], **_data_scope(partner)}, {"_id": 0}, session=session)
        if not booking:
            raise HTTPException(404, "Booking not found")
        patch = {k: v for k, v in body.dict().items() if v is not None}
        status = patch.get("status", booking["status"])
        if status not in ("confirmed", "seated", "no_show", "cancelled", "completed"):
            raise HTTPException(400, "Invalid status")
        merged = {**booking, **patch}
        start, end = window(venue, merged["start_time"], merged["end_time"])
        patch.update({"start_time": start, "end_time": end, "time_format": "utc-v1", "updated_at": _now()})
        # A restore must recheck capacity even when no time field changes.
        if status in ("confirmed", "seated"):
            resource = await _resource(venue, partner, merged["party_size"], start, end,
                                       merged.get("resource_id"), booking_id, session)
            patch["resource_id"] = resource["id"]
        updated = await db.bookings.find_one_and_update(
            {"id": booking_id, "venue_id": venue["id"]}, {"$set": patch},
            return_document=True, session=session)
        updated = _confirmation(partner, updated)
        released = booking["status"] in ("confirmed", "seated") and status in ("cancelled", "no_show", "completed")
        await webhooks.emit(partner, "booking.cancelled" if status in ("cancelled", "no_show") else "booking.updated",
                            updated, session=session)
        if released:
            await _promote_waitlist(venue, partner, booking["start_time"], booking["end_time"], session)
        return updated
    return await run_for_venue(original["venue_id"], partner, operation)


# ---- Waitlist ----

@router.post("/waitlist")
async def add_waitlist(body: WaitlistCreate, partner: dict = Depends(get_partner)):
    await _own_venue(body.venue_id, partner)
    entry = WaitlistEntry(
        **body.dict(), source_partner_id=partner["id"],
        test=partner.get("test_mode", False), joined_at=_now(),
    )
    await db.waitlist.insert_one(entry.dict())
    return entry.dict()


@router.get("/waitlist")
async def list_waitlist(venue_id: str, partner: dict = Depends(get_partner)):
    await _own_venue(venue_id, partner)
    return await db.waitlist.find(
        {"venue_id": venue_id, "status": "waiting", **_data_scope(partner)}, {"_id": 0}
    ).sort("joined_at", 1).to_list(500)


@router.patch("/waitlist/{entry_id}")
async def update_waitlist(entry_id: str, body: WaitlistUpdate, partner: dict = Depends(get_partner)):
    entry = await db.waitlist.find_one({"id": entry_id, **_data_scope(partner)}, {"_id": 0})
    if not entry:
        raise HTTPException(status_code=404, detail="Waitlist entry not found")
    async def operation(venue, session):
        current = await db.waitlist.find_one({"id": entry_id, "venue_id": venue["id"], **_data_scope(partner)}, session=session)
        if body.status == "seated":
            raise HTTPException(409, "Use the seat endpoint to reserve capacity")
        if current.get("booking_id"):
            raise HTTPException(409, "Update the linked booking before changing an allocated waitlist entry")
        if body.status not in ("waiting", "abandoned"):
            raise HTTPException(400, "Invalid status")
        updated = await db.waitlist.find_one_and_update(
            {"id": entry_id}, {"$set": {"status": body.status}}, return_document=True, session=session)
        updated.pop("_id", None)
        return updated
    return await run_for_venue(entry["venue_id"], partner, operation)


@router.post("/waitlist/{entry_id}/seat")
async def seat_waitlist(entry_id: str, body: WaitlistSeat, partner: dict = Depends(get_partner)):
    entry = await db.waitlist.find_one({"id": entry_id, **_data_scope(partner)}, {"_id": 0})
    if not entry:
        raise HTTPException(404, "Waitlist entry not found")

    async def operation(venue, session):
        current = await db.waitlist.find_one({"id": entry_id, "venue_id": venue["id"], **_data_scope(partner)}, session=session)
        if current.get("booking_id"):
            booking = await db.bookings.find_one({"id": current["booking_id"]}, session=session)
            return _confirmation(partner, booking)
        if current["status"] != "waiting":
            raise HTTPException(409, "Only waiting entries can be seated")
        booking = await _record_booking(BookingCreate(
            **body.dict(), venue_id=venue["id"], party_size=current["party_size"],
            contact_name=current["contact_name"], contact_phone=current.get("contact_phone")),
            venue, partner, session, status="seated")
        patch = {"status": "seated", "booking_id": booking["id"], "seated_resource_id": booking["resource_id"]}
        await db.waitlist.update_one({"id": entry_id}, {"$set": patch}, session=session)
        current.pop("_id", None)
        await webhooks.emit(partner, "waitlist.seated", {**current, **patch}, session=session)
        return _confirmation(partner, booking)
    return await run_for_venue(entry["venue_id"], partner, operation)


@router.put("/venues/{venue_id}/external-reservations/{source_id}")
async def sync_external(venue_id: str, source_id: str, body: ExternalReservation,
                        partner: dict = Depends(get_partner)):
    if len(source_id) != 64 or any(c not in "0123456789abcdef" for c in source_id):
        raise HTTPException(422, "Source id must be a SHA-256 identifier")
    key = hashlib.sha256(f"{partner['id']}:{venue_id}:{source_id}".encode()).hexdigest()
    fingerprint = hashlib.sha256(json.dumps(body.dict(), sort_keys=True).encode()).hexdigest()

    async def operation(venue, session):
        if venue.get("authority") != "external":
            raise HTTPException(409, "This venue confirms bookings locally; external projections are disabled")
        existing = await db.external_reservations.find_one({'_id': key}, session=session)
        if existing and existing['version'] >= body.version:
            if existing['version'] == body.version and existing['fingerprint'] != fingerprint:
                raise HTTPException(409, "Source version was already used with different content")
            return {'source_id': source_id, 'version': existing['version'], 'applied': False}
        record = {'_id': key, 'source_id': source_id, 'venue_id': venue_id,
                  'partner_id': partner['id'], 'version': body.version,
                  'fingerprint': fingerprint, 'deleted': body.deleted, 'updated_at': _now()}
        if not body.deleted:
            if not body.date or not body.time:
                raise HTTPException(422, "Projection requires a local date and time")
            start, end = window({'timezone': body.source_timezone, 'default_duration_minutes': body.duration},
                                f"{body.date}T{body.time}")
            record.update({'contact_name': body.contact_name, 'contact_email': body.contact_email,
                           'contact_phone': body.contact_phone, 'party_size': body.party_size,
                           'status': body.status, 'start_time': start, 'end_time': end})
        await db.external_reservations.replace_one({'_id': key}, record, upsert=True, session=session)
        return {'source_id': source_id, 'version': body.version, 'applied': True}
    return await run_for_venue(venue_id, partner, operation)


@router.get("/venues/{venue_id}/external-reservations")
async def list_external(venue_id: str, partner: dict = Depends(get_partner)):
    await _own_venue(venue_id, partner)
    return await db.external_reservations.find(
        {'venue_id': venue_id, 'partner_id': partner['id'], 'deleted': False},
        {'_id': 0, 'fingerprint': 0}).to_list(1000)
