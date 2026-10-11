"""Kitchen docket config used to be one `_id: "singleton"` document shared by
every business on the deployment — one venue's font-size/notes preferences
silently applied to every other venue's kitchen. Now scoped per business via
services.tenant_settings.{get,set}_scoped_singleton, the same helpers
loyalty_config/agent_autonomy already use for this shape.
"""
import uuid

import pytest
from conftest import req
from database import db


@pytest.fixture
def second_business_owner_headers(client):
    """A second, independent business — not the `owner_headers` fixture's
    seeded "default" business — so cross-tenant isolation can be checked."""
    identifier = str(uuid.uuid4())
    pin = "4217"
    doc = {"id": identifier, "email": f"{identifier}@example.com", "name": "Other Venue Owner",
           "role": "owner", "businessId": "other-venue", "status": "active",
           "pin": pin, "password_hash": ""}
    client.portal.call(db.auth_users.insert_one, dict(doc))
    try:
        result = req(client, "POST", "/api/auth/pin-login", json={"pin": pin})
        assert result.status_code == 200, result.text
        yield {"Authorization": f"Bearer {result.json()['token']}"}
    finally:
        client.portal.call(db.auth_users.delete_one, {"id": identifier})


def test_fresh_business_gets_default_config_without_touching_legacy(client, owner_headers):
    client.portal.call(db.kitchen_docket_config.delete_many, {"id": "docket-config", "businessId": "default"})
    response = req(client, "GET", "/api/kitchen/docket-config", headers=owner_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["fontSize"] == "medium"
    stored = client.portal.call(db.kitchen_docket_config.find_one, {"id": "docket-config", "businessId": "default"})
    assert stored is not None
    assert stored["businessId"] == "default"


def test_two_businesses_have_independent_docket_configs(client, owner_headers, second_business_owner_headers):
    client.portal.call(db.kitchen_docket_config.delete_many, {"id": "docket-config"})
    put_a = req(client, "PUT", "/api/kitchen/docket-config", headers=owner_headers, json={"fontSize": "large"})
    assert put_a.status_code == 200, put_a.text
    assert put_a.json()["fontSize"] == "large"

    get_b = req(client, "GET", "/api/kitchen/docket-config", headers=second_business_owner_headers)
    assert get_b.status_code == 200, get_b.text
    assert get_b.json()["fontSize"] == "medium"  # untouched by business A's write

    put_b = req(client, "PUT", "/api/kitchen/docket-config", headers=second_business_owner_headers,
                json={"fontSize": "small"})
    assert put_b.status_code == 200, put_b.text

    get_a_again = req(client, "GET", "/api/kitchen/docket-config", headers=owner_headers)
    assert get_a_again.json()["fontSize"] == "large"  # untouched by business B's write


def _make_rostered_staff_headers(client, pin: str, identifier: str):
    from datetime import datetime, timezone
    today_iso = datetime.now(timezone.utc).date().isoformat()
    client.portal.call(db.roster_overrides.insert_one,
                        {"staffId": identifier, "staffName": "Line cook", "date": today_iso,
                         "businessId": "default", "approvedBy": "test-fixture",
                         "approvedByName": "test-fixture", "approvedAt": today_iso})
    login = req(client, "POST", "/api/auth/pin-login", json={"pin": pin})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['token']}"}


def test_update_docket_config_requires_owner_or_manager(client):
    identifier = str(uuid.uuid4())
    pin = "7731"
    doc = {"id": identifier, "email": f"{identifier}@example.com", "name": "Line cook",
           "role": "staff", "businessId": "default", "status": "active",
           "pin": pin, "password_hash": ""}
    client.portal.call(db.auth_users.insert_one, dict(doc))
    try:
        headers = _make_rostered_staff_headers(client, pin, identifier)
        response = req(client, "PUT", "/api/kitchen/docket-config", headers=headers, json={"fontSize": "large"})
        assert response.status_code == 403
    finally:
        client.portal.call(db.auth_users.delete_one, {"id": identifier})
        client.portal.call(db.roster_overrides.delete_many, {"staffId": identifier})


def test_legacy_singleton_is_reported_but_never_adopted(client, owner_headers):
    client.portal.call(db.kitchen_docket_config.delete_many, {"id": "docket-config", "businessId": "default"})
    client.portal.call(db.kitchen_docket_config.delete_one, {"_id": "singleton"})
    client.portal.call(db.kitchen_docket_config.insert_one,
                        {"_id": "singleton", "fontSize": "large", "updatedBy": "legacy@old-deploy.test"})
    try:
        report = req(client, "GET", "/api/kitchen/docket-config/legacy-singleton-report", headers=owner_headers)
        assert report.status_code == 200, report.text
        body = report.json()
        assert body["exists"] is True
        assert body["legacyConfig"]["fontSize"] == "large"

        # The report must never have assigned the legacy row to this business.
        fresh = req(client, "GET", "/api/kitchen/docket-config", headers=owner_headers)
        assert fresh.json()["fontSize"] == "medium"
        stored = client.portal.call(db.kitchen_docket_config.find_one, {"id": "docket-config", "businessId": "default"})
        assert stored["fontSize"] == "medium"
    finally:
        client.portal.call(db.kitchen_docket_config.delete_one, {"_id": "singleton"})


def test_legacy_singleton_report_requires_owner_or_manager(client):
    identifier = str(uuid.uuid4())
    pin = "9042"
    doc = {"id": identifier, "email": f"{identifier}@example.com", "name": "Line cook 2",
           "role": "staff", "businessId": "default", "status": "active",
           "pin": pin, "password_hash": ""}
    client.portal.call(db.auth_users.insert_one, dict(doc))
    try:
        headers = _make_rostered_staff_headers(client, pin, identifier)
        response = req(client, "GET", "/api/kitchen/docket-config/legacy-singleton-report", headers=headers)
        assert response.status_code == 403
    finally:
        client.portal.call(db.auth_users.delete_one, {"id": identifier})
        client.portal.call(db.roster_overrides.delete_many, {"staffId": identifier})
