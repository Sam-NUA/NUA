"""Device identity (backend/models/device.py, routes/devices.py).

Registration is open to any authenticated staff member (a cashier opening
the app on a new terminal must be able to claim it), but listing/revoking
is owner/manager-only, every read/write is tenant-scoped, and a revoked
device's existing access token is rejected on its very next request — not
just on new logins — via the deviceId-aware check in
RequireAuthMiddleware/get_current_user (server.py / routes/auth.py).
"""
import uuid
from datetime import datetime, timezone

import pytest
from conftest import req
from database import db


@pytest.fixture
def second_business_owner_headers(client):
    identifier = str(uuid.uuid4())
    pin = "6093"
    doc = {"id": identifier, "email": f"{identifier}@example.com", "name": "Other Venue Owner",
           "role": "owner", "businessId": "device-test-other-biz", "status": "active",
           "pin": pin, "password_hash": ""}
    client.portal.call(db.auth_users.insert_one, dict(doc))
    try:
        result = req(client, "POST", "/api/auth/pin-login", json={"pin": pin})
        assert result.status_code == 200, result.text
        yield {"Authorization": f"Bearer {result.json()['token']}"}
    finally:
        client.portal.call(db.auth_users.delete_one, {"id": identifier})
        client.portal.call(db.devices.delete_many, {"businessId": "device-test-other-biz"})


@pytest.fixture(autouse=True)
def _cleanup_default_devices(client):
    yield
    client.portal.call(db.devices.delete_many, {"businessId": "default"})


def test_register_device_requires_only_authentication_not_elevated_role(client):
    identifier = str(uuid.uuid4())
    pin = "7421"
    client.portal.call(db.auth_users.insert_one, {
        "id": identifier, "email": f"{identifier}@example.com", "name": "Cashier",
        "role": "cashier", "businessId": "default", "status": "active",
        "pin": pin, "password_hash": "",
    })
    client.portal.call(db.roster_overrides.insert_one, {
        "staffId": identifier, "staffName": "Cashier", "date": datetime.now(timezone.utc).date().isoformat(),
        "businessId": "default", "approvedBy": "fixture", "approvedByName": "fixture",
        "approvedAt": "2026-01-01T00:00:00+00:00",
    })
    try:
        login = req(client, "POST", "/api/auth/pin-login", json={"pin": pin})
        assert login.status_code == 200, login.text
        headers = {"Authorization": f"Bearer {login.json()['token']}"}

        response = req(client, "POST", "/api/devices/register", headers=headers, json={
            "platform": "android", "deviceName": "Front Counter Tablet",
            "deviceModel": "Pixel Tablet", "osVersion": "14", "appVersion": "1.0.0",
            "capabilities": ["printer.network"],
        })
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["businessId"] == "default"
        assert body["status"] == "active"
        assert body["registeredBy"] == identifier
    finally:
        client.portal.call(db.auth_users.delete_one, {"id": identifier})
        client.portal.call(db.roster_overrides.delete_one, {"staffId": identifier})


def test_register_rejects_invalid_platform(client, owner_headers):
    response = req(client, "POST", "/api/devices/register", headers=owner_headers,
                   json={"platform": "palmos", "deviceName": "Ancient PDA"})
    assert response.status_code == 400


def test_list_and_revoke_require_owner_or_manager(client):
    identifier = str(uuid.uuid4())
    pin = "8512"
    client.portal.call(db.auth_users.insert_one, {
        "id": identifier, "email": f"{identifier}@example.com", "name": "Cashier2",
        "role": "cashier", "businessId": "default", "status": "active",
        "pin": pin, "password_hash": "",
    })
    client.portal.call(db.roster_overrides.insert_one, {
        "staffId": identifier, "staffName": "Cashier2", "date": datetime.now(timezone.utc).date().isoformat(),
        "businessId": "default", "approvedBy": "fixture", "approvedByName": "fixture",
        "approvedAt": "2026-01-01T00:00:00+00:00",
    })
    try:
        login = req(client, "POST", "/api/auth/pin-login", json={"pin": pin})
        headers = {"Authorization": f"Bearer {login.json()['token']}"}
        assert req(client, "GET", "/api/devices", headers=headers).status_code == 403
        assert req(client, "POST", "/api/devices/some-id/revoke", headers=headers).status_code == 403
    finally:
        client.portal.call(db.auth_users.delete_one, {"id": identifier})
        client.portal.call(db.roster_overrides.delete_one, {"staffId": identifier})


def test_devices_are_tenant_isolated(client, owner_headers, second_business_owner_headers):
    reg_a = req(client, "POST", "/api/devices/register", headers=owner_headers,
               json={"platform": "android", "deviceName": "Venue A Tablet"})
    assert reg_a.status_code == 200, reg_a.text
    device_a_id = reg_a.json()["id"]

    # Business B must never see business A's device in its list.
    list_b = req(client, "GET", "/api/devices", headers=second_business_owner_headers)
    assert list_b.status_code == 200
    assert all(d["id"] != device_a_id for d in list_b.json())

    # Business B must not be able to revoke business A's device.
    revoke_cross = req(client, "POST", f"/api/devices/{device_a_id}/revoke", headers=second_business_owner_headers)
    assert revoke_cross.status_code == 404

    stored = client.portal.call(db.devices.find_one, {"id": device_a_id}, {"_id": 0, "status": 1})
    assert stored["status"] == "active", "a cross-tenant revoke attempt must never actually revoke"

    # Business A can revoke its own device.
    revoke_own = req(client, "POST", f"/api/devices/{device_a_id}/revoke", headers=owner_headers)
    assert revoke_own.status_code == 200, revoke_own.text


def test_revoked_device_is_rejected_on_its_very_next_request_not_just_next_login(client, owner_headers):
    """The core guarantee: revocation takes effect on the ALREADY-ISSUED
    token's next request, not only on a future login attempt."""
    reg = req(client, "POST", "/api/devices/register", headers=owner_headers,
             json={"platform": "android", "deviceName": "Soon-To-Be-Stolen Tablet"})
    device_id = reg.json()["id"]

    login = req(client, "POST", "/api/auth/login",
               json={"email": "owner@nua.com", "password": "NuaOwner2026!"},
               headers={"X-Device-Id": device_id})
    assert login.status_code == 200, login.text
    device_bound_headers = {"Authorization": f"Bearer {login.json()['token']}"}

    # The device-bound token works normally before revocation.
    still_good = req(client, "GET", "/api/devices", headers=device_bound_headers)
    assert still_good.status_code == 200, still_good.text

    revoke = req(client, "POST", f"/api/devices/{device_id}/revoke", headers=owner_headers)
    assert revoke.status_code == 200, revoke.text

    # The SAME already-issued access token must now be rejected outright —
    # not after it expires, right now.
    rejected = req(client, "GET", "/api/devices", headers=device_bound_headers)
    assert rejected.status_code == 401, rejected.text


def test_ios_platform_device_registers_and_enforces_revocation_identically_to_android(client, owner_headers):
    """The validation gate (`ALLOWED_PLATFORMS`) already listed "ios" before
    any iOS scaffolding existed, but no test ever exercised it — every other
    test in this file registers "android". This proves the full
    register → device-bound login → revoke → next-request-rejected cycle
    works for "ios" too, since the enforcement code (RequireAuthMiddleware,
    get_current_user) is platform-agnostic by construction and a future
    change that narrowed ALLOWED_PLATFORMS to drop "ios" should fail a test,
    not ship silently."""
    reg = req(client, "POST", "/api/devices/register", headers=owner_headers,
             json={"platform": "ios", "deviceName": "Front Counter iPad", "deviceModel": "iPad Pro"})
    assert reg.status_code == 200, reg.text
    assert reg.json()["platform"] == "ios"
    device_id = reg.json()["id"]

    login = req(client, "POST", "/api/auth/login",
               json={"email": "owner@nua.com", "password": "NuaOwner2026!"},
               headers={"X-Device-Id": device_id})
    assert login.status_code == 200, login.text
    device_bound_headers = {"Authorization": f"Bearer {login.json()['token']}"}

    req(client, "POST", f"/api/devices/{device_id}/revoke", headers=owner_headers)

    rejected = req(client, "GET", "/api/devices", headers=device_bound_headers)
    assert rejected.status_code == 401, rejected.text


def test_login_with_a_revoked_device_id_header_is_rejected_outright(client, owner_headers):
    reg = req(client, "POST", "/api/devices/register", headers=owner_headers,
             json={"platform": "android", "deviceName": "Pre-Revoked Tablet"})
    device_id = reg.json()["id"]
    req(client, "POST", f"/api/devices/{device_id}/revoke", headers=owner_headers)

    login = req(client, "POST", "/api/auth/login",
               json={"email": "owner@nua.com", "password": "NuaOwner2026!"},
               headers={"X-Device-Id": device_id})
    assert login.status_code == 403, login.text


def test_login_with_an_unknown_device_id_header_is_rejected_failclosed(client):
    """An X-Device-Id that doesn't match any registered device is treated
    the same as a revoked one — fail-closed, matching tenant_scope_filter's
    own philosophy elsewhere in this codebase."""
    login = req(client, "POST", "/api/auth/login",
               json={"email": "owner@nua.com", "password": "NuaOwner2026!"},
               headers={"X-Device-Id": "DEV-NEVERREGISTERED"})
    assert login.status_code == 403, login.text


def test_heartbeat_updates_last_seen_and_is_tenant_scoped(client, owner_headers, second_business_owner_headers):
    reg = req(client, "POST", "/api/devices/register", headers=owner_headers,
             json={"platform": "android", "deviceName": "Heartbeat Tablet"})
    device_id = reg.json()["id"]

    cross = req(client, "POST", f"/api/devices/{device_id}/heartbeat", headers=second_business_owner_headers)
    assert cross.status_code == 404

    own = req(client, "POST", f"/api/devices/{device_id}/heartbeat", headers=owner_headers)
    assert own.status_code == 200, own.text
    stored = client.portal.call(db.devices.find_one, {"id": device_id}, {"_id": 0, "lastSeenAt": 1, "createdAt": 1})
    assert stored["lastSeenAt"] >= stored["createdAt"]


def test_refresh_preserves_device_binding_so_revocation_survives_token_refresh(client, owner_headers):
    """A device-bound session that refreshes its access token must still
    carry the SAME deviceId afterward — otherwise revocation would be
    defeated the moment a legitimately-stolen session refreshes."""
    reg = req(client, "POST", "/api/devices/register", headers=owner_headers,
             json={"platform": "android", "deviceName": "Refresh Test Tablet"})
    device_id = reg.json()["id"]

    login = req(client, "POST", "/api/auth/login",
               json={"email": "owner@nua.com", "password": "NuaOwner2026!"},
               headers={"X-Device-Id": device_id})
    assert login.status_code == 200, login.text

    # /auth/refresh reads the refresh_token cookie, not a header or body —
    # the TestClient's cookie jar already carries it from the login call
    # above (req() never touches cookies, only headers).
    refreshed = req(client, "POST", "/api/auth/refresh")
    assert refreshed.status_code == 200, refreshed.text
    new_access_headers = {"Authorization": f"Bearer {refreshed.json()['token']}"}

    req(client, "POST", f"/api/devices/{device_id}/revoke", headers=owner_headers)

    rejected = req(client, "GET", "/api/devices", headers=new_access_headers)
    assert rejected.status_code == 401, (
        "the refreshed token lost its device binding — revocation no longer protects a refreshed session"
    )
