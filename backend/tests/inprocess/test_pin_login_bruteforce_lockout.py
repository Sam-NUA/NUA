"""routes/staff_management.py's /auth/pin-login and /auth/pin-login/approve
had no brute-force throttling of their own — only the generic 120/min-per-IP
default (server.py's RateLimitMiddleware). A 2-4 digit PIN has at most
10,000 possible values, so that default left enough headroom to sweep a
meaningful slice of the PIN space well before any per-account lockout (the
kind routes/auth.py's password/2FA login already has) would ever trigger.
Fixed with the same account-keyed lockout shape, keyed on the PIN value
itself since there's no account to key on until a PIN actually matches one.
"""
import uuid

import pytest
from conftest import req
from database import db


@pytest.fixture
def account(client):
    identifier = str(uuid.uuid4())
    pin = "8102"
    doc = {"id": identifier, "email": f"{identifier}@example.com", "name": "Lockout test owner",
           "role": "owner", "businessId": "pin-lockout-biz", "status": "active",
           "pin": pin, "password_hash": ""}
    client.portal.call(db.auth_users.insert_one, dict(doc))
    yield doc
    client.portal.call(db.auth_users.delete_one, {"id": identifier})
    client.portal.call(db.login_attempts.delete_many, {"identifier": f"pin:{pin}"})


def test_pin_login_locks_out_after_five_wrong_attempts_with_the_same_pin(client, account):
    wrong_pin = "0000"
    assert wrong_pin != account["pin"]
    client.portal.call(db.login_attempts.delete_many, {"identifier": f"pin:{wrong_pin}"})
    try:
        for i in range(5):
            r = req(client, "POST", "/api/auth/pin-login", json={"pin": wrong_pin})
            assert r.status_code == 401, f"attempt {i} should be a plain invalid-PIN rejection"
        locked = req(client, "POST", "/api/auth/pin-login", json={"pin": wrong_pin})
        assert locked.status_code == 429, locked.text[:200]
    finally:
        client.portal.call(db.login_attempts.delete_many, {"identifier": f"pin:{wrong_pin}"})


def test_a_correct_pin_is_never_locked_out_by_unrelated_wrong_guesses(client, account):
    other_wrong_pin = "1111"
    client.portal.call(db.login_attempts.delete_many, {"identifier": f"pin:{other_wrong_pin}"})
    try:
        for _ in range(4):
            r = req(client, "POST", "/api/auth/pin-login", json={"pin": other_wrong_pin})
            assert r.status_code == 401

        ok = req(client, "POST", "/api/auth/pin-login", json={"pin": account["pin"]})
        assert ok.status_code == 200, ok.text[:200]
    finally:
        client.portal.call(db.login_attempts.delete_many, {"identifier": f"pin:{other_wrong_pin}"})


def test_successful_pin_login_clears_that_pins_own_failure_count(client, account):
    wrong_pin = "2222"
    assert wrong_pin != account["pin"]
    client.portal.call(db.login_attempts.delete_many, {"identifier": f"pin:{wrong_pin}"})
    try:
        for _ in range(4):
            r = req(client, "POST", "/api/auth/pin-login", json={"pin": wrong_pin})
            assert r.status_code == 401
    finally:
        client.portal.call(db.login_attempts.delete_many, {"identifier": f"pin:{wrong_pin}"})

    ok = req(client, "POST", "/api/auth/pin-login", json={"pin": account["pin"]})
    assert ok.status_code == 200, ok.text[:200]

    row = client.portal.call(db.login_attempts.find_one, {"identifier": f"pin:{account['pin']}"})
    assert row is None, "a successful match must clear any failure count recorded against that exact PIN"
