"""routes/bookings_inbox.py's AI Bookings Inbox had no route-level auth at
all on any of its 4 endpoints (list/ingest were reachable with zero auth
dependency, and ack's own manual auth check silently proceeded as
"system" instead of rejecting the request when it failed) and zero
businessId scoping. Every business's inbound booking DMs/calls/emails —
customer names, phone numbers, raw message content — were readable and
actionable by any staff member of any other business.
"""
import asyncio

from database import db
from tests.inprocess.conftest import req


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _login_as(client, owner_headers, *, email, business_id):
    client.post("/api/auth/register", headers=owner_headers, json={
        "name": "Bookings Inbox Test Owner", "email": email, "password": "BookingsInboxTenantTest2026!",
    })
    _run(db.auth_users.update_one({"email": email}, {"$set": {"role": "owner", "businessId": business_id}}))
    r = client.post("/api/auth/login", json={"email": email, "password": "BookingsInboxTenantTest2026!"})
    assert r.status_code == 200, f"login failed: {r.text[:200]}"
    client.cookies.clear()
    body = r.json()
    return {"Authorization": f"Bearer {body['token']}"}


def test_a_different_businesss_inbox_item_is_not_visible_or_actionable(client, owner_headers):
    other = _login_as(client, owner_headers, email="bookinginbox.other@nua.com", business_id="bookinginbox-other-biz")

    ingested = req(client, "POST", "/api/bookings/inbox", headers=other, json={
        "channel": "sms", "rawMessage": "Table for 4 tonight please, secret phone 0400999888", "fromHandle": "+61400999888"})
    assert ingested.status_code == 200, ingested.text[:200]
    item_id = ingested.json()["id"]
    try:
        mine = req(client, "GET", "/api/bookings/inbox", headers=owner_headers).json()
        assert not any(i["id"] == item_id for i in mine), "another business's inbox item must not appear in this business's inbox"

        ack_mine = req(client, "POST", f"/api/bookings/inbox/{item_id}/ack", headers=owner_headers,
                        json={"convertToReservation": False})
        assert ack_mine.status_code == 404

        dismiss_mine = req(client, "POST", f"/api/bookings/inbox/{item_id}/dismiss", headers=owner_headers)
        assert dismiss_mine.status_code == 404

        theirs = req(client, "GET", "/api/bookings/inbox", headers=other).json()
        found = next(i for i in theirs if i["id"] == item_id)
        assert found["status"] == "new", "cross-tenant ack/dismiss attempts must not have mutated another business's item"

        anon_list = req(client, "GET", "/api/bookings/inbox").status_code
        assert anon_list in (401, 403), "the inbox must never be reachable with no credential at all"

        anon_ack = req(client, "POST", f"/api/bookings/inbox/{item_id}/ack", json={})
        assert anon_ack.status_code in (401, 403), "ack must reject an unauthenticated caller, not silently proceed as 'system'"
    finally:
        _run(db.booking_inbox.delete_one({"id": item_id}))
