"""Native binding must issue refresh cookies for both password and PIN sessions."""
import os
import uuid
from datetime import datetime, timezone

import jwt
import pytest

from conftest import req
from database import db


@pytest.fixture
def pin_terminal(client, owner_headers):
    uid = str(uuid.uuid4())
    # Isolated test account; no credential fallback is added to application code.
    pin = next(str(p) for p in range(9400, 9500)
               if not client.portal.call(db.auth_users.find_one, {'pin': str(p)}))
    client.portal.call(db.auth_users.insert_one, {
        'id': uid, 'email': uid + '@example.com', 'name': 'Refresh fixture',
        'businessId': 'default', 'role': 'owner', 'status': 'active', 'pin': pin})
    registered = req(client, 'POST', '/api/devices/register', headers=owner_headers,
                     json={'platform': 'ios', 'deviceName': 'Refresh fixture'})
    assert registered.status_code == 200, registered.text
    device_id = registered.json()['id']
    client.cookies.clear()
    try:
        login = req(client, 'POST', '/api/auth/pin-login', json={'pin': pin})
        assert login.status_code == 200, login.text
        headers = {'Authorization': 'Bearer ' + login.json()['token']}
        bound = req(client, 'POST', '/api/auth/bind-device', headers=headers, json={'deviceId': device_id})
        assert bound.status_code == 200, bound.text
        yield bound, device_id, uid
    finally:
        client.cookies.clear()
        client.portal.call(db.auth_users.delete_one, {'id': uid})
        client.portal.call(db.devices.delete_one, {'id': device_id})
        client.portal.call(db.terminal_sessions.delete_many, {'userId': uid})


def claims(token):
    return jwt.decode(token, os.environ['JWT_SECRET'], algorithms=['HS256'])


def test_pin_binding_refresh_preserves_exact_session_and_expires_access_independently(client, pin_terminal):
    bound, device_id, uid = pin_terminal
    access = claims(bound.json()['token'])
    refresh_cookie = client.cookies.get('refresh_token')
    refresh = claims(refresh_cookie)
    for key in ('sub', 'sessionId', 'deviceId'):
        assert refresh[key] == access[key]
    assert refresh['deviceId'] == device_id and refresh['sub'] == uid
    assert 'refresh_token' not in bound.json()
    expired = {**access, 'exp': datetime.now(timezone.utc).timestamp() - 60}
    expired_token = jwt.encode(expired, os.environ['JWT_SECRET'], algorithm='HS256')
    assert req(client, 'GET', '/api/auth/me', headers={'Authorization': 'Bearer ' + expired_token}).status_code == 401
    renewed = req(client, 'POST', '/api/auth/refresh')
    assert renewed.status_code == 200, renewed.text
    new_claims = claims(renewed.json()['token'])
    for key in ('sub', 'businessId', 'deviceId', 'sessionId'):
        assert new_claims[key] == access[key]
    assert req(client, 'GET', '/api/auth/me', headers={'Authorization': 'Bearer ' + renewed.json()['token']}).status_code == 200


def test_native_refresh_cookie_cannot_survive_revocation_or_logout(client, owner_headers, pin_terminal):
    bound, device_id, _ = pin_terminal
    cookie = client.cookies.get('refresh_token')
    assert req(client, 'POST', '/api/auth/refresh').status_code == 200
    assert req(client, 'POST', f'/api/devices/{device_id}/revoke', headers=owner_headers).status_code == 200
    client.cookies.clear()
    client.cookies.set('refresh_token', cookie)
    assert req(client, 'POST', '/api/auth/refresh').status_code == 401
    assert req(client, 'POST', '/api/auth/logout').status_code == 200
    assert client.cookies.get('refresh_token') is None
    assert req(client, 'POST', '/api/auth/refresh').status_code == 401


def test_binding_cookie_security_attributes_stay_http_only_and_lax(client, pin_terminal):
    bound, _, _ = pin_terminal
    cookies = bound.headers.get_list('set-cookie')
    assert len(cookies) == 2
    for cookie in cookies:
        assert 'HttpOnly' in cookie and 'SameSite=lax' in cookie and 'Path=/' in cookie
