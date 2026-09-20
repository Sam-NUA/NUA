"""Booking 3.0's second half: a real per-business cancellation-policy
engine (services/cancellation_policy.py) and real waitlist SMS.

Cancelling a booking used to always refund a collected deposit in full,
no matter how close to the reservation it happened — there was no
concept of a cancellation window at all. Now each business can configure
its own free-cancellation cutoff (GET/PUT /reservations/cancellation-policy,
default 24h); cancelling outside it still refunds in full, cancelling
inside it forfeits the deposit as a cancellation fee instead, the same
real-money-capture mechanism mark_no_show already uses for a genuine
no-show.

Waitlist SMS: routes/reservations.py's update_waitlist_entry PUT (what
Waitlist.jsx's "Notify" button calls) used to just flip a status label —
the toast said "Guest notified" but nothing was ever actually sent. Now
fires a real utils.notifications.send_sms on the waiting -> notified
transition.
"""
import asyncio
import uuid
from datetime import datetime, timedelta

from database import db
from tests.inprocess.conftest import req


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _login_as(client, owner_headers, *, email, business_id):
    client.post("/api/auth/register", headers=owner_headers, json={
        "name": "Cancel Policy Test Owner", "email": email, "password": "CancelPolicyTenant2026!",
    })
    _run(db.auth_users.update_one({"email": email}, {"$set": {"role": "owner", "businessId": business_id}}))
    r = client.post("/api/auth/login", json={"email": email, "password": "CancelPolicyTenant2026!"})
    assert r.status_code == 200, f"login failed: {r.text[:200]}"
    client.cookies.clear()
    body = r.json()
    return {"Authorization": f"Bearer {body['token']}"}


def _create_reservation(client, headers, **extra):
    payload = {
        "guestName": "Test Guest", "guestPhone": f"+6140{uuid.uuid4().int % 10000000:07d}",
        "partySize": 2, "date": "2027-06-15", "time": "19:00",
    }
    payload.update(extra)
    r = req(client, "POST", "/api/reservations", headers=headers, json=payload)
    assert r.status_code == 200, r.text[:200]
    return r.json()


def test_cancellation_policy_defaults_and_is_scoped_per_business(client, owner_headers):
    other = _login_as(client, owner_headers, email="cancelpolicy.other@nua.com", business_id="cancelpolicy-biz")

    default_policy = req(client, "GET", "/api/reservations/cancellation-policy", headers=other).json()
    assert default_policy["cutoffHours"] == 24.0

    updated = req(client, "PUT", "/api/reservations/cancellation-policy", headers=other,
                  json={"cutoffHours": 48})
    assert updated.status_code == 200, updated.text[:200]
    assert updated.json()["cutoffHours"] == 48.0

    mine_default = req(client, "GET", "/api/reservations/cancellation-policy", headers=owner_headers).json()
    assert mine_default["cutoffHours"] == 24.0, "a different business's policy edit must not change mine"

    theirs = req(client, "GET", "/api/reservations/cancellation-policy", headers=other).json()
    assert theirs["cutoffHours"] == 48.0


def test_cancellation_policy_requires_owner_or_manager_to_write(client, owner_headers):
    req(client, "POST", "/api/auth/staff/add", headers=owner_headers, json={
        "name": "Cancel Policy Cashier", "email": "cancelpolicy.cashier@nua.com",
        "password": "CashierPass1!", "role": "cashier"})
    tok = req(client, "POST", "/api/auth/login", json={
        "email": "cancelpolicy.cashier@nua.com", "password": "CashierPass1!"}).json()
    client.cookies.clear()
    cashier_headers = {"Authorization": f"Bearer {tok['token']}"}

    r = req(client, "PUT", "/api/reservations/cancellation-policy", headers=cashier_headers,
            json={"cutoffHours": 1})
    assert r.status_code == 403


def test_cancelling_outside_the_window_refunds_and_inside_it_forfeits(client, owner_headers):
    other = _login_as(client, owner_headers, email="cancelwindow.other@nua.com", business_id="cancelwindow-biz")

    # Well outside the default 24h cutoff — refund path (best-effort; no
    # STRIPE_API_KEY in this sandbox so the actual refund call short-
    # circuits to False, but depositForfeited must stay untouched).
    early = _create_reservation(client, other, guestName="Early Canceller",
                                depositRequired=20.0, depositPaid=True)
    _run(db.reservations.update_one({"id": early["id"]}, {"$set": {"depositSessionId": "cs_test_early"}}))
    try:
        r = req(client, "POST", f"/api/reservations/{early['id']}/cancel", headers=other, json={})
        assert r.status_code == 200, r.text[:200]
        body = r.json()
        assert body.get("depositForfeited") is not True, "outside the cancellation window nothing should be forfeited"
    finally:
        _run(db.reservations.delete_one({"id": early["id"]}))

    # Inside the default 24h cutoff — forfeiture path.
    near_dt = datetime.utcnow() + timedelta(hours=2)
    late = _create_reservation(client, other, guestName="Late Canceller",
                               date=near_dt.strftime("%Y-%m-%d"), time=near_dt.strftime("%H:%M"),
                               depositRequired=35.0, depositPaid=True)
    _run(db.reservations.update_one({"id": late["id"]}, {"$set": {"depositSessionId": "cs_test_late"}}))
    try:
        r = req(client, "POST", f"/api/reservations/{late['id']}/cancel", headers=other, json={})
        assert r.status_code == 200, r.text[:200]
        body = r.json()
        assert body["depositForfeited"] is True, "cancelling inside the free-cancellation window must forfeit the deposit"
        assert body["depositPaid"] is True, "forfeited money stays with the business, not refunded"
        stored = _run(db.reservations.find_one({"id": late["id"]}, {"_id": 0}))
        assert stored["status"] == "cancelled"
        assert stored["depositForfeited"] is True
    finally:
        _run(db.reservations.delete_one({"id": late["id"]}))


def test_a_later_policy_change_never_applies_retroactively_to_an_existing_booking(client, owner_headers):
    """Remediation of the final readiness audit's finding: the cutoff used
    to be looked up live at cancellation time, so tightening the policy
    AFTER a guest booked would retroactively apply to their already-
    confirmed reservation. A guest who booked under the default 24h
    promise and cancels 30 hours out — comfortably outside 24h — must
    still get a full refund even if the business later tightens the
    policy to 72h, because the booking snapshotted 24h at creation time."""
    other = _login_as(client, owner_headers, email="cancelretro.other@nua.com", business_id="cancelretro-biz")

    near_dt = datetime.utcnow() + timedelta(hours=30)
    res = _create_reservation(client, other, guestName="Retro Policy Guest",
                              date=near_dt.strftime("%Y-%m-%d"), time=near_dt.strftime("%H:%M"),
                              depositRequired=40.0, depositPaid=True)
    assert res["cancellationCutoffHours"] == 24.0
    _run(db.reservations.update_one({"id": res["id"]}, {"$set": {"depositSessionId": "cs_test_retro"}}))

    tightened = req(client, "PUT", "/api/reservations/cancellation-policy", headers=other,
                     json={"cutoffHours": 72})
    assert tightened.status_code == 200

    try:
        r = req(client, "POST", f"/api/reservations/{res['id']}/cancel", headers=other, json={})
        assert r.status_code == 200, r.text[:200]
        body = r.json()
        assert body.get("depositForfeited") is not True, (
            "a booking made under the OLD 24h policy must not be judged against "
            "the business's later-tightened 72h policy"
        )
    finally:
        req(client, "PUT", "/api/reservations/cancellation-policy", headers=other, json={"cutoffHours": 24})
        _run(db.reservations.delete_one({"id": res["id"]}))


def test_waitlist_notify_sends_a_real_sms_once(client, owner_headers, monkeypatch):
    sent = []

    async def fake_send_sms(to, body):
        sent.append((to, body))
        return {"channel": "sms", "delivered": True, "to": to}

    import utils.notifications
    monkeypatch.setattr(utils.notifications, "send_sms", fake_send_sms)

    created = req(client, "POST", "/api/waitlist", headers=owner_headers, json={
        "guestName": "SMS Test Guest", "guestPhone": "+61400111222", "partySize": 2,
    })
    assert created.status_code == 200, created.text[:200]
    entry_id = created.json()["id"]
    try:
        r = req(client, "PUT", f"/api/waitlist/{entry_id}", headers=owner_headers, json={"status": "notified"})
        assert r.status_code == 200, r.text[:200]
        assert len(sent) == 1, "the waiting -> notified transition must send exactly one real SMS"
        assert sent[0][0] == "+61400111222"
        assert "ready" in sent[0][1].lower()

        # Redundant re-save while already notified must not resend.
        r2 = req(client, "PUT", f"/api/waitlist/{entry_id}", headers=owner_headers, json={"status": "notified"})
        assert r2.status_code == 200, r2.text[:200]
        assert len(sent) == 1, "re-saving an already-notified entry must not send a second SMS"
    finally:
        _run(db.waitlist.delete_one({"id": entry_id}))


def test_waitlist_notify_with_no_phone_does_not_crash(client, owner_headers, monkeypatch):
    sent = []

    async def fake_send_sms(to, body):
        sent.append((to, body))
        return {"channel": "sms", "delivered": True, "to": to}

    import utils.notifications
    monkeypatch.setattr(utils.notifications, "send_sms", fake_send_sms)

    created = req(client, "POST", "/api/waitlist", headers=owner_headers, json={
        "guestName": "No Phone Guest", "partySize": 2,
    })
    assert created.status_code == 200, created.text[:200]
    entry_id = created.json()["id"]
    try:
        r = req(client, "PUT", f"/api/waitlist/{entry_id}", headers=owner_headers, json={"status": "notified"})
        assert r.status_code == 200, r.text[:200]
        assert len(sent) == 0
    finally:
        _run(db.waitlist.delete_one({"id": entry_id}))
