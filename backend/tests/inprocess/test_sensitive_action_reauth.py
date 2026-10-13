"""Directive Phase 5 — biometric reauthentication for sensitive actions.

No biometric hardware is integrated on any platform (see
frontend/src/platform/*/BiometricService.js — every platform reports
'unsupported'), so POST /api/auth/verify-sensitive-action is the real,
server-verified fallback every platform actually uses: re-enter a PIN
right before a refund/void/sensitive setting, checked here rather than
trusted client-side. Mirrors approve_pin_login's existing shape.
"""
import uuid
from datetime import datetime, timezone

import pytest
from conftest import req
from database import db


@pytest.fixture
def cashier_headers_and_pin(client):
    identifier = str(uuid.uuid4())
    pin = "4910"
    client.portal.call(db.auth_users.insert_one, {
        "id": identifier, "email": f"{identifier}@example.com", "name": "Reauth Cashier",
        "role": "cashier", "businessId": "default", "status": "active",
        "pin": pin, "password_hash": "",
    })
    client.portal.call(db.roster_overrides.insert_one, {
        "staffId": identifier, "staffName": "Reauth Cashier", "date": datetime.now(timezone.utc).date().isoformat(),
        "businessId": "default", "approvedBy": "fixture", "approvedByName": "fixture",
        "approvedAt": "2026-01-01T00:00:00+00:00",
    })
    try:
        login = req(client, "POST", "/api/auth/pin-login", json={"pin": pin})
        assert login.status_code == 200, login.text
        yield {"Authorization": f"Bearer {login.json()['token']}"}, pin
    finally:
        client.portal.call(db.auth_users.delete_one, {"id": identifier})
        client.portal.call(db.roster_overrides.delete_one, {"staffId": identifier})


@pytest.fixture
def same_business_manager_pin(client):
    identifier = str(uuid.uuid4())
    pin = "6652"
    client.portal.call(db.auth_users.insert_one, {
        "id": identifier, "email": f"{identifier}@example.com", "name": "Reauth Manager",
        "role": "manager", "businessId": "default", "status": "active",
        "pin": pin, "password_hash": "",
    })
    try:
        yield pin
    finally:
        client.portal.call(db.auth_users.delete_one, {"id": identifier})


@pytest.fixture
def second_business_manager_pin(client):
    identifier = str(uuid.uuid4())
    pin = "7731"
    client.portal.call(db.auth_users.insert_one, {
        "id": identifier, "email": f"{identifier}@example.com", "name": "Other Venue Manager",
        "role": "manager", "businessId": "reauth-test-other-biz", "status": "active",
        "pin": pin, "password_hash": "",
    })
    try:
        yield pin
    finally:
        client.portal.call(db.auth_users.delete_one, {"id": identifier})


def test_own_pin_verifies(client, cashier_headers_and_pin):
    headers, pin = cashier_headers_and_pin
    r = req(client, "POST", "/api/auth/verify-sensitive-action", headers=headers, json={"pin": pin})
    assert r.status_code == 200, r.text
    assert r.json()["verified"] is True


def test_manager_pin_from_same_business_approves_on_behalf_of_a_cashier(client, cashier_headers_and_pin, same_business_manager_pin):
    acting_headers, _pin = cashier_headers_and_pin
    r = req(client, "POST", "/api/auth/verify-sensitive-action", headers=acting_headers, json={"pin": same_business_manager_pin})
    assert r.status_code == 200, r.text
    assert r.json()["approvedBy"] == "Reauth Manager"


def test_a_cashier_pin_cannot_approve_on_behalf_of_another_cashier(client, cashier_headers_and_pin):
    acting_headers, _pin = cashier_headers_and_pin
    other_identifier = str(uuid.uuid4())
    other_pin = "2244"
    client.portal.call(db.auth_users.insert_one, {
        "id": other_identifier, "email": f"{other_identifier}@example.com", "name": "Another Cashier",
        "role": "cashier", "businessId": "default", "status": "active",
        "pin": other_pin, "password_hash": "",
    })
    try:
        r = req(client, "POST", "/api/auth/verify-sensitive-action", headers=acting_headers, json={"pin": other_pin})
        assert r.status_code == 403, r.text
    finally:
        client.portal.call(db.auth_users.delete_one, {"id": other_identifier})


def test_pin_from_a_different_business_is_rejected_even_if_manager_there(client, cashier_headers_and_pin, second_business_manager_pin):
    acting_headers, _pin = cashier_headers_and_pin
    r = req(client, "POST", "/api/auth/verify-sensitive-action", headers=acting_headers, json={"pin": second_business_manager_pin})
    assert r.status_code == 403, r.text


def test_unknown_pin_is_rejected(client, cashier_headers_and_pin):
    acting_headers, _pin = cashier_headers_and_pin
    r = req(client, "POST", "/api/auth/verify-sensitive-action", headers=acting_headers, json={"pin": "0000"})
    assert r.status_code == 401, r.text


def test_endpoint_requires_authentication(anon):
    r = req(anon, "POST", "/api/auth/verify-sensitive-action", json={"pin": "1234"})
    assert r.status_code == 401
