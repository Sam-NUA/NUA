from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pymongo.errors import DuplicateKeyError

import webhooks
from allocation import allocate_resource, availability, promote_waitlist, resource_is_free, _parse
from auth import get_partner
from database import db
from models import (
    Booking, BookingCreate, BookingUpdate,
    Resource, ResourceCreate,
    Venue, VenueCreate,
    WaitlistCreate, WaitlistEntry, WaitlistUpdate,
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


async def _replay_booking(key: str, request_hash: str, partner: dict):
    existing = await db.bookings.find_one({"_id": key})
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
    slots = await availability(venue, date, party_size)
    return {"venue_id": venue_id, "date": date, "party_size": party_size, "slots": slots}


# ---- Bookings ----

@router.post("/bookings")
async def create_booking(body: BookingCreate, partner: dict = Depends(get_partner),
                         idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key")):
    venue = await _own_venue(body.venue_id, partner)
    storage_key = None
    request_hash = ""
    if idempotency_key is not None:
        if not idempotency_key.strip() or len(idempotency_key) > 200:
            raise HTTPException(400, "Idempotency-Key must contain 1 to 200 characters")
        scope = [partner["id"], bool(partner.get("test_mode")), idempotency_key]
        storage_key = "booking-request:" + hashlib.sha256(json.dumps(scope).encode()).hexdigest()
        request_hash = hashlib.sha256(
            json.dumps(body.dict(), sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        replay = await _replay_booking(storage_key, request_hash, partner)
        if replay is not None:
            return replay
    start = body.start_time
    end = body.end_time
    if not end:
        end = (_parse(start) + timedelta(minutes=venue.get("default_duration_minutes", 90))).isoformat()

    if body.resource_id:
        resource = await db.resources.find_one(
            {"id": body.resource_id, "venue_id": venue["id"]}, {"_id": 0}
        )
        if not resource:
            raise HTTPException(status_code=404, detail="Resource not found")
        if not (resource["capacity_min"] <= body.party_size <= resource["capacity_max"]):
            raise HTTPException(status_code=409, detail="Party size does not fit this resource")
        if not await resource_is_free(resource["id"], start, end, test_mode=partner.get("test_mode", False)):
            raise HTTPException(status_code=409, detail="Resource is already booked for that time")
    else:
        resource = await allocate_resource(venue["id"], body.party_size, start, end,
                                           test_mode=partner.get("test_mode", False))
        if resource is None:
            raise HTTPException(status_code=409, detail="No availability for that party size and time")

    booking = Booking(
        **{**body.dict(), "resource_id": resource["id"], "end_time": end},
        status="confirmed",
        source_partner_id=partner["id"],
        test=partner.get("test_mode", False),
        created_at=_now(), updated_at=_now(),
    )
    doc = booking.dict()
    if storage_key:
        # The booking and replay identity are one atomic insert. Mongo's _id
        # uniqueness prevents two racing retries from creating two records.
        doc.update({"_id": storage_key, "request_hash": request_hash})
    try:
        await db.bookings.insert_one(doc)
    except DuplicateKeyError:
        if storage_key:
            replay = await _replay_booking(storage_key, request_hash, partner)
            if replay is not None:
                return replay
        raise
    await log_usage(partner["id"], venue["id"], "booking.created", test=partner.get("test_mode", False))
    await webhooks.emit(partner, "booking.created", booking.dict())
    return _confirmation(partner, booking.dict())


@router.get("/bookings")
async def list_bookings(venue_id: str, date: str = None, partner: dict = Depends(get_partner)):
    await _own_venue(venue_id, partner)
    query = {"venue_id": venue_id, **_data_scope(partner)}
    if date:
        query["start_time"] = {"$gte": f"{date}T00:00:00", "$lte": f"{date}T23:59:59"}
    return await db.bookings.find(query, {"_id": 0, "request_hash": 0}).sort("start_time", 1).to_list(1000)


@router.patch("/bookings/{booking_id}")
async def update_booking(booking_id: str, body: BookingUpdate, partner: dict = Depends(get_partner)):
    booking = await db.bookings.find_one({"id": booking_id, **_data_scope(partner)}, {"_id": 0})
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    await _own_venue(booking["venue_id"], partner)

    patch = {k: v for k, v in body.dict().items() if v is not None}
    new_status = patch.get("status")
    if new_status and new_status not in ("confirmed", "seated", "no_show", "cancelled"):
        raise HTTPException(status_code=400, detail="Invalid status")

    # A time/size/resource change must re-clear allocation before it lands.
    if any(k in patch for k in ("start_time", "end_time", "party_size", "resource_id")):
        start = patch.get("start_time", booking["start_time"])
        end = patch.get("end_time", booking["end_time"])
        party = patch.get("party_size", booking["party_size"])
        target = patch.get("resource_id", booking["resource_id"])
        if target:
            resource = await db.resources.find_one({"id": target, "venue_id": booking["venue_id"]}, {"_id": 0})
            if not resource:
                raise HTTPException(status_code=404, detail="Resource not found")
            if not (resource["capacity_min"] <= party <= resource["capacity_max"]):
                raise HTTPException(status_code=409, detail="Party size does not fit this resource")
            if not await resource_is_free(target, start, end, exclude_booking_id=booking_id,
                                          test_mode=partner.get("test_mode", False)):
                raise HTTPException(status_code=409, detail="Resource is already booked for that time")
        else:
            resource = await allocate_resource(booking["venue_id"], party, start, end,
                                               exclude_booking_id=booking_id,
                                               test_mode=partner.get("test_mode", False))
            if resource is None:
                raise HTTPException(status_code=409, detail="No availability for that change")
            patch["resource_id"] = resource["id"]

    patch["updated_at"] = _now()
    updated = await db.bookings.find_one_and_update(
        {"id": booking_id}, {"$set": patch}, return_document=True
    )
    updated.pop("_id", None)

    if new_status in ("cancelled", "no_show"):
        await webhooks.emit(partner, "booking.cancelled", updated)
        # The slot just freed up — give it to the longest-waiting fitting party.
        promoted = await promote_waitlist(
            booking["venue_id"], booking.get("resource_id"),
            booking["start_time"], booking["end_time"],
            test_mode=partner.get("test_mode", False),
        )
        if promoted:
            await webhooks.emit(partner, "waitlist.seated", promoted)
    else:
        await webhooks.emit(partner, "booking.updated", updated)
    return _confirmation(partner, updated)


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
    await _own_venue(entry["venue_id"], partner)
    if body.status not in ("waiting", "seated", "abandoned"):
        raise HTTPException(status_code=400, detail="Invalid status")
    updated = await db.waitlist.find_one_and_update(
        {"id": entry_id}, {"$set": {"status": body.status}}, return_document=True
    )
    updated.pop("_id", None)
    if body.status == "seated":
        await webhooks.emit(partner, "waitlist.seated", updated)
    return updated
