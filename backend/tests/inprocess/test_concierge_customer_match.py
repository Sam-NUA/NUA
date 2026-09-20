"""AI Concierge / Bookings Inbox must check the customer database before
creating a reservation, instead of booking every guest as a stranger.

Both routes call the same LLM "extract structured info from free text"
step, which this sandbox can't exercise for real (no EMERGENT_LLM_KEY), so
each test monkeypatches the extraction step to a fixed result — the thing
under test is what happens *after* extraction: does it look the guest up
against db.customers and carry their history into the reservation.
"""
import asyncio

from conftest import req


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ------------------------------------------------------------- AI Concierge

def test_concierge_reservation_matches_an_existing_customer_by_phone(client, owner_headers, monkeypatch):
    import routes.v25_suite as v25
    from database import db

    async def fake_llm_json(session_id, system, user_text, model="gpt-5.2"):
        return {
            "intent": "reservation", "date": "2026-08-20", "time": "19:30",
            "partySize": 4, "name": "Alex Chen", "phone": "0412 345 678",
            "notes": "window seat please", "reply": "You're all set, Alex.",
        }
    monkeypatch.setattr(v25, "_llm_json", fake_llm_json)

    _run(db.customers.insert_one({"businessId": "default",
        "id": "CUST-MATCH-1", "name": "Alexander Chen", "email": "alex@example.com",
        "phone": "+61412345678", "isVip": True, "allergies": ["peanuts"], "visits": 12,
    }))
    try:
        r = req(client, "POST", "/api/v25/concierge", headers=owner_headers,
                json={"message": "Table for 4 tonight at 7:30, Alex Chen, 0412 345 678"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["created"] is True
        assert body["matchedCustomer"]["id"] == "CUST-MATCH-1"
        assert body["matchedCustomer"]["isVip"] is True

        res = _run(db.reservations.find_one({"id": body["reservationId"]}, {"_id": 0}))
        assert res["customerId"] == "CUST-MATCH-1"
        assert "peanuts" in res["notes"]
        assert "VIP" in res["notes"]
    finally:
        _run(db.customers.delete_one({"id": "CUST-MATCH-1"}))
        _run(db.reservations.delete_many({"guestPhone": "0412 345 678"}))


def test_concierge_reservation_has_no_customer_id_when_nobody_matches(client, owner_headers, monkeypatch):
    import routes.v25_suite as v25
    from database import db

    async def fake_llm_json(session_id, system, user_text, model="gpt-5.2"):
        return {
            "intent": "reservation", "date": "2026-08-21", "time": "18:00",
            "partySize": 2, "name": "Totally New Guest", "phone": "0499 000 000",
            "notes": "", "reply": "Booked.",
        }
    monkeypatch.setattr(v25, "_llm_json", fake_llm_json)

    r = req(client, "POST", "/api/v25/concierge", headers=owner_headers,
            json={"message": "Table for 2 tomorrow at 6, new guest, 0499 000 000"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] is True
    assert body["matchedCustomer"] is None

    res = _run(db.reservations.find_one({"id": body["reservationId"]}, {"_id": 0}))
    assert res.get("customerId") is None
    _run(db.reservations.delete_one({"id": body["reservationId"]}))


# ------------------------------------------------------------- Bookings Inbox

def test_bookings_inbox_conversion_matches_an_existing_customer(client, owner_headers, monkeypatch):
    import routes.bookings_inbox as inbox
    from database import db

    async def fake_ai_parse(message, channel):
        parsed = {"date": "2026-08-22", "time": "20:00", "partySize": 3,
                  "name": "Jordan Lee", "phone": "0455 111 222", "notes": "birthday"}
        return parsed, "summary", "reply", False
    monkeypatch.setattr(inbox, "_ai_parse", fake_ai_parse)

    _run(db.customers.insert_one({"businessId": "default",
        "id": "CUST-MATCH-2", "name": "Jordan Lee", "email": "jordan@example.com",
        "phone": "+61455111222", "membershipTier": "Gold", "seatingPreference": "booth",
    }))
    try:
        ingest = req(client, "POST", "/api/bookings/inbox", headers=owner_headers,
                     json={"channel": "sms", "rawMessage": "table for 3 at 8pm, Jordan Lee, 0455 111 222"})
        assert ingest.status_code == 200, ingest.text
        item_id = ingest.json()["id"]

        ack = req(client, "POST", f"/api/bookings/inbox/{item_id}/ack", headers=owner_headers,
                  json={"convertToReservation": True})
        assert ack.status_code == 200, ack.text
        reservation_id = ack.json()["reservationId"]

        res = _run(db.reservations.find_one({"id": reservation_id}, {"_id": 0}))
        assert res["customerId"] == "CUST-MATCH-2"
        assert "booth" in res["notes"]
        assert "Gold" in res["notes"]
    finally:
        _run(db.customers.delete_one({"id": "CUST-MATCH-2"}))
        _run(db.booking_inbox.delete_many({"fromHandle": None, "channel": "sms"}))


# ------------------------------------------------------- customer_match unit

def test_find_matching_customer_matches_on_phone_tail_regardless_of_formatting():
    from services.customer_match import find_matching_customer
    from database import db

    _run(db.customers.insert_one({"businessId": "default", "id": "CUST-TAIL-1", "name": "Sam Rivera",
                                   "email": "sam@example.com", "phone": "0412 999 000"}))
    try:
        match = _run(find_matching_customer(phone="+61 412 999 000", business_id="default"))
        assert match is not None
        assert match["id"] == "CUST-TAIL-1"
    finally:
        _run(db.customers.delete_one({"id": "CUST-TAIL-1"}))


def test_guest_context_summarizes_vip_and_allergies():
    from services.customer_match import guest_context
    text = guest_context({"isVip": True, "allergies": ["shellfish"], "visits": 5})
    assert "VIP" in text and "shellfish" in text and "5" in text
