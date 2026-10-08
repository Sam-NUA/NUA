"""Single source of truth for booking capacity, booking-size tiers, and the
booking window — read by BOTH the staff reservation path
(routes/reservations.py POST /reservations) and the customer path
(routes/public.py POST /public/book) so a rule enforced on one channel can
never be silently skipped by going through the other.

Previously `db.settings["booking_rules"]` (maxOnlinePartySize, maxAdvanceDays,
etc.) was saved by Settings > Booking Rules but never read by either booking
path — it was decorative. This module is what makes those settings (and the
new large-booking / capacity ones alongside them) actually take effect,
against every booking regardless of who or what created it.

Every check below is one of two shapes:
  - Off by default, safe to turn on gradually (sizeTiers empty, capacity
    enforcement opt-in, blockedWeekdays empty, minAdvanceHours 0, ...) — so
    enabling this module doesn't retroactively break a venue that never
    configured these settings.
  - A previously-decorative setting (maxOnlinePartySize, maxAdvanceDays)
    that now genuinely enforces what the owner already typed into Settings.

A deliberate staff override (owner/manager + a typed reason) can skip any of
these checks — that's the difference between "staff can't bypass a rule
accidentally" (the default, checks run for staff same as guests) and "staff
can never override" (too rigid for a real dining room, where a manager
sometimes needs to seat an exception).

Tenant isolation: every real per-business read this module does (blackout
dates, shift definitions, reservations counted toward capacity, booking
experiences) is scoped by an optional `business_id`, threaded through
explicitly by each caller — deliberately NOT defaulted from the request's
actor context the way most of this codebase's other tenant-isolation fixes
are (see `validate_and_enrich_booking`'s own comment for why: this module
is reachable from a genuinely anonymous guest endpoint, where the actor
context's header-based businessId fallback isn't a trustworthy signal).
Before this, a blackout date or a full slot on one business's calendar
could silently block bookings on a completely different business sharing
the same deployment, and vice versa: capacity checks pooled every
business's covers into one ceiling.

Booking rules are stored per business. Public callers resolve a real venue
before enforcing rules; unknown or ambiguous selectors fail closed.
Legacy unowned settings require evidence-based support resolution.
"""
from __future__ import annotations
import asyncio
import time
import uuid
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import datetime, date as date_cls, timezone, timedelta
from typing import Any, Dict, List, Optional

from database import db
from services import floor_tables
from middleware.actor_context import tenant_scope_filter

active_capacity_leases: ContextVar[tuple] = ContextVar("capacity_leases", default=())

_LOCK_TTL_SECONDS = 10
_LOCK_MAX_WAIT_SECONDS = 5
_LOCK_POLL_INTERVAL_SECONDS = 0.05


@asynccontextmanager
async def _acquire_one(lock_id: str):
    """Acquire a single named mutex row in db.booking_capacity_locks, TTL'd
    and token-pinned on release. Factored out of capacity_lock so a caller
    can hold more than one of these at once (see capacity_lock)."""
    token = uuid.uuid4().hex
    deadline = time.monotonic() + _LOCK_MAX_WAIT_SECONDS
    acquired = False
    try:
        while True:
            now = datetime.now(timezone.utc)
            try:
                result: Optional[dict] = await db.booking_capacity_locks.find_one_and_update(
                    {"_id": lock_id, "$or": [
                        {"expiresAt": {"$exists": False}},
                        {"expiresAt": {"$lte": now.isoformat()}},
                    ]},
                    {"$set": {"token": token,
                              "expiresAt": (now + timedelta(seconds=_LOCK_TTL_SECONDS)).isoformat()}},
                    upsert=True, return_document=True,
                )
            except Exception:
                # Two racing upserts on the same not-yet-existing _id can
                # surface as a DuplicateKeyError on the loser depending on
                # driver/server version rather than a clean re-match — treat
                # any failure here the same as "someone else holds it right
                # now" and just retry, instead of assuming this loop's own
                # bug.
                result = None
            if result and result.get("token") == token:
                acquired = True
                break
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    "Another booking for this date is being confirmed — please try again")
            await asyncio.sleep(_LOCK_POLL_INTERVAL_SECONDS)
        context_token = active_capacity_leases.set(active_capacity_leases.get() + ((lock_id, token),))
        try:
            yield
        finally:
            active_capacity_leases.reset(context_token)
    finally:
        if acquired:
            await db.booking_capacity_locks.delete_one({"_id": lock_id, "token": token})


@asynccontextmanager
async def capacity_lock(business_id: Optional[str], date_str: str):
    """Serializes reservation creation for one business's given date.

    capacity_for_slot's covers-booked count is a read (aggregate query
    across db.reservations), not a single document — unlike the atomic
    compare-and-swap this codebase uses elsewhere for a single-document race
    (services/wallet_service.py, routes/commerce_v29.py's voucher redemption),
    there's no one document to pin a filter to here. Two simultaneous
    requests for the last remaining slot on the same date would otherwise
    both read "capacity available" before either commits its insert, both
    pass validate_and_enrich_booking, and both land — overbooking despite
    enforceCapacity being on.

    Every caller of validate_and_enrich_booking that goes on to actually
    insert a reservation wraps that whole check-then-insert sequence in
    `async with capacity_lock(business_id, date):` — this is the atomic
    primitive that closes the race, not a change to the capacity math
    itself (which stays exactly the sliding ±slotBufferMinutes window it
    always was).

    Held for a bounded time (LOCK_TTL_SECONDS) so a crashed holder can never
    wedge every future booking on that date; a waiter gives up after
    LOCK_MAX_WAIT_SECONDS with a clear, retryable error rather than hanging.

    Lock granularity matches capacity_for_slot's query scope, not just the
    caller's own business_id: tenant_scope_filter() (which capacity_for_slot
    uses to count covers) matches a tagged business's own rows PLUS every
    untagged row (no businessId at all — the state of every guest-path
    booking today, and of any pre-tenant-stamping legacy row). A tagged
    business's lock used to be keyed only on its own business_id, so a
    concurrent untagged/guest booking for the same date — which still counts
    toward that business's capacity via the untagged fallback — held a
    *different* lock and could race straight through it, overbooking despite
    the lock appearing to be held. Every acquisition now also takes the
    shared "unscoped" lock for the date first, so a tagged business's
    check-then-insert and any untagged booking's check-then-insert for that
    same date are mutually exclusive, matching what their capacity reads
    actually overlap with. The cost is that all businesses now serialize
    with each other on a given date rather than just against themselves;
    acceptable until tenant stamping is fully backfilled and the untagged
    fallback stops matching anything (see this module's top-of-file
    docstring).
    """
    unscoped_id = f"unscoped:{date_str}"
    if business_id:
        async with _acquire_one(unscoped_id):
            async with _acquire_one(f"{business_id}:{date_str}"):
                yield
    else:
        async with _acquire_one(unscoped_id):
            yield


DEFAULT_RULES: Dict[str, Any] = {
    # Pre-existing (previously unread) settings
    "maxOnlinePartySize": 10,
    "maxAdvanceDays": 60,
    "bookingWindowMinutes": 30,
    "autoConfirm": True,
    "requireDeposit": False,
    "depositAmount": 0,
    "noShowFee": 0,
    "cancellationHours": 2,
    # New: booking window
    "minAdvanceHours": 0,
    "allowSameDay": True,
    "bookingOpenTime": "00:00",
    "bookingCloseTime": "23:59",
    "blockedWeekdays": [],  # e.g. ["Monday"]
    # New: capacity
    "enforceCapacity": False,  # opt-in — previously only an advisory staff check existed
    "maxCoversPerSlot": 0,     # 0 = derive from floor plan table capacity
    "slotBufferMinutes": 30,
    "capacityBySession": False,
    "maxLargeBookingsPerSession": 0,
    # New: booking-size tiers (large-booking rules) — ordered by minGuests.
    # Empty = every party is the implicit "Standard" tier, no restrictions.
    # Example shape:
    #   {"id": "tier-2", "minGuests": 7, "maxGuests": 12, "label": "Set Menu",
    #    "requiresExperience": True, "allowedExperienceIds": [],
    #    "requireDeposit": True, "requirePreOrder": True, "requireApproval": False}
    "sizeTiers": [],
}

DEFAULT_SHIFTS: List[Dict[str, str]] = [
    {"id": "shift-breakfast", "name": "Breakfast", "startTime": "07:00", "endTime": "11:00"},
    {"id": "shift-lunch", "name": "Lunch", "startTime": "11:30", "endTime": "15:00"},
    {"id": "shift-dinner", "name": "Dinner", "startTime": "17:00", "endTime": "22:00"},
]

_BASE_TIER: Dict[str, Any] = {
    "id": "default", "minGuests": 1, "maxGuests": None, "label": "Standard",
    "requiresExperience": False, "allowedExperienceIds": [],
    "requireDeposit": False, "requirePreOrder": False, "requireApproval": False,
}


class BookingRuleViolation(ValueError):
    """Message is guest-facing — safe to show verbatim in the UI."""


async def get_rules(business_id: Optional[str] = None) -> Dict[str, Any]:
    from services.tenant_settings import get_setting
    value = await get_setting("booking_rules", business_id)
    rules = dict(DEFAULT_RULES)
    if isinstance(value, dict):
        rules.update(value)
    return rules


def match_tier(tiers: List[Dict[str, Any]], party_size: int) -> Dict[str, Any]:
    """First configured tier whose [minGuests, maxGuests] contains party_size,
    ordered ascending by minGuests. Falls back to the unrestricted base tier
    (also what an empty sizeTiers list always resolves to)."""
    ordered = sorted(
        (t for t in (tiers or []) if isinstance(t, dict)),
        key=lambda t: int(t.get("minGuests") or 1),
    )
    for t in ordered:
        lo = int(t.get("minGuests") or 1)
        hi_raw = t.get("maxGuests")
        hi = int(hi_raw) if hi_raw not in (None, "") else None
        if party_size >= lo and (hi is None or party_size <= hi):
            return t
    return dict(_BASE_TIER)


async def _active_blackout(date_str: str, business_id: Optional[str] = None) -> Optional[dict]:
    query = {"$and": [tenant_scope_filter(business_id), {"date": date_str}]}
    b = await db.booking_blackouts.find_one(query, {"_id": 0})
    if not b:
        return None
    block_until = b.get("blockUntil")
    if block_until:
        try:
            exp = datetime.fromisoformat(str(block_until).replace("Z", "+00:00"))
            if datetime.now(timezone.utc) > exp:
                return None
        except Exception:
            pass
    return b


async def _session_for_time(time_str: str, business_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    shifts = await db.booking_shifts.find(tenant_scope_filter(business_id), {"_id": 0}).to_list(50)
    candidates = [s for s in shifts if s.get("enabled", True)] if shifts else DEFAULT_SHIFTS
    try:
        h, m = map(int, time_str.split(":"))
    except Exception:
        return None
    mins = h * 60 + m
    for s in candidates:
        try:
            sh, sm = map(int, str(s["startTime"]).split(":"))
            eh, em = map(int, str(s["endTime"]).split(":"))
        except Exception:
            continue
        if sh * 60 + sm <= mins <= eh * 60 + em:
            return s
    return None


async def capacity_for_slot(date_str: str, time_str: str, rules: dict,
                              exclude_reservation_id: Optional[str] = None,
                              business_id: Optional[str] = None) -> Dict[str, Any]:
    """Covers already booked within the slot's buffer window vs the ceiling.

    The ceiling is the owner's maxCoversPerSlot if they set one — an
    explicit, intentional cap, used exactly as given. Otherwise it's
    derived from the floor plan's total seat count with the existing
    overbooking buffer ratio applied (db.settings id="overbooking",
    bufferRatio, default 1.10) — the same derivation
    POST /ai/overbooking-check used on its own before it was refactored to
    call this function; kept so a venue that already tuned that ratio
    doesn't see its behavior change.
    """
    cap = int(rules.get("maxCoversPerSlot") or 0)
    if not cap:
        tables = await floor_tables.list_tables()
        floor_capacity = sum(
            int(t.get("maxCovers") or t.get("capacity") or t.get("seats") or 4) for t in tables
        ) or 60
        from services.tenant_settings import get_scoped_singleton
        overbooking_settings = await get_scoped_singleton(db.settings, {"id": "overbooking"}, business_id) or {}
        buffer_ratio = float(overbooking_settings.get("bufferRatio", 1.10))
        cap = int(floor_capacity * buffer_ratio)

    buffer_minutes = int(rules.get("slotBufferMinutes") or 30)
    try:
        h, m = map(int, time_str.split(":"))
    except Exception:
        h, m = 12, 0
    slot_mins = h * 60 + m
    slot_start, slot_end = slot_mins - buffer_minutes, slot_mins + buffer_minutes

    same_day_query = {"$and": [tenant_scope_filter(business_id),
                                {"date": date_str, "status": {"$in": ["confirmed", "seated"]}}]}
    same_day = await db.reservations.find(
        same_day_query,
        {"_id": 0, "id": 1, "time": 1, "partySize": 1},
    ).to_list(2000)
    booked = 0
    for r in same_day:
        if exclude_reservation_id and r.get("id") == exclude_reservation_id:
            continue
        try:
            rh, rm = map(int, str(r.get("time", "0:0")).split(":"))
        except Exception:
            continue
        if slot_start <= (rh * 60 + rm) <= slot_end:
            booked += int(r.get("partySize") or 0)
    return {"capacity": cap, "booked": booked, "available": max(0, cap - booked)}


def in_time_range(time_str: str, open_t: str, close_t: str) -> bool:
    if close_t >= open_t:
        return open_t <= time_str <= close_t
    # Wraps past midnight (e.g. open "18:00", close "02:00").
    return time_str >= open_t or time_str <= close_t


async def validate_and_enrich_booking(
    *, date: str, time: str, party_size: int, source: str,
    experience_id: Optional[str] = None,
    reservation_id_to_exclude: Optional[str] = None,
    override_reason: Optional[str] = None,
    override_actor: Optional[Dict[str, Any]] = None,
    business_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Raises BookingRuleViolation (message is guest-facing) on any hard
    violation. Returns a dict of fields to merge onto the Reservation being
    created/updated — the large-booking flags, matched tier, attached
    experience, and what it now requires (deposit/pre-order/approval).

    `source` gates which checks apply:
      - "walk_in": a guest already in the building. No booking-window checks
        at all (advance notice, same-day, max-advance-days, booking hours)
        — there's no "advance" to a walk-in. Capacity, blackout,
        weekday-block, and size-tier/experience rules still apply.
      - "online": the customer self-service channel. Every check applies,
        including the online-only maxOnlinePartySize ceiling and the
        "already passed" / minAdvanceHours / allowSameDay guardrails, which
        are specifically about an unsupervised customer submitting the
        public form — not a meaningful restriction on staff judgment.
      - anything else (phone/app/staff-entered): maxAdvanceDays, booking
        hours, capacity, blackout, weekday-block, and size-tier/experience
        rules all apply; the online-only checks above and
        maxOnlinePartySize do not — staff routinely create same-day phone
        bookings and backdated records (data corrections, historical entry)
        that would break if held to the same guardrails as the public form.
    """
    if not date or not time:
        raise BookingRuleViolation("Date and time are required")
    if party_size < 1:
        raise BookingRuleViolation("Party size must be at least 1")

    # Deliberately no actor-context fallback here (unlike most of this
    # codebase's other tenant-isolation fixes): this function is reachable
    # from routes/public.py's genuinely anonymous guest booking endpoint,
    # where ActorContextMiddleware's header-based businessId fallback is
    # meant for a different case (a partner/integration caller with no
    # bearer token) — trusting it here would let a client-supplied header
    # steer which business's blackout dates/capacity/experiences a guest
    # booking is checked against. Staff callers (routes/reservations.py,
    # routes/phase_ef_wave2.py) already pass their own authenticated
    # user's businessId explicitly; the guest path passes nothing, same as
    # before this module had any tenant scoping at all.
    rules = await get_rules(business_id)
    is_override = bool(override_reason) and bool(override_actor) and \
        (override_actor.get("role") in ("owner", "manager"))

    # --- Blackout dates ---
    blackout = await _active_blackout(date, business_id)
    if blackout and not is_override:
        raise BookingRuleViolation(f"Bookings paused for {date}: {blackout.get('reason') or 'closed'}")

    # --- Blocked weekdays ---
    try:
        weekday_name = date_cls.fromisoformat(date).strftime("%A")
    except Exception:
        weekday_name = None
    if weekday_name and weekday_name in (rules.get("blockedWeekdays") or []) and not is_override:
        raise BookingRuleViolation(f"We're closed for bookings on {weekday_name}s")

    # --- Booking window ---
    # Two different gates here, not one:
    #   - "already passed" / minAdvanceHours / allowSameDay are guardrails
    #     against an unsupervised customer fat-fingering (or a bad-faith
    #     script hammering) the public form — they apply to the "online"
    #     channel only. Staff routinely create phone bookings for right now,
    #     backdated data-entry corrections, and historical records; blocking
    #     those the same way would break real front-desk workflow, not
    #     protect anything.
    #   - maxAdvanceDays and booking hours are about the restaurant's actual
    #     service window (don't take a booking for a time we don't serve, or
    #     five years from now by a typo) and apply to every channel except
    #     walk-ins, where "date"/"time" is definitionally "right now."
    if source != "walk_in":
        try:
            target = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
        except Exception:
            raise BookingRuleViolation("Invalid date/time")
        from services.venue_time import venue_now_for_business
        now = await venue_now_for_business(business_id)
        delta_seconds = (target - now).total_seconds()
        if source == "online":
            # 5-minute grace so "book for right now" doesn't trip on clock
            # skew or the seconds truncated off a HH:MM time.
            if delta_seconds < -300 and not is_override:
                raise BookingRuleViolation("That date/time has already passed")
            is_same_day = target.date() == now.date()
            if is_same_day and not rules.get("allowSameDay", True) and not is_override:
                raise BookingRuleViolation("Same-day bookings aren't available — please choose a later date")
            min_advance_hours = float(rules.get("minAdvanceHours") or 0)
            if min_advance_hours > 0 and delta_seconds < min_advance_hours * 3600 and not is_override:
                raise BookingRuleViolation(f"Bookings need at least {min_advance_hours:g} hours' notice")
        max_advance_days = int(rules.get("maxAdvanceDays") or 0)
        if max_advance_days > 0 and (target.date() - now.date()).days > max_advance_days and not is_override:
            raise BookingRuleViolation(f"Bookings can only be made up to {max_advance_days} days in advance")
        open_t = rules.get("bookingOpenTime") or "00:00"
        close_t = rules.get("bookingCloseTime") or "23:59"
        if not in_time_range(time, open_t, close_t) and not is_override:
            raise BookingRuleViolation(f"Bookings are only available between {open_t} and {close_t}")

    # --- Booking-size tier + experience requirement ---
    tier = match_tier(rules.get("sizeTiers") or [], party_size)
    # "Large" means this tier actually imposes something beyond normal
    # à la carte — not just "the owner configured a tier that happened to
    # match." An owner's own base tier (e.g. "1-6 guests, À La Carte, no
    # requirements") must not read as a large booking just because they
    # gave it an id other than the literal fallback "default".
    is_large = bool(
        tier.get("requiresExperience") or tier.get("requireDeposit")
        or tier.get("requirePreOrder") or tier.get("requireApproval")
    )

    # --- Online party-size ceiling ---
    # Skipped when this party size falls under a tier that requires an
    # experience: an owner who configured e.g. a 13+ Private Dining tier
    # has, by doing so, deliberately opted online bookings back in for that
    # size — gated by picking the experience, not by maxOnlinePartySize.
    # Without this, the two settings contradict each other (a lower default
    # maxOnlinePartySize would silently block a party size the owner
    # explicitly built a tier to accept).
    max_online = int(rules.get("maxOnlinePartySize") or 0)
    if (source == "online" and max_online > 0 and party_size > max_online
            and not tier.get("requiresExperience") and not is_override):
        raise BookingRuleViolation(
            f"Online bookings are limited to {max_online} guests — please call us for larger parties"
        )

    experience = None
    if tier.get("requiresExperience") and not is_override:
        if not experience_id:
            raise BookingRuleViolation(
                f"For parties of {tier.get('minGuests')} or more, bookings are available with our "
                f"{tier.get('label') or 'Set Menu / Dining Experience'} only."
            )
        exp_query = {"$and": [tenant_scope_filter(business_id), {"id": experience_id, "active": True}]}
        experience = await db.booking_experiences.find_one(exp_query, {"_id": 0})
        if not experience:
            raise BookingRuleViolation("Selected experience isn't available")
        allowed_ids = tier.get("allowedExperienceIds") or []
        if allowed_ids and experience_id not in allowed_ids:
            raise BookingRuleViolation(
                f"That experience isn't available for parties of {party_size} — "
                f"please choose one of the {tier.get('label')} options"
            )
    elif experience_id:
        exp_query = {"$and": [tenant_scope_filter(business_id), {"id": experience_id, "active": True}]}
        experience = await db.booking_experiences.find_one(exp_query, {"_id": 0})
        if not experience and not is_override:
            raise BookingRuleViolation("Selected experience isn't available")

    # --- Capacity (opt-in — see DEFAULT_RULES["enforceCapacity"]) ---
    if rules.get("enforceCapacity") and not is_override:
        cap_info = await capacity_for_slot(date, time, rules, exclude_reservation_id=reservation_id_to_exclude,
                                            business_id=business_id)
        if cap_info["available"] < party_size:
            raise BookingRuleViolation(
                f"That time is fully booked — only {cap_info['available']} seats left "
                f"(requested {party_size})"
            )

    # --- Max large bookings per session ---
    max_large_per_session = int(rules.get("maxLargeBookingsPerSession") or 0)
    if is_large and max_large_per_session > 0 and not is_override:
        session = await _session_for_time(time, business_id)
        if session:
            existing_query = {"$and": [tenant_scope_filter(business_id),
                                        {"date": date, "status": {"$in": ["confirmed", "seated"]},
                                         "isLargeBooking": True}]}
            existing = await db.reservations.find(
                existing_query,
                {"_id": 0, "id": 1, "time": 1},
            ).to_list(500)
            try:
                sh, sm = map(int, str(session["startTime"]).split(":"))
                eh, em = map(int, str(session["endTime"]).split(":"))
                s_start, s_end = sh * 60 + sm, eh * 60 + em
            except Exception:
                s_start = s_end = None
            count_in_session = 0
            if s_start is not None:
                for r in existing:
                    if reservation_id_to_exclude and r.get("id") == reservation_id_to_exclude:
                        continue
                    try:
                        rh, rm = map(int, str(r.get("time", "0:0")).split(":"))
                    except Exception:
                        continue
                    if s_start <= (rh * 60 + rm) <= s_end:
                        count_in_session += 1
            if count_in_session >= max_large_per_session:
                raise BookingRuleViolation(
                    f"We've reached our limit of {max_large_per_session} large bookings for this "
                    f"session — please choose a different time"
                )

    enrichment: Dict[str, Any] = {
        "isLargeBooking": is_large,
        "bookingTierId": tier.get("id"),
        "bookingTierLabel": tier.get("label"),
        "experienceId": experience["id"] if experience else None,
        "experienceName": experience["name"] if experience else None,
        "preOrderRequired": bool(tier.get("requirePreOrder")) and is_large,
        "approvalRequired": bool(tier.get("requireApproval")) and is_large,
        "approvalStatus": "pending" if (is_large and tier.get("requireApproval")) else "not_required",
    }
    if is_large and tier.get("requireDeposit"):
        enrichment["depositRequired"] = float(rules.get("depositAmount") or 0)
    if is_override:
        enrichment["ruleOverrideReason"] = override_reason
        enrichment["ruleOverrideBy"] = (override_actor or {}).get("email") or (override_actor or {}).get("id")
    return enrichment
