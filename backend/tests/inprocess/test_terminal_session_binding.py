"""Real HTTP regressions for first-session binding and tenant-aware login."""
import json
import os
import uuid
import jwt
import pytest
from conftest import req, OWNER
from database import db


@pytest.fixture
def terminal(client, owner_headers):
    result = req(client, "POST", "/api/devices/register", headers=owner_headers,
                 json={"platform": "windows", "deviceName": "Bound terminal"})
    yield result.json()["id"]
    client.portal.call(db.devices.delete_one, {"id": result.json()["id"]})


def sign_in(client, headers=None):
    client.cookies.clear()
    return req(client, "POST", "/api/auth/login", json=OWNER, headers=headers or {})


def test_first_session_binding_revokes_even_the_original_unbound_tokens(client, terminal):
    login = sign_in(client)
    original_access = login.json()["token"]
    original_refresh = client.cookies.get("refresh_token")
    headers = {"Authorization": "Bearer " + original_access}
    bound = req(client, "POST", "/api/auth/bind-device", headers=headers, json={"deviceId": terminal})
    assert bound.status_code == 200, bound.text
    claim = jwt.decode(bound.json()["token"], os.environ["JWT_SECRET"], algorithms=["HS256"])
    assert claim["deviceId"] == terminal
    assert claim["sessionId"]
    client.cookies.set("refresh_token", original_refresh)
    refreshed = req(client, "POST", "/api/auth/refresh")
    assert refreshed.status_code == 200, refreshed.text
    renewed = jwt.decode(refreshed.json()["token"], os.environ["JWT_SECRET"], algorithms=["HS256"])
    assert renewed["deviceId"] == terminal
    assert req(client, "GET", "/api/auth/me", headers=headers).status_code == 200
    assert req(client, "POST", f"/api/devices/{terminal}/revoke", headers=headers).status_code == 200
    client.cookies.clear()
    assert req(client, "GET", "/api/auth/me", headers=headers).status_code == 401
    client.cookies.set("refresh_token", original_refresh)
    assert req(client, "POST", "/api/auth/refresh").status_code == 401
    client.cookies.clear()


def test_session_cannot_be_rebound_to_another_terminal(client, terminal, owner_headers):
    other = req(client, "POST", "/api/devices/register", headers=owner_headers,
                json={"platform": "windows", "deviceName": "Other terminal"}).json()["id"]
    try:
        login = sign_in(client)
        headers = {"Authorization": "Bearer " + login.json()["token"]}
        assert req(client, "POST", "/api/auth/bind-device", headers=headers, json={"deviceId": terminal}).status_code == 200
        assert req(client, "POST", "/api/auth/bind-device", headers=headers, json={"deviceId": other}).status_code == 409
    finally:
        client.portal.call(db.devices.delete_one, {"id": other})
        client.cookies.clear()


@pytest.mark.parametrize("mode", ["password", "pin"])
def test_active_foreign_terminal_does_not_bind_a_login(client, terminal, mode):
    client.portal.call(db.devices.update_one, {"id": terminal}, {"$set": {"businessId": "foreign-venue"}})
    if mode == "password":
        result = sign_in(client, {"X-Device-Id": terminal})
    else:
        staff_id = str(uuid.uuid4())
        client.portal.call(db.auth_users.insert_one, {"id": staff_id, "email": staff_id + "@example.com", "name": "PIN owner",
            "pin": "6197", "role": "owner", "businessId": "default", "status": "active"})
        try:
            result = req(client, "POST", "/api/auth/pin-login", headers={"X-Device-Id": terminal}, json={"pin": "6197"})
        finally:
            client.portal.call(db.auth_users.delete_one, {"id": staff_id})
    assert result.status_code == 403, result.text
    client.cookies.clear()


def test_business_device_map_selects_only_the_authenticated_business(client, terminal):
    headers = {"X-Device-Map": json.dumps({"default": terminal, "other": "DEV-UNTRUSTED-HINT"})}
    good = sign_in(client, headers)
    assert good.status_code == 200, good.text
    payload = jwt.decode(good.json()["token"], os.environ["JWT_SECRET"], algorithms=["HS256"])
    assert payload["deviceId"] == terminal
    client.portal.call(db.devices.update_one, {"id": terminal}, {"$set": {"status": "revoked"}})
    assert sign_in(client, headers).status_code == 403
    new_business = sign_in(client, {"X-Device-Map": json.dumps({"other": terminal})})
    assert new_business.status_code == 200
    payload = jwt.decode(new_business.json()["token"], os.environ["JWT_SECRET"], algorithms=["HS256"])
    assert payload["deviceId"] is None
    client.cookies.clear()


def test_bind_rejects_a_foreign_device_and_legacy_session(client, terminal, owner_headers):
    client.portal.call(db.devices.update_one, {"id": terminal}, {"$set": {"businessId": "foreign-venue"}})
    assert req(client, "POST", "/api/auth/bind-device", headers=owner_headers, json={"deviceId": terminal}).status_code == 403
    from routes.auth import create_access_token
    owner = client.portal.call(db.auth_users.find_one, {"email": OWNER["email"]})
    legacy = create_access_token(owner["id"], owner["email"], owner["role"], owner["businessId"])
    client.cookies.clear()
    result = req(client, "POST", "/api/auth/bind-device", headers={"Authorization": "Bearer " + legacy}, json={"deviceId": terminal})
    assert result.status_code == 409


def test_moving_account_cannot_retarget_its_existing_terminal_session(client, terminal):
    login = sign_in(client)
    headers = {"Authorization": "Bearer " + login.json()["token"]}
    user_id = login.json()["user"]["id"]
    assert req(client, "POST", "/api/auth/bind-device", headers=headers, json={"deviceId": terminal}).status_code == 200
    try:
        client.portal.call(db.auth_users.update_one, {"id": user_id}, {"$set": {"businessId": "moved-business"}})
        assert req(client, "GET", "/api/auth/me", headers=headers).status_code == 401
        assert req(client, "POST", "/api/auth/refresh").status_code == 401
    finally:
        client.portal.call(db.auth_users.update_one, {"id": user_id}, {"$set": {"businessId": "default"}})
        client.cookies.clear()


def test_explicit_bearer_and_middleware_use_the_same_actor_despite_old_cookie(client, owner_headers):
    from routes.auth import create_access_token
    other_id = str(uuid.uuid4())
    client.portal.call(db.auth_users.insert_one, {"id": other_id, "email": other_id + "@example.com",
        "role": "owner", "businessId": "cookie-other-business", "status": "active"})
    try:
        cookie = create_access_token(other_id, other_id + "@example.com", "owner", "cookie-other-business")
        client.cookies.set("access_token", cookie)
        result = req(client, "GET", "/api/auth/me", headers=owner_headers)
        assert result.status_code == 200, result.text
        assert result.json()["businessId"] == "default"
    finally:
        client.cookies.clear()
        client.portal.call(db.auth_users.delete_one, {"id": other_id})
