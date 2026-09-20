"""services/booking_rules_engine.py (the shared single source of truth for
booking capacity, blackout dates, shift-based session windows, and booking
experiences, read by both the staff and guest booking paths) had zero
businessId scoping. One business's blackout date, shift definitions, or
already-booked covers could silently affect a completely different
business's booking availability on a shared deployment, and a booking
could reference another business's "experience" package.

Only the staff-authenticated path (routes/reservations.py,
routes/phase_ef_wave2.py) is fixed here — the guest path
(routes/public.py's POST /public/book) has no business signal at all,
same pre-existing, separately-documented gap as table_ordering.py.
"""
import asyncio

from database import db
from tests.inprocess.conftest import req


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _login_as(client, owner_headers, *, email, business_id):
    client.post("/api/auth/register", headers=owner_headers, json={
        "name": "Booking Rules Test Owner", "email": email, "password": "BookingRulesTenant2026!",
    })
    _run(db.auth_users.update_one({"email": email}, {"$set": {"role": "owner", "businessId": business_id}}))
    r = client.post("/api/auth/login", json={"email": email, "password": "BookingRulesTenant2026!"})
    assert r.status_code == 200, f"login failed: {r.text[:200]}"
    client.cookies.clear()
    body = r.json()
    return {"Authorization": f"Bearer {body['token']}"}


def _future_date(days=21):
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%d")


def test_another_businesss_blackout_date_does_not_block_this_businesss_staff_booking(client, owner_headers):
    other = _login_as(client, owner_headers, email="bre.blackout.other@nua.com", business_id="bre-blackout-other-biz")
    date = _future_date()
    _run(db.booking_blackouts.insert_one({"date": date, "reason": "Other biz closed", "businessId": "bre-blackout-other-biz"}))
    try:
        r = req(client, "POST", "/api/reservations", headers=owner_headers, json={
            "guestName": "Cross Biz Blackout Test", "guestPhone": "", "guestEmail": "",
            "partySize": 2, "date": date, "time": "19:00", "source": "phone",
        })
        assert r.status_code == 200, (
            f"another business's blackout date must not block this business's booking: {r.text[:200]}"
        )
        _run(db.reservations.delete_many({"guestName": "Cross Biz Blackout Test"}))
    finally:
        _run(db.booking_blackouts.delete_many({"businessId": "bre-blackout-other-biz"}))


def test_capacity_check_does_not_pool_another_businesss_reservations(client, owner_headers):
    other = _login_as(client, owner_headers, email="bre.cap.other@nua.com", business_id="bre-cap-other-biz")
    date = _future_date()
    # Fill the other business's slot with a huge party that would blow any
    # sane capacity ceiling if it leaked into this business's check.
    _run(db.reservations.insert_one({
        "id": "RES-CAP-OTHER", "guestName": "Other Biz Mega Party", "partySize": 500,
        "date": date, "time": "19:00", "status": "confirmed", "businessId": "bre-cap-other-biz",
    }))
    try:
        rules_resp = req(client, "GET", "/api/booking/rules", headers=owner_headers)
        rules = rules_resp.json()
        req(client, "POST", "/api/booking/rules", headers=owner_headers,
            json={**rules, "enforceCapacity": True, "maxCoversPerSlot": 20})
        try:
            r = req(client, "POST", "/api/reservations", headers=owner_headers, json={
                "guestName": "Cross Biz Capacity Test", "guestPhone": "", "guestEmail": "",
                "partySize": 4, "date": date, "time": "19:00", "source": "phone",
            })
            assert r.status_code == 200, (
                f"another business's 500-cover booking must not consume this business's capacity: {r.text[:200]}"
            )
            _run(db.reservations.delete_many({"guestName": "Cross Biz Capacity Test"}))
        finally:
            req(client, "POST", "/api/booking/rules", headers=owner_headers, json=rules)
    finally:
        _run(db.reservations.delete_one({"id": "RES-CAP-OTHER"}))


def test_staff_booking_cannot_reference_another_businesss_experience(client, owner_headers):
    other = _login_as(client, owner_headers, email="bre.exp.other@nua.com", business_id="bre-exp-other-biz")
    exp = req(client, "POST", "/api/booking/experiences", headers=other, json={
        "name": "Other Biz Only Experience", "active": True,
    }).json()
    try:
        rules_resp = req(client, "GET", "/api/booking/rules", headers=owner_headers)
        rules = rules_resp.json()
        tier = {"id": "tier-cross", "minGuests": 7, "maxGuests": None, "label": "Set Menu",
                "requiresExperience": True, "allowedExperienceIds": [],
                "requireDeposit": False, "requirePreOrder": False, "requireApproval": False}
        req(client, "POST", "/api/booking/rules", headers=owner_headers,
            json={**rules, "sizeTiers": [tier]})
        try:
            r = req(client, "POST", "/api/reservations", headers=owner_headers, json={
                "guestName": "Cross Biz Experience Test", "guestPhone": "", "guestEmail": "",
                "partySize": 8, "date": _future_date(), "time": "19:00", "source": "phone",
                "experienceId": exp["id"],
            })
            assert r.status_code == 409, "must not accept another business's experience id"
        finally:
            req(client, "POST", "/api/booking/rules", headers=owner_headers, json=rules)
    finally:
        req(client, "DELETE", f"/api/booking/experiences/{exp['id']}", headers=other)
