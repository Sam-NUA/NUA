"""Launch regressions: usable post-recovery PIN tokens and tenant boundaries."""
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from conftest import req
from database import db


@pytest.fixture
def account(client):
    identifier = str(uuid.uuid4())
    doc = {"id": identifier, "email": f"{identifier}@example.com", "name": "Audit owner",
           "role": "owner", "businessId": "launch-audit", "status": "active",
           "pin": "9638", "password_hash": "", "twoFactorSecretPending": "test-enrolment-material"}
    client.portal.call(db.auth_users.insert_one, dict(doc))
    yield doc
    client.portal.call(db.auth_users.delete_one, {"id": identifier})
    client.portal.call(db.roster_overrides.delete_many, {"businessId": "launch-audit"})


def test_new_pin_token_works_after_password_change_and_old_one_is_revoked(client, account):
    first = req(client, "POST", "/api/auth/pin-login", json={"pin": account["pin"]}).json()
    changed = datetime.now(timezone.utc).isoformat()
    client.portal.call(db.auth_users.update_one, {"id": account["id"]}, {"$set": {"passwordChangedAt": changed}})
    old = {"Authorization": f"Bearer {first['token']}"}
    assert req(client, "GET", "/api/auth/me", headers=old).status_code == 401
    result = req(client, "POST", "/api/auth/pin-login", json={"pin": account["pin"]})
    assert result.status_code == 200, result.text
    body = result.json()
    headers = {"Authorization": f"Bearer {body['token']}"}
    me = req(client, "GET", "/api/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    for profile in (body["user"], me.json()):
        assert not {"pin", "password_hash", "twoFactorSecret", "twoFactorSecretPending", "recoveryCodes"} & profile.keys()
        assert "permissions" in profile


def test_pin_cannot_bypass_enrolled_second_factor(client, account):
    client.portal.call(db.auth_users.update_one, {"id": account["id"]}, {"$set": {"twoFactorEnabled": True}})
    response = req(client, "POST", "/api/auth/pin-login", json={"pin": account["pin"]})
    assert response.status_code == 403
    assert "email sign-in" in response.json()["detail"]
    assert "token" not in response.json()


def test_pin_cannot_bypass_venue_second_factor_policy(client, account, monkeypatch):
    from services import two_factor
    async def policy(_business_id=None):
        return {"required": True, "roles": ["owner"]}
    monkeypatch.setattr(two_factor, "policy", policy)
    assert req(client, "POST", "/api/auth/pin-login", json={"pin": account["pin"]}).status_code == 403


@pytest.mark.parametrize("protected_role", ["staff", "manager"])
def test_pin_approval_checks_both_second_factors_before_writing_override(client, account, protected_role):
    manager_id = str(uuid.uuid4())
    client.portal.call(db.auth_users.update_one, {"id": account["id"]}, {"$set": {
        "role": "cashier", "twoFactorEnabled": protected_role == "staff"}})
    client.portal.call(db.auth_users.insert_one, {
        "id": manager_id, "email": f"{manager_id}@example.com", "name": "Approver",
        "role": "manager", "businessId": account["businessId"], "status": "active",
        "pin": "9639", "twoFactorEnabled": protected_role == "manager"})
    try:
        response = req(client, "POST", "/api/auth/pin-login/approve", json={"staffPin": "9638", "managerPin": "9639"})
        assert response.status_code == 403
        assert client.portal.call(db.roster_overrides.count_documents, {"staffId": account["id"]}) == 0
    finally:
        client.portal.call(db.auth_users.delete_one, {"id": manager_id})


@pytest.mark.parametrize("business_id", ["other-venue", None])
def test_kitchen_rejects_foreign_and_unowned_reservations(client, owner_headers, business_id):
    rid = str(uuid.uuid4())
    client.portal.call(db.reservations.insert_one, {"id": rid, "businessId": business_id,
                                                  "guestName": "Private guest", "partySize": 9})
    try:
        response = req(client, "POST", "/api/kitchen/orders", headers=owner_headers,
                       json={"reservationId": rid, "covers": 2, "items": []})
        assert response.status_code == 404
        assert client.portal.call(db.kitchen_orders.count_documents, {"reservationId": rid}) == 0
    finally:
        client.portal.call(db.reservations.delete_one, {"id": rid})


def test_kitchen_enriches_own_reservation(client, owner_headers):
    rid = str(uuid.uuid4())
    client.portal.call(db.reservations.insert_one, {"id": rid, "businessId": "default",
                                                  "guestName": "Own guest", "partySize": 3})
    try:
        response = req(client, "POST", "/api/kitchen/orders", headers=owner_headers,
                       json={"reservationId": rid, "items": []})
        assert response.status_code == 200, response.text
        assert response.json()["guestName"] == "Own guest"
        assert response.json()["covers"] == 3
    finally:
        client.portal.call(db.reservations.delete_one, {"id": rid})
        client.portal.call(db.kitchen_orders.delete_many, {"reservationId": rid})


def test_bulk_price_write_cannot_update_another_tenants_duplicate_id(client, owner_headers):
    pid = str(uuid.uuid4())
    # Foreign row first: an id-only update would modify it despite a scoped read.
    client.portal.call(db.products.insert_one, {"id": pid, "businessId": "other-venue", "price": 99})
    client.portal.call(db.products.insert_one, {"id": pid, "businessId": "default", "price": 10})
    try:
        response = req(client, "POST", "/api/products/bulk-edit", headers=owner_headers,
                       json={"productIds": [pid], "pricePercentDelta": 10})
        assert response.status_code == 200, response.text
        assert client.portal.call(db.products.find_one, {"id": pid, "businessId": "other-venue"})["price"] == 99
        assert client.portal.call(db.products.find_one, {"id": pid, "businessId": "default"})["price"] == 11
    finally:
        client.portal.call(db.products.delete_many, {"id": pid})
