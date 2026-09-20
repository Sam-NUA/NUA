"""routes/reservations.py's core reservation CRUD/status endpoints
(GET/PUT/DELETE one reservation, seat, complete, no-show, cancel, approve,
reject, restore, auto-assign, ai-assign-table, guest-lookup, guest-intel,
day-counts, blackouts, walkins/ai-assign, walkins/seat) had NO auth
dependency at all on most of them, and no ownership check on the rest —
found while building Booking 3.0's real deposit/no-show payment capture.

Worse, the root cause: the Reservation model had no businessId field at
all, so create_reservation never stamped one — meaning get_reservations'
own pre-existing tenant_scope_filter call had been a silent no-op this
whole time (every reservation matched every business's safe-default
scope). Fixed by adding businessId to the model, stamping it at creation,
and adding get_user/tenant_owns to every endpoint above. services/
guest_intel.py's find_customers/build_guest_intel (shared by the booking
desk's guest-lookup and the AI phone agent) had the same zero-scoping gap
and are covered here too.

Also covers the new real payment capture: POST .../request-deposit
(Stripe Checkout for a booking's deposit — untestable end-to-end in this
sandbox with no STRIPE_API_KEY configured, so its graceful "not
configured" path is what's actually exercised) and mark_no_show's
deposit-forfeiture logic (only forfeits a deposit that was ACTUALLY
collected through a real session, never a bare depositPaid flag).
"""
import asyncio
import uuid

from database import db
from tests.inprocess.conftest import req


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _login_as(client, owner_headers, *, email, business_id):
    client.post("/api/auth/register", headers=owner_headers, json={
        "name": "Reservations Test Owner", "email": email, "password": "ReservationsTenant2026!",
    })
    _run(db.auth_users.update_one({"email": email}, {"$set": {"role": "owner", "businessId": business_id}}))
    r = client.post("/api/auth/login", json={"email": email, "password": "ReservationsTenant2026!"})
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


def test_reservation_endpoints_require_authentication(client):
    assert req(client, "GET", "/api/reservations/RES-NOPE").status_code in (401, 403)
    assert req(client, "PUT", "/api/reservations/RES-NOPE", json={}).status_code in (401, 403)
    assert req(client, "DELETE", "/api/reservations/RES-NOPE").status_code in (401, 403)
    assert req(client, "POST", "/api/reservations/RES-NOPE/seat").status_code in (401, 403)
    assert req(client, "POST", "/api/reservations/RES-NOPE/complete").status_code in (401, 403)
    assert req(client, "POST", "/api/reservations/RES-NOPE/no-show").status_code in (401, 403)
    assert req(client, "POST", "/api/reservations/RES-NOPE/cancel").status_code in (401, 403)
    assert req(client, "POST", "/api/reservations/RES-NOPE/approve").status_code in (401, 403)
    assert req(client, "POST", "/api/reservations/RES-NOPE/reject").status_code in (401, 403)
    assert req(client, "POST", "/api/reservations/RES-NOPE/restore").status_code in (401, 403)
    assert req(client, "GET", "/api/reservations/auto-assign/RES-NOPE").status_code in (401, 403)
    assert req(client, "POST", "/api/reservations/RES-NOPE/ai-assign-table").status_code in (401, 403)
    assert req(client, "POST", "/api/reservations/RES-NOPE/request-deposit", json={}).status_code in (401, 403)
    assert req(client, "GET", "/api/reservations/guest-lookup", params={"q": "x"}).status_code in (401, 403)
    assert req(client, "GET", "/api/reservations/guest-intel/some-id").status_code in (401, 403)
    assert req(client, "GET", "/api/reservations/day-counts",
               params={"fromDate": "2027-01-01", "toDate": "2027-01-02"}).status_code in (401, 403)
    assert req(client, "GET", "/api/reservations/blackouts").status_code in (401, 403)
    assert req(client, "POST", "/api/reservations/blackouts", json={"date": "2027-01-01"}).status_code in (401, 403)
    assert req(client, "DELETE", "/api/reservations/blackouts/2027-01-01").status_code in (401, 403)
    assert req(client, "POST", "/api/walkins/ai-assign", json={}).status_code in (401, 403)
    assert req(client, "POST", "/api/walkins/seat", json={}).status_code in (401, 403)


def test_reservation_is_scoped_and_owned_per_business(client, owner_headers):
    other = _login_as(client, owner_headers, email="res.other@nua.com", business_id="res-other-biz")
    created = _create_reservation(client, other, guestName="Other Biz Guest")
    rid = created["id"]
    assert created["businessId"] == "res-other-biz", "creation must stamp the real businessId, not leave it unset"
    try:
        mine_list = req(client, "GET", "/api/reservations", headers=owner_headers).json()
        assert not any(r["id"] == rid for r in mine_list)
        own_list = req(client, "GET", "/api/reservations", headers=other).json()
        assert any(r["id"] == rid for r in own_list)

        assert req(client, "GET", f"/api/reservations/{rid}", headers=owner_headers).status_code == 404
        assert req(client, "GET", f"/api/reservations/{rid}", headers=other).status_code == 200

        assert req(client, "PUT", f"/api/reservations/{rid}", headers=owner_headers,
                   json={"notes": "hacked"}).status_code == 404
        assert req(client, "POST", f"/api/reservations/{rid}/seat", headers=owner_headers).status_code == 404
        assert req(client, "POST", f"/api/reservations/{rid}/complete", headers=owner_headers).status_code == 404
        assert req(client, "POST", f"/api/reservations/{rid}/no-show", headers=owner_headers).status_code == 404
        assert req(client, "POST", f"/api/reservations/{rid}/cancel", headers=owner_headers).status_code == 404
        assert req(client, "GET", f"/api/reservations/auto-assign/{rid}", headers=owner_headers).status_code == 404
        assert req(client, "POST", f"/api/reservations/{rid}/ai-assign-table", headers=owner_headers).status_code == 404
        assert req(client, "POST", f"/api/reservations/{rid}/request-deposit", headers=owner_headers,
                   json={}).status_code == 404
        assert req(client, "DELETE", f"/api/reservations/{rid}", headers=owner_headers).status_code == 404

        # Confirm the cross-tenant delete really didn't happen.
        assert req(client, "GET", f"/api/reservations/{rid}", headers=other).status_code == 200
    finally:
        _run(db.reservations.delete_one({"id": rid}))


def test_guest_lookup_and_intel_are_scoped_per_business(client, owner_headers):
    other = _login_as(client, owner_headers, email="res.guestintel.other@nua.com", business_id="res-guestintel-biz")
    phone = f"+6141{uuid.uuid4().int % 10000000:07d}"
    cust = {
        "id": str(uuid.uuid4()), "name": "Guest Intel Test", "email": f"{uuid.uuid4().hex[:8]}@test.com",
        "phone": phone, "points": 0, "totalSpent": 0.0, "visits": 0, "businessId": "res-guestintel-biz",
    }
    try:
        _run(db.customers.insert_one(dict(cust)))
        mine = req(client, "GET", "/api/reservations/guest-lookup", headers=owner_headers,
                   params={"phone": phone}).json()
        assert not any(m.get("customerId") == cust["id"] for m in mine["matches"])

        own = req(client, "GET", "/api/reservations/guest-lookup", headers=other,
                  params={"phone": phone}).json()
        assert any(m.get("customerId") == cust["id"] for m in own["matches"])

        cross_intel = req(client, "GET", f"/api/reservations/guest-intel/{cust['id']}", headers=owner_headers)
        assert cross_intel.status_code == 404

        own_intel = req(client, "GET", f"/api/reservations/guest-intel/{cust['id']}", headers=other)
        assert own_intel.status_code == 200, own_intel.text[:200]
    finally:
        _run(db.customers.delete_one({"id": cust["id"]}))


def test_blackouts_are_independent_per_business_on_the_same_date(client, owner_headers):
    other = _login_as(client, owner_headers, email="res.blackout.other@nua.com", business_id="res-blackout-biz")
    date = "2027-12-25"
    try:
        mine = req(client, "POST", "/api/reservations/blackouts", headers=owner_headers,
                   json={"date": date, "reason": "Mine closed"})
        assert mine.status_code == 200, mine.text[:200]
        theirs = req(client, "POST", "/api/reservations/blackouts", headers=other,
                     json={"date": date, "reason": "Theirs closed for a different reason"})
        assert theirs.status_code == 200, theirs.text[:200]

        mine_list = req(client, "GET", "/api/reservations/blackouts", headers=owner_headers,
                        params={"fromDate": date, "toDate": date}).json()
        mine_row = next((b for b in mine_list if b["date"] == date), None)
        assert mine_row is not None and mine_row["reason"] == "Mine closed", (
            "a second business blacking out the same date must not overwrite the first business's blackout")

        their_list = req(client, "GET", "/api/reservations/blackouts", headers=other,
                         params={"fromDate": date, "toDate": date}).json()
        their_row = next((b for b in their_list if b["date"] == date), None)
        assert their_row is not None and their_row["reason"] == "Theirs closed for a different reason"
    finally:
        req(client, "DELETE", f"/api/reservations/blackouts/{date}", headers=owner_headers)
        req(client, "DELETE", f"/api/reservations/blackouts/{date}", headers=other)


def test_no_show_forfeits_a_real_deposit_but_not_a_bare_flag(client, owner_headers):
    other = _login_as(client, owner_headers, email="res.noshow.other@nua.com", business_id="res-noshow-biz")

    # Case 1: a real deposit collected through an actual Stripe session
    # (depositSessionId set, not just a staff-ticked box) — no-show must
    # forfeit it.
    real_deposit = _create_reservation(client, other, guestName="Real Deposit Guest",
                                        depositRequired=50.0, depositPaid=True)
    _run(db.reservations.update_one({"id": real_deposit["id"]},
                                     {"$set": {"depositSessionId": "cs_test_fake_session"}}))
    try:
        r = req(client, "POST", f"/api/reservations/{real_deposit['id']}/no-show", headers=other, json={})
        assert r.status_code == 200, r.text[:200]
        body = r.json()
        assert body["depositForfeited"] is True
        assert body["forfeitedAmount"] == 50.0
        stored = _run(db.reservations.find_one({"id": real_deposit["id"]}, {"_id": 0}))
        assert stored["depositForfeited"] is True
        assert stored["status"] == "no_show"
    finally:
        _run(db.reservations.delete_one({"id": real_deposit["id"]}))

    # Case 2: depositPaid=True but no depositSessionId at all — the old
    # staff-ticked-checkbox case, no real money was ever actually
    # collected through this system, so there's nothing to forfeit.
    fake_deposit = _create_reservation(client, other, guestName="Bare Flag Guest",
                                        depositRequired=50.0, depositPaid=True)
    try:
        r = req(client, "POST", f"/api/reservations/{fake_deposit['id']}/no-show", headers=other,
                json={}, params={"fee": 25})
        assert r.status_code == 200, r.text[:200]
        body = r.json()
        assert body["depositForfeited"] is False
        assert body["forfeitedAmount"] == 0
        stored = _run(db.reservations.find_one({"id": fake_deposit["id"]}, {"_id": 0}))
        assert stored["noShowFee"] == 25
        assert stored.get("depositForfeited") is not True
    finally:
        _run(db.reservations.delete_one({"id": fake_deposit["id"]}))


def test_cancel_attempts_a_refund_of_a_paid_deposit(client, owner_headers):
    other = _login_as(client, owner_headers, email="res.cancel.other@nua.com", business_id="res-cancel-biz")
    res = _create_reservation(client, other, guestName="Cancel Deposit Guest",
                              depositRequired=30.0, depositPaid=True)
    _run(db.reservations.update_one({"id": res["id"]}, {"$set": {"depositSessionId": "cs_test_fake_session_2"}}))
    try:
        r = req(client, "POST", f"/api/reservations/{res['id']}/cancel", headers=other, json={"reason": "test"})
        assert r.status_code == 200, r.text[:200]
        body = r.json()
        # No STRIPE_API_KEY is configured in this sandbox, so
        # refund_stripe_payment short-circuits to False (see
        # routes/integrations.py) — the honest, testable behaviour here is
        # that cancellation still succeeds (never blocked by a failed
        # refund) and depositPaid/depositRefunded reflect the refund NOT
        # having actually happened, rather than lying that it did.
        assert body["status"] == "cancelled"
        assert body["depositPaid"] is True
        assert body["depositRefunded"] is False
    finally:
        _run(db.reservations.delete_one({"id": res["id"]}))


def test_request_deposit_validates_and_degrades_without_stripe_configured(client, owner_headers):
    other = _login_as(client, owner_headers, email="res.deposit.other@nua.com", business_id="res-deposit-biz")

    no_deposit = _create_reservation(client, other, guestName="No Deposit Guest")
    try:
        r = req(client, "POST", f"/api/reservations/{no_deposit['id']}/request-deposit", headers=other, json={})
        assert r.status_code == 400
    finally:
        _run(db.reservations.delete_one({"id": no_deposit["id"]}))

    needs_deposit = _create_reservation(client, other, guestName="Needs Deposit Guest", depositRequired=40.0)
    try:
        r = req(client, "POST", f"/api/reservations/{needs_deposit['id']}/request-deposit", headers=other, json={})
        assert r.status_code == 200, r.text[:200]
        body = r.json()
        # This sandbox has no STRIPE_API_KEY — the honest, testable
        # behaviour is graceful degradation (configured:false), the same
        # pattern routes/online_orders.py's checkout endpoint uses, not a
        # crash or a fabricated session.
        assert body["configured"] is False
        assert body["url"] is None
    finally:
        _run(db.reservations.delete_one({"id": needs_deposit["id"]}))


# ---------------------------------------------- untagged-doc quarantine
# Tenant-ownership release-closure pass: every tenant_owns() check in this
# file was converted to tenant_owns_strict() now that the only remaining
# active untagged-reservation-creation path (routes/public.py's
# /public/book) requires a resolved business (see that file's own tests).
# An untagged reservation/waitlist entry here can now only be genuine
# pre-fix legacy data — quarantined (refused, never auto-owned or deleted)
# rather than readable/editable by whichever business asks first.


def test_get_reservation_refuses_a_doc_with_no_businessId(client, owner_headers):
    untagged_id = "RES-QUARANTINE-TEST-1"
    _run(db.reservations.insert_one({
        "id": untagged_id, "guestName": "Untagged Legacy Guest", "guestPhone": "+61400000900",
        "partySize": 2, "date": "2027-06-15", "time": "19:00", "status": "confirmed", "businessId": None,
    }))
    try:
        r = req(client, "GET", f"/api/reservations/{untagged_id}", headers=owner_headers)
        assert r.status_code == 404, (
            f"a reservation with no businessId must be refused on read too, not shown to whichever "
            f"business asks first, got {r.status_code}"
        )
    finally:
        _run(db.reservations.delete_one({"id": untagged_id}))


def test_update_and_delete_reservation_refuse_a_doc_with_no_businessId(client, owner_headers):
    untagged_id = "RES-QUARANTINE-TEST-2"
    _run(db.reservations.insert_one({
        "id": untagged_id, "guestName": "Untagged Legacy Guest 2", "guestPhone": "+61400000901",
        "partySize": 2, "date": "2027-06-15", "time": "19:30", "status": "confirmed", "businessId": None,
    }))
    try:
        upd = req(client, "PUT", f"/api/reservations/{untagged_id}", headers=owner_headers,
                   json={"partySize": 4})
        assert upd.status_code == 404, upd.text[:200]
        deL = req(client, "DELETE", f"/api/reservations/{untagged_id}", headers=owner_headers)
        assert deL.status_code == 404, deL.text[:200]
        still_there = _run(db.reservations.find_one({"id": untagged_id}))
        assert still_there is not None and still_there["partySize"] == 2, (
            "a rejected quarantine mutation must never modify or delete the untagged document"
        )
    finally:
        _run(db.reservations.delete_many({"id": untagged_id}))


def test_waitlist_mutations_refuse_a_doc_with_no_businessId(client, owner_headers):
    untagged_id = "WL-QUARANTINE-TEST-1"
    _run(db.waitlist.insert_one({
        "id": untagged_id, "guestName": "Untagged Legacy Waitlist", "guestPhone": "+61400000902",
        "partySize": 2, "position": 1, "status": "waiting", "businessId": None,
    }))
    try:
        upd = req(client, "PUT", f"/api/waitlist/{untagged_id}", headers=owner_headers,
                   json={"partySize": 3})
        assert upd.status_code == 404, upd.text[:200]
        deL = req(client, "DELETE", f"/api/waitlist/{untagged_id}", headers=owner_headers)
        assert deL.status_code == 404, deL.text[:200]
        still_there = _run(db.waitlist.find_one({"id": untagged_id}))
        assert still_there is not None and still_there["partySize"] == 2
    finally:
        _run(db.waitlist.delete_many({"id": untagged_id}))
