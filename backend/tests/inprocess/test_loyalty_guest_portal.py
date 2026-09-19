"""POST /loyalty/v2/guest-lookup — a customer checking their own points/tier
by phone, with no staff login. Unauthenticated by design (same posture as
/vouchers/public-check): returns first name only, never the full customer
record, and a phone that matches nothing looks the same as a genuine miss.

Gated by a texted one-time code (/guest-lookup/request-code) — knowing a
phone number is no longer enough to see the account behind it, the caller
has to prove they hold the phone. Tests pin the "random" code via a patched
secrets.randbelow rather than reading it from a real SMS, since there's no
provider configured in the test env.
"""
import asyncio
import uuid
from unittest.mock import patch

from conftest import req

FIXED_CODE = "123456"


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _request_code(client, phone):
    with patch("routes.loyalty_v2.secrets.randbelow", return_value=int(FIXED_CODE)):
        r = req(client, "POST", "/api/loyalty/v2/guest-lookup/request-code", json={"phone": phone})
    assert r.status_code == 200, r.text[:200]
    assert r.json() == {"sent": True}


def test_guest_lookup_finds_a_real_customer_by_phone(client, owner_headers):
    from database import db

    cust_id = str(uuid.uuid4())
    phone = "04" + str(uuid.uuid4().int)[:8]
    _run(db.customers.delete_many({"id": cust_id}))
    _run(db.customers.insert_one({
        "id": cust_id, "businessId": "default", "name": "Priya Sharma", "email": "priya@test.com",
        "phone": phone, "points": 250, "visits": 4, "totalSpent": 120.0,
    }))

    _request_code(client, phone)
    r = req(client, "POST", "/api/loyalty/v2/guest-lookup", json={"phone": phone, "code": FIXED_CODE, "business": "default"})
    assert r.status_code == 200, r.text[:200]
    body = r.json()
    assert body["found"] is True
    assert body["firstName"] == "Priya"
    assert body["points"] == 250
    assert "email" not in body
    assert "phone" not in body
    assert "customerId" not in body


def test_guest_lookup_on_an_unknown_phone_returns_a_generic_miss(client):
    nonexistent_phone = "09" + str(uuid.uuid4().int)[:9]
    _request_code(client, nonexistent_phone)
    r = req(client, "POST", "/api/loyalty/v2/guest-lookup", json={"phone": nonexistent_phone, "code": FIXED_CODE, "business": "default"})
    assert r.status_code == 200, r.text[:200]
    assert r.json() == {"found": False}


def test_guest_lookup_requires_no_authentication(anon):
    phone = "0400" + str(uuid.uuid4().int)[:6]
    _request_code(anon, phone)
    r = req(anon, "POST", "/api/loyalty/v2/guest-lookup", json={"phone": phone, "code": FIXED_CODE, "business": "default"})
    assert r.status_code == 200, r.text[:200]


def test_guest_lookup_rejects_an_empty_phone(client):
    r = req(client, "POST", "/api/loyalty/v2/guest-lookup", json={"phone": "", "code": "123456"})
    assert r.status_code == 400


def test_guest_lookup_rejects_a_wrong_code(client):
    phone = "0411" + str(uuid.uuid4().int)[:6]
    _request_code(client, phone)
    r = req(client, "POST", "/api/loyalty/v2/guest-lookup", json={"phone": phone, "code": "000000"})
    assert r.status_code == 401, r.text[:200]


def test_guest_lookup_rejects_missing_code(client):
    phone = "0422" + str(uuid.uuid4().int)[:6]
    _request_code(client, phone)
    r = req(client, "POST", "/api/loyalty/v2/guest-lookup", json={"phone": phone})
    assert r.status_code == 400


def test_guest_lookup_without_requesting_a_code_first_is_rejected(client):
    phone = "0433" + str(uuid.uuid4().int)[:6]
    r = req(client, "POST", "/api/loyalty/v2/guest-lookup", json={"phone": phone, "code": "123456"})
    assert r.status_code == 401, r.text[:200]


def test_guest_lookup_code_is_single_use(client):
    from database import db

    cust_id = str(uuid.uuid4())
    phone = "0444" + str(uuid.uuid4().int)[:6]
    _run(db.customers.delete_many({"id": cust_id}))
    _run(db.customers.insert_one({
        "id": cust_id, "businessId": "default", "name": "Sam Lee", "phone": phone, "points": 10, "visits": 1,
    }))
    _request_code(client, phone)
    first = req(client, "POST", "/api/loyalty/v2/guest-lookup", json={"phone": phone, "code": FIXED_CODE, "business": "default"})
    assert first.status_code == 200
    second = req(client, "POST", "/api/loyalty/v2/guest-lookup", json={"phone": phone, "code": FIXED_CODE, "business": "default"})
    assert second.status_code == 401, second.text[:200]


def test_guest_lookup_request_code_requires_no_authentication(anon):
    phone = "0455" + str(uuid.uuid4().int)[:6]
    r = req(anon, "POST", "/api/loyalty/v2/guest-lookup/request-code", json={"phone": phone})
    assert r.status_code == 200, r.text[:200]
    assert r.json() == {"sent": True}


def test_guest_lookup_request_code_rejects_an_empty_phone(client):
    r = req(client, "POST", "/api/loyalty/v2/guest-lookup/request-code", json={"phone": ""})
    assert r.status_code == 400
