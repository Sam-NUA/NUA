"""Passwordless guest identity (services/guest_session.py, routes/guest_session.py)
— a guest currently re-types their name/phone/email on every surface that asks
(booking, waitlist, online ordering) with nothing carrying over between them.
This generalizes loyalty_v2.py's already-hardened guest OTP flow (texted
one-time code, anti-enumeration, single-use, rate-limited) into a short-lived
session token any guest-facing surface can accept, tested the same way that
flow already is.
"""
import uuid
from unittest.mock import patch

from conftest import req

FIXED_CODE = "445566"


def _request_code(client, phone):
    with patch("routes.guest_session.secrets.randbelow", return_value=int(FIXED_CODE)):
        r = req(client, "POST", "/api/guest/session/request-code", json={"phone": phone})
    assert r.status_code == 200, r.text[:200]
    assert r.json() == {"sent": True}


def test_verify_issues_a_guest_token_and_a_known_profile(client, owner_headers):
    phone = "0470" + str(uuid.uuid4().int)[:6]
    req(client, "POST", "/api/customers", headers=owner_headers, json={
        "name": "Session Test Guest", "email": "session.guest@example.com", "phone": phone})

    _request_code(client, phone)
    r = req(client, "POST", "/api/guest/session/verify", json={"phone": phone, "code": FIXED_CODE, "business": "default"})
    assert r.status_code == 200, r.text[:200]
    body = r.json()
    assert body["token"]
    assert body["phone"] == phone
    assert body["known"] is True
    assert body["name"] == "Session Test Guest"


def test_verify_still_issues_a_token_for_an_unknown_phone(client):
    """A brand-new guest gets a session too — 'known: false' just means
    forms won't prefill, not that verification fails."""
    phone = "0471" + str(uuid.uuid4().int)[:6]
    _request_code(client, phone)
    r = req(client, "POST", "/api/guest/session/verify", json={"phone": phone, "code": FIXED_CODE, "business": "default"})
    assert r.status_code == 200, r.text[:200]
    body = r.json()
    assert body["token"]
    assert body["known"] is False
    assert body["name"] is None


def test_verify_rejects_a_wrong_code(client):
    phone = "0472" + str(uuid.uuid4().int)[:6]
    _request_code(client, phone)
    r = req(client, "POST", "/api/guest/session/verify", json={"phone": phone, "code": "000000"})
    assert r.status_code == 401


def test_verify_code_is_single_use(client):
    phone = "0473" + str(uuid.uuid4().int)[:6]
    _request_code(client, phone)
    first = req(client, "POST", "/api/guest/session/verify", json={"phone": phone, "code": FIXED_CODE, "business": "default"})
    assert first.status_code == 200
    second = req(client, "POST", "/api/guest/session/verify", json={"phone": phone, "code": FIXED_CODE, "business": "default"})
    assert second.status_code == 401


def test_me_endpoint_resolves_from_a_valid_token(client, owner_headers):
    phone = "0474" + str(uuid.uuid4().int)[:6]
    req(client, "POST", "/api/customers", headers=owner_headers, json={
        "name": "Me Endpoint Guest", "email": "me.guest@example.com", "phone": phone})
    _request_code(client, phone)
    token = req(client, "POST", "/api/guest/session/verify",
               json={"phone": phone, "code": FIXED_CODE, "business": "default"}).json()["token"]

    r = req(client, "GET", "/api/guest/session/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text[:200]
    assert r.json()["name"] == "Me Endpoint Guest"


def test_me_endpoint_rejects_a_missing_token(client):
    r = req(client, "GET", "/api/guest/session/me")
    assert r.status_code == 401


def test_me_endpoint_rejects_a_staff_token(client, owner_headers):
    """A guest session and a staff session must never be interchangeable —
    the middleware-level "type must be None/access" check is the first
    line of defense, this proves a staff token doesn't work as a guest
    session credential either, since guest routes decode it themselves."""
    r = req(client, "GET", "/api/guest/session/me", headers=owner_headers)
    assert r.status_code == 401


def test_me_endpoint_rejects_a_garbage_token(client):
    r = req(client, "GET", "/api/guest/session/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert r.status_code == 401


def test_request_code_requires_no_authentication(anon):
    phone = "0475" + str(uuid.uuid4().int)[:6]
    r = req(anon, "POST", "/api/guest/session/request-code", json={"phone": phone})
    assert r.status_code == 200
    assert r.json() == {"sent": True}


def test_request_code_rejects_an_empty_phone(client):
    r = req(client, "POST", "/api/guest/session/request-code", json={"phone": ""})
    assert r.status_code == 400
