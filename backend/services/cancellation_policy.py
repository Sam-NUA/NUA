"""Booking 3.0 — cancellation-policy engine.

A configurable per-business cutoff: cancel at least `cutoffHours` before
the reservation's own date/time and any deposit actually collected (see
routes/reservations.py's request_deposit/mark_no_show) is refunded in
full, same as cancellation always behaved before this. Cancel later than
that and the deposit is forfeited as a cancellation fee instead — the
same "keep what was actually collected, never fabricate a charge that
was never collected" mechanism mark_no_show already uses for a genuine
no-show, just triggered by a late cancellation rather than a no-show.

Per-business from day one — unlike loyalty_config (routes/loyalty_engine.py),
a documented, deliberately-not-fixed single global document elsewhere in
this codebase, cancellation_policies is keyed by businessId from the
start so this mistake isn't repeated.
"""
from datetime import datetime, timedelta
from typing import Optional

from database import db
from middleware.actor_context import tenant_scope_filter

DEFAULT_CUTOFF_HOURS = 24.0


async def get_policy(business_id: Optional[str] = None) -> dict:
    """The business's own policy if it's ever set one, else the default —
    seeded lazily on first read/write rather than a migration, same
    pattern as routes/loyalty.py's tier catalog."""
    doc = await db.cancellation_policies.find_one(tenant_scope_filter(business_id), {"_id": 0})
    if doc:
        return doc
    return {"businessId": business_id, "cutoffHours": DEFAULT_CUTOFF_HOURS}


async def snapshot_cutoff_hours(business_id: Optional[str] = None) -> float:
    """Called once, at reservation creation, to freeze the cutoff in effect
    right now onto the reservation itself (Reservation.cancellationCutoffHours).

    Without this, a later change to the business's policy applied
    retroactively to every existing booking: a guest who booked under a
    24h promise, and would cancel comfortably inside it, could find their
    deposit forfeited under a since-tightened 72h policy they never agreed
    to — is_within_free_cancellation_window looked up the CURRENT policy at
    cancellation time, not whatever was in effect when the guest committed.
    """
    policy = await get_policy(business_id)
    return float(policy.get("cutoffHours", DEFAULT_CUTOFF_HOURS))


def _reservation_datetime(res: dict) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(f"{res['date']}T{res['time']}:00")
    except Exception:
        return None


async def is_within_free_cancellation_window(res: dict, business_id: Optional[str] = None) -> bool:
    """True when this cancellation is early enough to owe nothing.

    Uses the cutoff snapshotted onto the reservation itself at creation
    time (Reservation.cancellationCutoffHours) when present, never a fresh
    live lookup of the business's CURRENT policy — a later policy change
    must never retroactively apply to a booking made under the old terms.
    Falls back to a live lookup only for a reservation created before this
    field existed (no migration needed; same lazy-seed convention
    get_policy already uses).

    A missing or unparseable reservation date/time fails toward the
    guest, not the business: we genuinely don't know how close the
    booking is, so treat it as within the free window rather than
    forfeiting money on a guess.
    """
    when = _reservation_datetime(res)
    if when is None:
        return True
    snapshotted = res.get("cancellationCutoffHours")
    if snapshotted is not None:
        cutoff_hours = float(snapshotted)
    else:
        policy = await get_policy(business_id)
        cutoff_hours = float(policy.get("cutoffHours", DEFAULT_CUTOFF_HOURS))
    cutoff = timedelta(hours=cutoff_hours)
    from services.venue_time import venue_now_for_business
    now = await venue_now_for_business(business_id)
    return (when - now) >= cutoff
