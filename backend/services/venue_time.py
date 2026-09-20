"""Venue-local time helpers for booking rules, cancellation windows, and
voice-inbound open-hours checks.

A reservation's `date`/`time` strings, and a business's configured
`openHours`, are wall-clock values in THAT VENUE's own timezone
(businesses.timezone, an IANA zone name like "Australia/Sydney" —
see routes/multi_tenant.py) — not UTC and not whatever timezone the
server happens to run in. Comparing them directly against a naive
datetime.now()/datetime.utcnow() (the server's clock) is wrong by
however many hours separate the venue from the server: a Sydney guest
booking "10 minutes from now" at 11pm local could be rejected as
already-passed by a UTC-hosted server that thinks it's tomorrow morning,
or a cancellation genuinely late in venue-local time could be computed
as still comfortably inside the free-cancellation window.

Same "try ZoneInfo(name), fall back to UTC with a logged warning on bad
or missing data" pattern already established in
services/repo_sync_scheduler.py's _local_tz() for its own (unrelated)
scheduled job — reused here rather than inventing a second convention.
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone as _utc_timezone
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

log = logging.getLogger("venue_time")

DEFAULT_TZ_NAME = "UTC"


def resolve_zone(tz_name: Optional[str]):
    """A business with no timezone set (or an invalid one — this field
    isn't validated as a real IANA name anywhere) falls back to UTC rather
    than raising, so a booking never hard-fails over bad timezone data."""
    if not tz_name:
        return _utc_timezone.utc
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        log.warning(f"Unknown timezone {tz_name!r}, falling back to UTC")
        return _utc_timezone.utc


def venue_now(tz_name: Optional[str]) -> datetime:
    """The current wall-clock moment in the venue's own timezone, as a
    NAIVE datetime (tzinfo stripped) — so it can be subtracted from or
    compared directly against a naive datetime parsed straight from a
    reservation's date/time strings, which carry no tzinfo of their own
    and are themselves meant to be read as venue-local wall clock."""
    return datetime.now(resolve_zone(tz_name)).replace(tzinfo=None)


async def business_timezone(business_id: Optional[str]) -> str:
    """The business's configured IANA timezone, or UTC if unset/unknown/
    the business can't be resolved — matches this codebase's existing
    "absent business_id means fully unscoped, safe default" convention
    (see middleware.actor_context.tenant_scope_filter) rather than raising."""
    if not business_id:
        return DEFAULT_TZ_NAME
    from database import db
    biz: Optional[dict] = await db.businesses.find_one({"id": business_id}, {"_id": 0, "timezone": 1})
    return (biz or {}).get("timezone") or DEFAULT_TZ_NAME


async def venue_now_for_business(business_id: Optional[str]) -> datetime:
    """Convenience combining business_timezone + venue_now for the common
    case of "I have a business_id, give me its current local wall clock."""
    return venue_now(await business_timezone(business_id))
