"""Server-side allocation engine.

This module is the licensable IP of the Bookings platform: how a party maps
to a resource, how double-bookings are prevented, and how the waitlist
auto-promotes. It must only ever run here — never shipped in an SDK, never
described to partners beyond the API contract ("give us a party and a time,
you get a booking or a 409").
"""
from datetime import datetime, timedelta
from typing import Optional

from database import db

ACTIVE_STATUSES = ("confirmed", "seated")


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


async def resource_is_free(resource_id: str, start: str, end: str,
                           exclude_booking_id: Optional[str] = None, test_mode: bool = False, session=None) -> bool:
    """A resource is free iff no active booking overlaps [start, end).
    Overlap: existing.start < end AND existing.end > start."""
    query = {
        "resource_id": resource_id,
        "status": {"$in": list(ACTIVE_STATUSES)},
        "start_time": {"$lt": end},
        "end_time": {"$gt": start},
        "test": True if test_mode else {"$ne": True},
    }
    if exclude_booking_id:
        query["id"] = {"$ne": exclude_booking_id}
    clash = await db.bookings.find_one(query, {"_id": 0, "id": 1}, session=session)
    return clash is None


async def allocate_resource(venue_id: str, party_size: int, start: str, end: str,
                            exclude_booking_id: Optional[str] = None,
                            test_mode: bool = False, session=None) -> Optional[dict]:
    """Pick the best free resource for a party: smallest table that fits,
    so large tables stay available for large parties. Returns None if the
    venue can't seat this party at this time."""
    candidates = await db.resources.find(
        {
            "venue_id": venue_id,
            "capacity_min": {"$lte": party_size},
            "capacity_max": {"$gte": party_size},
        },
        {"_id": 0}, session=session,
    ).to_list(500)
    candidates.sort(key=lambda r: (r.get("capacity_max", 0), r.get("capacity_min", 0)))
    for res in candidates:
        if await resource_is_free(res["id"], start, end, exclude_booking_id, test_mode, session):
            return res
    return None


async def availability(venue: dict, date: str, party_size: int,
                       slot_minutes: int = 30) -> list[dict]:
    from booking_time import instant, stamp
    from fastapi import HTTPException
    if party_size < 1 or slot_minutes < 1:
        raise HTTPException(422, "Party size and slot interval must be positive")
    duration = int(venue.get("default_duration_minutes", 90))
    zone = venue.get("timezone", "Australia/Sydney")
    day_start = instant(f"{date}T{venue.get('open_time', '11:00')}:00", zone)
    close_date = date
    if venue.get("close_time", "22:00") <= venue.get("open_time", "11:00"):
        close_date = (datetime.fromisoformat(date) + timedelta(days=1)).date().isoformat()
    day_end = instant(f"{close_date}T{venue.get('close_time', '22:00')}:00", zone)
    slots = []
    cursor = day_start
    while cursor + timedelta(minutes=duration) <= day_end:
        start_iso, end_iso = stamp(cursor), stamp(cursor + timedelta(minutes=duration))
        res = await allocate_resource(venue["id"], party_size, start_iso, end_iso,
                                      test_mode=venue.get("test", False))
        if res is not None:
            slots.append({"start_time": start_iso, "end_time": end_iso})
        cursor += timedelta(minutes=slot_minutes)
    return slots
