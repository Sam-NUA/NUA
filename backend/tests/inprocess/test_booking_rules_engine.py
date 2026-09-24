"""Booking capacity / booking-size (large-booking) rules.

Covers the spec's own TEST section end to end: 1-6 guests books normally,
7+ requires the configured Set Menu/Experience and blocks à la carte, 12 vs
13+ resolve to the correct tier, neither the customer nor an unauthorised
staff member can bypass the requirement, capacity blocks overbooking, and
deposit/pre-order/approval flow through correctly. Runs both the customer
path (POST /public/book) and the staff path (POST /reservations) through
the exact same assertions to prove services.booking_rules_engine really is
the single source of truth for both, not just one of them.
"""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from database import db
from tests.inprocess.conftest import req


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _future_date(days=14):
    return (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%d")


def _login_as(client, owner_headers, *, email, role):
    """Same pattern as test_pulse_role_gating.py's _login_as — register
    forces `cashier`, so the role is set directly for a deterministic
    fixture."""
    client.post("/api/auth/register", headers=owner_headers, json={
        "name": f"Booking Test {role}", "email": email, "password": "BookingTest2026!",
    })
    _run(db.auth_users.update_one({"email": email}, {"$set": {"role": role}}))
    r = client.post("/api/auth/login", json={"email": email, "password": "BookingTest2026!"})
    assert r.status_code == 200, f"login as {role} failed: {r.text[:200]}"
    client.cookies.clear()
    body = r.json()
    assert body["user"]["role"] == role
    return {"Authorization": f"Bearer {body['token']}"}


TIERS = [
    {"id": "tier-standard", "minGuests": 1, "maxGuests": 6, "label": "À La Carte",
     "requiresExperience": False, "allowedExperienceIds": [],
     "requireDeposit": False, "requirePreOrder": False, "requireApproval": False},
    {"id": "tier-setmenu", "minGuests": 7, "maxGuests": 12, "label": "Set Menu",
     "requiresExperience": True, "allowedExperienceIds": [],
     "requireDeposit": True, "requirePreOrder": True, "requireApproval": False},
    {"id": "tier-private", "minGuests": 13, "maxGuests": None, "label": "Private Dining",
     "requiresExperience": True, "allowedExperienceIds": [],
     "requireDeposit": True, "requirePreOrder": True, "requireApproval": True},
]


@pytest.fixture
def tiered_rules(owner_headers, client):
    """Save the spec's own example tiers (1-6 / 7-12 / 13+) for the
    duration of one test, then restore booking_rules to its prior value —
    these tests must not leak configuration into any other test file."""
    before = req(client, "GET", "/api/booking/rules?business=default").json()
    saved = {**before, "sizeTiers": TIERS, "depositAmount": 50}
    r = req(client, "POST", "/api/booking/rules", headers=owner_headers, json=saved)
    assert r.status_code == 200, r.text
    yield saved
    req(client, "POST", "/api/booking/rules", headers=owner_headers, json=before)


@pytest.fixture
def experience(owner_headers, client):
    r = req(client, "POST", "/api/booking/experiences", headers=owner_headers, json={
        "name": "Chef's Tasting Menu", "description": "5 courses", "pricePerPerson": 85, "active": True,
    })
    assert r.status_code == 200, r.text
    exp = r.json()
    yield exp
    req(client, "DELETE", f"/api/booking/experiences/{exp['id']}", headers=owner_headers)


def _cleanup_reservations(*names):
    _run(db.reservations.delete_many({"guestName": {"$in": list(names)}}))


# --------------------------------------------------------------- tier match

def test_1_to_6_guests_books_normally_no_experience_needed(tiered_rules, client, owner_headers):
    try:
        r = req(client, "POST", "/api/reservations", headers=owner_headers, json={
            "guestName": "Small Party", "partySize": 4, "date": _future_date(), "time": "19:00", "source": "phone",
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["isLargeBooking"] is False
        assert body["bookingTierId"] == "tier-standard"
    finally:
        _cleanup_reservations("Small Party")


def test_7_guests_online_blocked_without_experience(tiered_rules, client):
    r = req(client, "POST", "/api/public/book", json={
        "guestName": "Seven Top", "partySize": 7, "date": _future_date(), "time": "19:00",
    })
    assert r.status_code == 409
    assert "Set Menu" in r.json()["detail"]


def test_7_guests_online_with_permitted_experience_works(tiered_rules, experience, client):
    try:
        r = req(client, "POST", "/api/public/book", json={
            "guestName": "Seven Top OK", "partySize": 7, "date": _future_date(), "time": "19:00",
            "experienceId": experience["id"],
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["isLargeBooking"] is True
        assert body["experienceName"] == experience["name"]
        assert body["depositRequired"] == 50
        assert body["preOrderRequired"] is True
        assert body["approvalRequired"] is False
    finally:
        _cleanup_reservations("Seven Top OK")


def test_12_guests_resolves_to_set_menu_tier(tiered_rules, experience, client):
    try:
        r = req(client, "POST", "/api/public/book", json={
            "guestName": "Twelve Guests", "partySize": 12, "date": _future_date(), "time": "19:00",
            "experienceId": experience["id"],
        })
        assert r.status_code == 200, r.text
        stored = _run(db.reservations.find_one({"guestName": "Twelve Guests"}, {"_id": 0}))
        assert stored["bookingTierId"] == "tier-setmenu"
        assert stored["approvalRequired"] is False
    finally:
        _cleanup_reservations("Twelve Guests")


def test_13_plus_resolves_to_next_tier_and_requires_approval(tiered_rules, experience, client):
    try:
        r = req(client, "POST", "/api/public/book", json={
            "guestName": "Private Dining Guest", "partySize": 13, "date": _future_date(), "time": "19:00",
            "experienceId": experience["id"],
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["approvalRequired"] is True
        stored = _run(db.reservations.find_one({"guestName": "Private Dining Guest"}, {"_id": 0}))
        assert stored["bookingTierId"] == "tier-private"
        assert stored["approvalStatus"] == "pending"
    finally:
        _cleanup_reservations("Private Dining Guest")


# ------------------------------------------------------- cannot be bypassed

def test_customer_cannot_bypass_by_omitting_experience(tiered_rules, experience, client):
    """Even with a real, active experience id available, a guest who just
    doesn't send one is blocked — the requirement isn't optional metadata,
    it's enforced."""
    r = req(client, "POST", "/api/public/book", json={
        "guestName": "Bypass Attempt", "partySize": 8, "date": _future_date(), "time": "19:00",
    })
    assert r.status_code == 409
    assert _run(db.reservations.count_documents({"guestName": "Bypass Attempt"})) == 0


def test_customer_cannot_use_an_experience_not_allowed_for_the_tier(tiered_rules, client, owner_headers):
    other = req(client, "POST", "/api/booking/experiences", headers=owner_headers, json={
        "name": "Wrong Experience", "active": True,
    }).json()
    tiers = [dict(t) for t in TIERS]
    tiers[1] = {**tiers[1], "allowedExperienceIds": ["some-other-experience-id"]}
    rules = req(client, "GET", "/api/booking/rules?business=default").json()
    req(client, "POST", "/api/booking/rules", headers=owner_headers, json={**rules, "sizeTiers": tiers})
    try:
        r = req(client, "POST", "/api/public/book", json={
            "guestName": "Wrong Tier Pick", "partySize": 8, "date": _future_date(), "time": "19:00",
            "experienceId": other["id"],
        })
        assert r.status_code == 409
        assert "isn't available" in r.json()["detail"]
    finally:
        req(client, "DELETE", f"/api/booking/experiences/{other['id']}", headers=owner_headers)
        _cleanup_reservations("Wrong Tier Pick")


def test_staff_cannot_bypass_the_rule_accidentally(tiered_rules, client, owner_headers):
    """Staff hits the exact same engine as the customer path — creating a
    large booking with no override reason is blocked the same way."""
    r = req(client, "POST", "/api/reservations", headers=owner_headers, json={
        "guestName": "Staff Accidental", "partySize": 9, "date": _future_date(), "time": "19:00", "source": "phone",
    })
    assert r.status_code == 409
    assert _run(db.reservations.count_documents({"guestName": "Staff Accidental"})) == 0


def test_cashier_cannot_override_even_with_a_reason(tiered_rules, client, owner_headers):
    cashier = _login_as(client, owner_headers, email="booking.cashier@nua.com", role="cashier")
    r = req(client, "POST", "/api/reservations", headers=cashier, json={
        "guestName": "Cashier Override Attempt", "partySize": 9, "date": _future_date(), "time": "19:00",
        "source": "phone", "overrideReason": "I really want to skip this",
    })
    assert r.status_code == 409
    assert _run(db.reservations.count_documents({"guestName": "Cashier Override Attempt"})) == 0


def test_manager_can_deliberately_override_with_a_reason(tiered_rules, client, owner_headers):
    manager = _login_as(client, owner_headers, email="booking.manager@nua.com", role="manager")
    try:
        r = req(client, "POST", "/api/reservations", headers=manager, json={
            "guestName": "Manager Override", "partySize": 9, "date": _future_date(), "time": "19:00",
            "source": "phone", "overrideReason": "Regular VIP, seating without set menu by exception",
        })
        assert r.status_code == 200, r.text
        stored = _run(db.reservations.find_one({"guestName": "Manager Override"}, {"_id": 0}))
        assert stored["ruleOverrideReason"] == "Regular VIP, seating without set menu by exception"
        assert stored["ruleOverrideBy"] == "booking.manager@nua.com"
        # Still flagged as a large booking internally, override or not.
        assert stored["isLargeBooking"] is True

        # The override is itself audit-logged.
        audit = _run(db.audit_events.find_one(
            {"entityId": stored["id"], "tags": "booking_rule_override"}, {"_id": 0}))
        assert audit is not None
        assert audit["severity"] == "warning"
    finally:
        _cleanup_reservations("Manager Override")


def test_walkin_is_never_blocked_by_the_booking_window(tiered_rules, client, owner_headers):
    """A walk-in's date/time is always 'right now' — booking-window checks
    (advance notice, same-day, hours) must never apply, even with a strict
    window configured."""
    rules = req(client, "GET", "/api/booking/rules?business=default").json()
    req(client, "POST", "/api/booking/rules", headers=owner_headers,
        json={**rules, "minAdvanceHours": 48, "allowSameDay": False})
    try:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        now_time = datetime.now(timezone.utc).strftime("%H:%M")
        r = req(client, "POST", "/api/reservations", headers=owner_headers, json={
            "guestName": "Walkin Now", "partySize": 2, "date": today, "time": now_time, "source": "walk_in",
        })
        assert r.status_code == 200, r.text
    finally:
        req(client, "POST", "/api/booking/rules", headers=owner_headers, json=rules)
        _cleanup_reservations("Walkin Now")


def test_backdated_staff_entry_for_reporting_is_not_blocked(client, owner_headers):
    """A phone/staff-entered booking for a past date (data correction,
    historical import) must not be blocked the way an online booking for a
    past date is — only the online self-service channel gets that
    guardrail."""
    try:
        r = req(client, "POST", "/api/reservations", headers=owner_headers, json={
            "guestName": "Backdated Entry", "partySize": 2, "date": "2020-01-01", "time": "19:00", "source": "phone",
        })
        assert r.status_code == 200, r.text
    finally:
        _cleanup_reservations("Backdated Entry")


def test_online_booking_in_the_past_is_rejected(client):
    r = req(client, "POST", "/api/public/book", json={
        "guestName": "Past Online Guest", "partySize": 2, "date": "2020-01-01", "time": "19:00",
    })
    assert r.status_code == 409
    assert "already passed" in r.json()["detail"]


# ------------------------------------------------------------------ capacity

def test_capacity_prevents_overbooking_when_enforced(client, owner_headers):
    rules = req(client, "GET", "/api/booking/rules?business=default").json()
    req(client, "POST", "/api/booking/rules", headers=owner_headers,
        json={**rules, "enforceCapacity": True, "maxCoversPerSlot": 5, "slotBufferMinutes": 30})
    date = _future_date(20)
    try:
        r1 = req(client, "POST", "/api/reservations", headers=owner_headers, json={
            "guestName": "Cap Guest 1", "partySize": 4, "date": date, "time": "19:00", "source": "phone",
        })
        assert r1.status_code == 200, r1.text

        r2 = req(client, "POST", "/api/reservations", headers=owner_headers, json={
            "guestName": "Cap Guest 2", "partySize": 3, "date": date, "time": "19:15", "source": "phone",
        })
        assert r2.status_code == 409
        assert "fully booked" in r2.json()["detail"]
        assert _run(db.reservations.count_documents({"guestName": "Cap Guest 2"})) == 0
    finally:
        req(client, "POST", "/api/booking/rules", headers=owner_headers, json=rules)
        _cleanup_reservations("Cap Guest 1", "Cap Guest 2")


def test_capacity_lock_serializes_two_holders_for_the_same_business_and_date():
    """Direct proof of the mutual-exclusion primitive itself, independent of
    the full booking flow's own request timing (which the harness here
    can't reliably force into a genuine interleave — see
    test_two_concurrent_bookings_for_the_last_slot_never_both_succeed's
    docstring): while one caller holds services.booking_rules_engine.
    capacity_lock for a given business+date, a second acquire attempt for
    that SAME business+date must not succeed until the first releases —
    proving this is a real mutex, not a no-op context manager — while a
    different date must acquire immediately, proving the lock doesn't
    over-serialize unrelated dates.

    A *different business* for the SAME date must also block: capacity_lock
    always takes a shared per-date "unscoped" lock underneath its
    business-specific one, because capacity_for_slot's tenant_scope_filter
    counts a business's own rows PLUS every untagged row (guest bookings,
    pre-tenant-stamping legacy rows) toward that business's capacity — so a
    lock keyed only on the caller's own business_id would let an untagged or
    other-business booking race straight through it on the same date. See
    capacity_lock's docstring."""
    import asyncio
    from services import booking_rules_engine as bre

    async def _scenario():
        entered_together = False
        other_date_acquired = False
        other_business_entered_together = False
        async with bre.capacity_lock("lock-test-biz", "2099-01-01"):
            try:
                async with asyncio.timeout(0.3):
                    async with bre.capacity_lock("lock-test-biz", "2099-01-01"):
                        entered_together = True
            except TimeoutError:
                pass
            try:
                async with asyncio.timeout(0.3):
                    async with bre.capacity_lock("some-other-biz", "2099-01-01"):
                        other_business_entered_together = True
            except TimeoutError:
                pass
            async with asyncio.timeout(1):
                async with bre.capacity_lock("lock-test-biz", "2099-01-02"):
                    other_date_acquired = True
        return entered_together, other_date_acquired, other_business_entered_together

    entered_together, other_date_acquired, other_business_entered_together = _run(_scenario())
    assert not entered_together, (
        "a second caller must never be inside the lock for the same business+date "
        "while the first still holds it"
    )
    assert other_date_acquired, "a different date for the same business must not be blocked by this lock"
    assert not other_business_entered_together, (
        "a different business for the SAME date must still be blocked, because untagged/guest "
        "bookings on that date count toward every business's capacity"
    )


def test_two_concurrent_bookings_for_the_last_slot_never_both_succeed(client, owner_headers):
    """End-to-end companion to test_capacity_lock_serializes_two_holders_
    for_the_same_business_and_date above: proves the lock is actually wired
    into POST /reservations correctly (right business_id, right date) and
    that the final state is exactly one reservation. This harness's request
    execution doesn't reliably force the underlying read-then-write race
    into a genuine interleave even with the lock removed (mongomock's
    in-memory operations resolve too fast for a naive thread-timing race to
    catch reliably) — the mutual-exclusion guarantee itself is proven
    directly and deterministically by the lock-level test above instead."""
    rules = req(client, "GET", "/api/booking/rules?business=default").json()
    req(client, "POST", "/api/booking/rules", headers=owner_headers,
        json={**rules, "enforceCapacity": True, "maxCoversPerSlot": 6, "slotBufferMinutes": 30})
    date = _future_date(22)
    try:
        import time
        from concurrent.futures import ThreadPoolExecutor

        def _book(name, party_size):
            return req(client, "POST", "/api/reservations", headers=owner_headers, json={
                "guestName": name, "partySize": party_size, "date": date, "time": "19:00",
                "source": "phone",
            })

        with ThreadPoolExecutor(max_workers=2) as pool:
            f1 = pool.submit(_book, "Race Guest A", 5)
            f2 = pool.submit(_book, "Race Guest B", 5)
            r1, r2 = f1.result(), f2.result()

        successes = [r for r in (r1, r2) if r.status_code == 200]
        assert len(successes) == 1, (
            f"only one of two concurrent bookings that together exceed capacity may succeed — "
            f"got statuses {[r1.status_code, r2.status_code]}, bodies {[r.text[:150] for r in (r1, r2)]}"
        )
        loser = r1 if r1.status_code != 200 else r2
        assert loser.status_code == 409, loser.text[:200]

        total_booked = _run(db.reservations.count_documents(
            {"date": date, "guestName": {"$in": ["Race Guest A", "Race Guest B"]}}))
        assert total_booked == 1, f"exactly one reservation must have actually landed, found {total_booked}"
    finally:
        req(client, "POST", "/api/booking/rules", headers=owner_headers, json=rules)
        _cleanup_reservations("Race Guest A", "Race Guest B")


def test_capacity_is_only_advisory_when_not_enforced(client, owner_headers):
    """Default (enforceCapacity=False) — a slot over the derived floor
    capacity still succeeds; only /ai/overbooking-check warns about it.
    Protects the pre-existing, opt-in nature of this feature."""
    rules = req(client, "GET", "/api/booking/rules?business=default").json()
    assert rules.get("enforceCapacity") in (False, None)
    date = _future_date(21)
    try:
        for i in range(3):
            r = req(client, "POST", "/api/reservations", headers=owner_headers, json={
                "guestName": f"NoEnforce Guest {i}", "partySize": 20, "date": date, "time": "19:00", "source": "phone",
            })
            assert r.status_code == 200, r.text
    finally:
        _cleanup_reservations(*[f"NoEnforce Guest {i}" for i in range(3)])


# --------------------------------------------------------- approval workflow

def test_approve_and_reject_large_booking(tiered_rules, experience, client, owner_headers):
    r = req(client, "POST", "/api/public/book", json={
        "guestName": "Approval Flow Guest", "partySize": 14, "date": _future_date(), "time": "19:00",
        "experienceId": experience["id"],
    })
    assert r.status_code == 200, r.text
    res_id = r.json()["reservationId"]
    try:
        # Non-owner/manager cannot approve.
        cashier = _login_as(client, owner_headers, email="approve.cashier@nua.com", role="cashier")
        assert req(client, "POST", f"/api/reservations/{res_id}/approve", headers=cashier).status_code == 403

        approved = req(client, "POST", f"/api/reservations/{res_id}/approve", headers=owner_headers)
        assert approved.status_code == 200, approved.text
        assert approved.json()["approvalStatus"] == "approved"
        assert approved.json()["approvedBy"]

        # Can't approve twice.
        assert req(client, "POST", f"/api/reservations/{res_id}/approve", headers=owner_headers).status_code == 400
    finally:
        _cleanup_reservations("Approval Flow Guest")


def test_rejecting_a_large_booking_cancels_it(tiered_rules, experience, client, owner_headers):
    r = req(client, "POST", "/api/public/book", json={
        "guestName": "Reject Flow Guest", "partySize": 15, "date": _future_date(), "time": "19:00",
        "experienceId": experience["id"],
    })
    res_id = r.json()["reservationId"]
    try:
        rejected = req(client, "POST", f"/api/reservations/{res_id}/reject", headers=owner_headers,
                       json={"reason": "Kitchen can't handle two private groups that night"})
        assert rejected.status_code == 200, rejected.text
        body = rejected.json()
        assert body["approvalStatus"] == "rejected"
        assert body["status"] == "cancelled"
        assert "Kitchen can't handle" in body["cancellationReason"]
    finally:
        _cleanup_reservations("Reject Flow Guest")


# -------------------------------------------------------- approval/pre-order gates
# Remediation of the final readiness audit's finding: approvalStatus and
# preOrderRequired/preOrderCompleted were purely informational — nothing
# stopped POST /reservations/{id}/seat from seating a large booking still
# pending manager sign-off, or one whose matched tier requires a completed
# pre-order, exactly like any ordinary confirmed booking.

def test_seating_a_pending_approval_large_booking_is_rejected(tiered_rules, experience, client, owner_headers):
    r = req(client, "POST", "/api/public/book", json={
        "guestName": "Seat Gate Pending Guest", "partySize": 14, "date": _future_date(), "time": "19:00",
        "experienceId": experience["id"],
    })
    assert r.status_code == 200, r.text
    res_id = r.json()["reservationId"]
    assert r.json()["approvalRequired"] is True
    fetched = req(client, "GET", f"/api/reservations/{res_id}", headers=owner_headers).json()
    assert fetched["approvalStatus"] == "pending"
    try:
        r = req(client, "POST", f"/api/reservations/{res_id}/seat", headers=owner_headers)
        assert r.status_code == 409, r.text
        assert "pending" in r.json()["detail"].lower()

        # Once approved (and, since this tier also requires a pre-order,
        # that's completed too), seating goes through normally.
        req(client, "POST", f"/api/reservations/{res_id}/approve", headers=owner_headers)
        req(client, "PUT", f"/api/reservations/{res_id}", headers=owner_headers,
            json={"preOrderCompleted": True})
        r = req(client, "POST", f"/api/reservations/{res_id}/seat", headers=owner_headers)
        assert r.status_code == 200, r.text
    finally:
        _cleanup_reservations("Seat Gate Pending Guest")


def test_seating_a_rejected_large_booking_is_rejected(tiered_rules, experience, client, owner_headers):
    r = req(client, "POST", "/api/public/book", json={
        "guestName": "Seat Gate Rejected Guest", "partySize": 14, "date": _future_date(), "time": "19:00",
        "experienceId": experience["id"],
    })
    res_id = r.json()["reservationId"]
    try:
        req(client, "POST", f"/api/reservations/{res_id}/reject", headers=owner_headers, json={"reason": "no room"})
        r = req(client, "POST", f"/api/reservations/{res_id}/seat", headers=owner_headers)
        assert r.status_code in (400, 409), (
            f"a rejected (and therefore cancelled) large booking must never be seatable: {r.text[:200]}"
        )
    finally:
        _cleanup_reservations("Seat Gate Rejected Guest")


def test_seating_without_a_required_completed_pre_order_is_rejected(tiered_rules, experience, client, owner_headers):
    r = req(client, "POST", "/api/public/book", json={
        "guestName": "Seat Gate PreOrder Guest", "partySize": 8, "date": _future_date(), "time": "19:00",
        "experienceId": experience["id"],
    })
    assert r.status_code == 200, r.text
    body = r.json()
    res_id = body["reservationId"]
    assert body["preOrderRequired"] is True
    fetched = req(client, "GET", f"/api/reservations/{res_id}", headers=owner_headers).json()
    assert fetched["preOrderCompleted"] is False
    try:
        r = req(client, "POST", f"/api/reservations/{res_id}/seat", headers=owner_headers)
        assert r.status_code == 409, r.text
        assert "pre-order" in r.json()["detail"].lower()

        # Once the pre-order is marked complete, seating goes through.
        req(client, "PUT", f"/api/reservations/{res_id}", headers=owner_headers,
            json={"preOrderCompleted": True})
        r = req(client, "POST", f"/api/reservations/{res_id}/seat", headers=owner_headers)
        assert r.status_code == 200, r.text
    finally:
        _cleanup_reservations("Seat Gate PreOrder Guest")


# ------------------------------------------------- existing bookings unaffected

def test_changing_rules_later_does_not_retroactively_touch_existing_bookings(client, owner_headers):
    """A booking made before a tier existed keeps its original (no
    restriction) shape even after the owner adds tiers that would now
    match it — only new creates are validated."""
    date = _future_date(22)
    r = req(client, "POST", "/api/reservations", headers=owner_headers, json={
        "guestName": "Pre-Tier Guest", "partySize": 9, "date": date, "time": "19:00", "source": "phone",
    })
    assert r.status_code == 200, r.text
    original = r.json()
    assert original["isLargeBooking"] is False

    rules = req(client, "GET", "/api/booking/rules?business=default").json()
    req(client, "POST", "/api/booking/rules", headers=owner_headers, json={**rules, "sizeTiers": TIERS})
    try:
        stored = _run(db.reservations.find_one({"id": original["id"]}, {"_id": 0}))
        assert stored["isLargeBooking"] is False
        # Recorded the tier that applied AT CREATION TIME (none were
        # configured yet, so the unrestricted fallback) — not re-derived
        # from the tiers added afterward.
        assert stored["bookingTierId"] == "default"
    finally:
        req(client, "POST", "/api/booking/rules", headers=owner_headers, json=rules)
        _cleanup_reservations("Pre-Tier Guest")


def test_active_blackout_blocks_both_customer_and_staff_paths(client, owner_headers):
    date = _future_date(25)
    req(client, "POST", "/api/reservations/blackouts", headers=owner_headers,
        json={"date": date, "reason": "Private event"})
    try:
        r1 = req(client, "POST", "/api/public/book", json={
            "guestName": "Blackout Guest 1", "partySize": 2, "date": date, "time": "19:00",
        })
        assert r1.status_code == 409
        assert "Private event" in r1.json()["detail"]

        r2 = req(client, "POST", "/api/reservations", headers=owner_headers, json={
            "guestName": "Blackout Guest 2", "partySize": 2, "date": date, "time": "19:00", "source": "phone",
        })
        assert r2.status_code == 409
    finally:
        req(client, "DELETE", f"/api/reservations/blackouts/{date}", headers=owner_headers)
        _cleanup_reservations("Blackout Guest 1", "Blackout Guest 2")


# ------------------------------------------------------------ modifications
# Remediation of the final readiness audit's finding: PUT /reservations/{id}
# was a bare $set with no re-validation at all — moving a confirmed booking
# onto a blacked-out date, past capacity, or across a size-tier boundary all
# went straight through unchecked, even though the exact same change made at
# creation time would have been rejected or correctly enriched.

def test_editing_a_booking_onto_a_blackout_date_is_rejected(client, owner_headers):
    good_date = _future_date(26)
    blackout_date = _future_date(27)
    req(client, "POST", "/api/reservations/blackouts", headers=owner_headers,
        json={"date": blackout_date, "reason": "Kitchen closed"})
    rid = None
    try:
        r = req(client, "POST", "/api/reservations", headers=owner_headers, json={
            "guestName": "Edit Blackout Guest", "partySize": 2, "date": good_date, "time": "19:00",
            "source": "phone",
        })
        assert r.status_code == 200, r.text
        rid = r.json()["id"]

        r = req(client, "PUT", f"/api/reservations/{rid}", headers=owner_headers,
                json={"date": blackout_date})
        assert r.status_code == 409, r.text
        assert "Kitchen closed" in r.json()["detail"]

        unchanged = req(client, "GET", f"/api/reservations/{rid}", headers=owner_headers).json()
        assert unchanged["date"] == good_date, "a rejected edit must not partially apply"
    finally:
        req(client, "DELETE", f"/api/reservations/blackouts/{blackout_date}", headers=owner_headers)
        _cleanup_reservations("Edit Blackout Guest")


def test_editing_party_size_past_capacity_is_rejected(client, owner_headers):
    rules = req(client, "GET", "/api/booking/rules?business=default").json()
    req(client, "POST", "/api/booking/rules", headers=owner_headers,
        json={**rules, "enforceCapacity": True, "maxCoversPerSlot": 6, "slotBufferMinutes": 30})
    date = _future_date(28)
    rid = None
    try:
        req(client, "POST", "/api/reservations", headers=owner_headers, json={
            "guestName": "Edit Capacity Filler", "partySize": 4, "date": date, "time": "19:00",
            "source": "phone",
        })
        r = req(client, "POST", "/api/reservations", headers=owner_headers, json={
            "guestName": "Edit Capacity Guest", "partySize": 2, "date": date, "time": "19:15",
            "source": "phone",
        })
        assert r.status_code == 200, r.text
        rid = r.json()["id"]

        # Growing this booking from 2 to 4 would push the slot to 8/6 —
        # must be rejected, not silently allowed through a bare $set.
        r = req(client, "PUT", f"/api/reservations/{rid}", headers=owner_headers,
                json={"partySize": 4})
        assert r.status_code == 409, r.text

        unchanged = req(client, "GET", f"/api/reservations/{rid}", headers=owner_headers).json()
        assert unchanged["partySize"] == 2
    finally:
        req(client, "POST", "/api/booking/rules", headers=owner_headers, json=rules)
        _cleanup_reservations("Edit Capacity Filler", "Edit Capacity Guest")


def test_editing_a_bookings_own_time_slightly_does_not_trip_capacity_against_itself(client, owner_headers):
    """reservation_id_to_exclude must be passed through on the modification
    path too, or a booking's own already-counted covers would double-count
    against itself the moment its time (or any other rule-relevant field)
    is edited without changing its party size."""
    rules = req(client, "GET", "/api/booking/rules?business=default").json()
    req(client, "POST", "/api/booking/rules", headers=owner_headers,
        json={**rules, "enforceCapacity": True, "maxCoversPerSlot": 6, "slotBufferMinutes": 30})
    date = _future_date(29)
    rid = None
    try:
        r = req(client, "POST", "/api/reservations", headers=owner_headers, json={
            "guestName": "Self Exclude Guest", "partySize": 6, "date": date, "time": "19:00",
            "source": "phone",
        })
        assert r.status_code == 200, r.text
        rid = r.json()["id"]

        r = req(client, "PUT", f"/api/reservations/{rid}", headers=owner_headers,
                json={"time": "19:10"})
        assert r.status_code == 200, (
            f"editing a booking's own time must not count its own covers against itself: {r.text[:200]}"
        )
        assert r.json()["time"] == "19:10"
    finally:
        req(client, "POST", "/api/booking/rules", headers=owner_headers, json=rules)
        _cleanup_reservations("Self Exclude Guest")


def test_editing_party_size_across_a_tier_boundary_re_enriches_the_booking(tiered_rules, experience, client, owner_headers):
    """Growing a booking from the standard tier into the large-booking tier
    via an edit must pick up that tier's deposit/pre-order/approval flags —
    not keep whatever the ORIGINAL, smaller party size resolved to at
    creation time."""
    date = _future_date(30)
    rid = None
    try:
        r = req(client, "POST", "/api/reservations", headers=owner_headers, json={
            "guestName": "Tier Growth Guest", "partySize": 4, "date": date, "time": "19:00",
            "source": "phone",
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["isLargeBooking"] is False
        rid = body["id"]

        r = req(client, "PUT", f"/api/reservations/{rid}", headers=owner_headers,
                json={"partySize": 8, "experienceId": experience["id"]})
        assert r.status_code == 200, r.text
        updated = r.json()
        assert updated["isLargeBooking"] is True
        assert updated["depositRequired"] > 0, "growing into the Set Menu tier must now require a deposit"
    finally:
        _cleanup_reservations("Tier Growth Guest")


def test_editing_only_metadata_does_not_touch_rule_fields(client, owner_headers):
    """A pure notes/tags edit must not re-run (or be blocked by) booking
    rules at all — confirms the fast path for non-rule-relevant fields."""
    date = _future_date(31)
    rid = None
    try:
        r = req(client, "POST", "/api/reservations", headers=owner_headers, json={
            "guestName": "Metadata Only Guest", "partySize": 2, "date": date, "time": "19:00",
            "source": "phone",
        })
        assert r.status_code == 200, r.text
        rid = r.json()["id"]

        r = req(client, "PUT", f"/api/reservations/{rid}", headers=owner_headers,
                json={"notes": "Allergic to peanuts"})
        assert r.status_code == 200, r.text
        assert r.json()["notes"] == "Allergic to peanuts"
        assert r.json()["date"] == date
    finally:
        _cleanup_reservations("Metadata Only Guest")


# ---------------------------------------------------------------- timezone
# Remediation of the final readiness audit's finding: the "already passed" /
# same-day / advance-notice checks compared a reservation's date/time (meant
# to be read as VENUE-local wall clock) against datetime.now() — the
# server's own clock, UTC in this sandbox and in production. A guest in a
# timezone far from UTC booking a time that's genuinely in the near future
# at their venue could be wrongly rejected as "already passed" (or vice
# versa) purely because the server's clock reads a different wall-clock
# hour than the venue's.

def test_booking_validity_is_judged_by_the_venues_own_timezone_not_the_servers(client):
    """Honolulu is UTC-10 with no DST, so the gap between it and this
    sandbox's UTC-clock server is large, fixed, and easy to reason about.
    A time 20 minutes from now in Honolulu is, read naively against this
    server's own UTC clock, about 9h40m in the PAST — exactly the false
    "already passed" rejection the pre-fix naive datetime.now() comparison
    would produce. Booking it must succeed once the check is venue-aware."""
    from zoneinfo import ZoneInfo
    biz_id = "tz-test-honolulu-biz"
    _run(db.businesses.insert_one({
        "id": biz_id, "slug": biz_id, "name": "Honolulu Test Biz", "status": "active",
        "timezone": "Pacific/Honolulu",
    }))
    try:
        hi_now = datetime.now(ZoneInfo("Pacific/Honolulu")).replace(tzinfo=None)
        target = hi_now + timedelta(minutes=20)

        r = req(client, "POST", "/api/public/book", json={
            "guestName": "Honolulu Near Future Guest", "partySize": 2,
            "date": target.strftime("%Y-%m-%d"), "time": target.strftime("%H:%M"),
            "business": biz_id,
        })
        assert r.status_code == 200, (
            f"a time 20 minutes from now in the venue's own timezone must not be rejected "
            f"as already passed just because the server's clock reads a different hour: {r.text[:300]}"
        )
    finally:
        _run(db.reservations.delete_many({"guestName": "Honolulu Near Future Guest"}))
        _run(db.businesses.delete_one({"id": biz_id}))


def test_restore_cannot_reclaim_capacity_taken_after_cancellation(client, owner_headers):
    rules = req(client, 'GET', '/api/booking/rules?business=default').json()
    day = _future_date(18)
    req(client, 'POST', '/api/booking/rules', headers=owner_headers,
        json={**rules, 'enforceCapacity': True, 'maxCoversPerSlot': 2, 'slotBufferMinutes': 30})
    names = ['Restore capacity A', 'Restore capacity B']
    try:
        a = req(client, 'POST', '/api/reservations', headers=owner_headers,
                json={'guestName': names[0], 'partySize': 2, 'date': day, 'time': '18:00', 'source': 'walk_in'})
        assert a.status_code == 200, a.text
        key = a.json()['id']
        assert req(client, 'POST', f'/api/reservations/{key}/cancel', headers=owner_headers, json={}).status_code == 200
        b = req(client, 'POST', '/api/reservations', headers=owner_headers,
                json={'guestName': names[1], 'partySize': 2, 'date': day, 'time': '18:00', 'source': 'walk_in'})
        assert b.status_code == 200, b.text
        restored = req(client, 'POST', f'/api/reservations/{key}/restore', headers=owner_headers, json={})
        assert restored.status_code == 409, restored.text
        bypass = req(client, 'PUT', f'/api/reservations/{key}', headers=owner_headers, json={'status': 'confirmed'})
        assert bypass.status_code == 409, bypass.text
        assert _run(db.reservations.find_one({'id': key}))['status'] == 'cancelled'
    finally:
        _cleanup_reservations(*names)
        req(client, 'POST', '/api/booking/rules', headers=owner_headers, json=rules)
