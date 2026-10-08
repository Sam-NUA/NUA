import pytest
"""Password reset was half-built and abandoned: ForgotPasswordRequest and
ResetPasswordRequest Pydantic models existed in routes/auth.py with no
endpoint ever using them, no frontend "Forgot password?" link, and a staff
member locked out of their account had no self-service recovery at all.
Built on top of infrastructure that already existed and worked elsewhere
in this file: send_email (utils/notifications.py), hash_password/bcrypt,
and the create_challenge_token/read_challenge_token short-lived-JWT
pattern the 2FA flow already uses.
"""
import asyncio
from datetime import datetime, timedelta, timezone

from conftest import OWNER, req


@pytest.fixture(autouse=True)
def recovery_config(monkeypatch, client):
    monkeypatch.setenv("SENDGRID_API_KEY", "test-only-key")
    monkeypatch.setenv("SENDGRID_FROM_EMAIL", "help@example.com")
    monkeypatch.setenv("FRONTEND_URL", "https://app.example.com")
    from database import db
    client.portal.call(db.login_attempts.delete_many, {})



def test_forgot_password_always_answers_the_same_way(client, monkeypatch):
    """Must not leak whether an email has an account — same response shape
    whether it matches a real user or not."""
    sent = []

    async def fake_send_email(to, subject, body):
        sent.append((to, subject, body))
        return {"channel": "email", "delivered": True, "to": to}

    import utils.notifications
    monkeypatch.setattr(utils.notifications, "send_email", fake_send_email)

    real = req(client, "POST", "/api/auth/forgot-password", json={"email": OWNER["email"]})
    fake = req(client, "POST", "/api/auth/forgot-password", json={"email": "definitely-nobody@nua.com"})

    assert real.status_code == 200
    assert fake.status_code == 200
    assert real.json() == fake.json()
    assert len(sent) == 1, "must only email the address that actually has an account"
    assert sent[0][0] == OWNER["email"]
    assert "reset-password?token=" in sent[0][2]


def test_the_emailed_reset_link_actually_resets_the_password(client, monkeypatch):
    import routes.auth as auth_module

    captured = {}

    async def fake_send_email(to, subject, body):
        captured["body"] = body
        return {"channel": "email", "delivered": True, "to": to}

    import utils.notifications
    monkeypatch.setattr(utils.notifications, "send_email", fake_send_email)

    r = req(client, "POST", "/api/auth/forgot-password", json={"email": OWNER["email"]})
    assert r.status_code == 200
    token = captured["body"].split("token=")[1].split('"')[0]

    reset = req(client, "POST", "/api/auth/reset-password", json={"token": token, "password": "NewOwnerPass1!"})
    assert reset.status_code == 200, reset.text[:200]

    # Old password must no longer work; the new one must.
    old_login = req(client, "POST", "/api/auth/login", json=OWNER)
    assert old_login.status_code == 401

    new_login = req(client, "POST", "/api/auth/login", json={"email": OWNER["email"], "password": "NewOwnerPass1!"})
    assert new_login.status_code == 200

    # Restore the fixture's expected password so other tests relying on
    # OWNER's credentials (the whole suite) keep working.
    loop = asyncio.get_event_loop()
    from database import db
    from routes.auth import hash_password
    loop.run_until_complete(db.auth_users.update_one(
        {"email": OWNER["email"]}, {"$set": {"password_hash": hash_password(OWNER["password"])}}))


def test_a_reset_token_cannot_be_reused_as_a_second_factor_or_access_credential(client, monkeypatch):
    """The challenge-token pattern is purpose-scoped on purpose — a
    password_reset token must not pass as a 2FA challenge token, and (like
    every challenge token) must never work as a Bearer access credential."""
    captured = {}

    async def fake_send_email(to, subject, body):
        captured["body"] = body
        return {"channel": "email", "delivered": True, "to": to}

    import utils.notifications
    monkeypatch.setattr(utils.notifications, "send_email", fake_send_email)

    req(client, "POST", "/api/auth/forgot-password", json={"email": OWNER["email"]})
    token = captured["body"].split("token=")[1].split('"')[0]

    # The session-scoped client keeps the access_token cookie from whatever
    # earlier test last logged in, and get_current_user prefers cookies over
    # the Authorization header — without clearing it, this would "pass" by
    # authenticating on the leftover cookie and never actually exercise the
    # Bearer-token path this test exists to check. Same trap the `anon`
    # fixture in conftest.py exists to document.
    client.cookies.clear()
    me = req(client, "GET", "/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 401

    twofa = req(client, "POST", "/api/auth/2fa/challenge", json={"challengeToken": token, "code": "000000"})
    assert twofa.status_code == 401


@pytest.fixture
def reset_email(monkeypatch):
    tokens = []
    async def send(to, subject, body):
        assert 'href="https://app.example.com/reset-password?token=' in body
        tokens.append(body.split('token=')[1].split('"')[0])
        return {"delivered": True}
    monkeypatch.setattr('utils.notifications.send_email', send)
    return tokens


def test_unconfigured_recovery_is_honest_without_exposing_accounts(anon, monkeypatch):
    monkeypatch.delenv('SENDGRID_API_KEY')
    real = req(anon, 'POST', '/api/auth/forgot-password', json={'email': OWNER['email']})
    missing = req(anon, 'POST', '/api/auth/forgot-password', json={'email': 'missing@example.com'})
    assert real.status_code == missing.status_code == 503
    assert real.json() == missing.json()
    options = req(anon, 'GET', '/api/auth/access-options')
    assert options.status_code == 200
    assert options.json()['emailResetAvailable'] is False
    assert OWNER['email'] not in options.text


@pytest.mark.parametrize('origin', ['', 'http://untrusted.example', 'https://example.com/?redirect=bad', 'https://user:pass@example.com'])
def test_reset_requires_a_canonical_safe_origin(anon, monkeypatch, origin):
    monkeypatch.setenv('FRONTEND_URL', origin)
    assert req(anon, 'POST', '/api/auth/forgot-password', json={'email': OWNER['email']}).status_code == 503


def test_only_latest_link_works_once_and_unlocks_login(anon, reset_email):
    from database import db
    for _ in range(2):
        assert req(anon, 'POST', '/api/auth/forgot-password', json={'email': OWNER['email']}).status_code == 200
    first, latest = reset_email
    assert first != latest
    assert req(anon, 'POST', '/api/auth/reset-password', json={'token': first, 'password': OWNER['password']}).status_code == 400
    assert req(anon, 'POST', '/api/auth/reset-password', json={'token': latest, 'password': 'short'}).status_code == 400
    anon.portal.call(db.login_attempts.insert_one, {'identifier': f"acct:{OWNER['email']}", 'count': 5, 'locked_until': datetime.now(timezone.utc) + timedelta(minutes=15)})
    assert req(anon, 'POST', '/api/auth/reset-password', json={'token': latest, 'password': OWNER['password']}).status_code == 200
    assert req(anon, 'POST', '/api/auth/reset-password', json={'token': latest, 'password': OWNER['password']}).status_code == 400
    assert req(anon, 'POST', '/api/auth/login', json=OWNER).status_code == 200


def test_expired_link_is_rejected(anon, reset_email):
    from database import db
    req(anon, 'POST', '/api/auth/forgot-password', json={'email': OWNER['email']})
    anon.portal.call(db.password_reset_tokens.update_many, {}, {'$set': {'expiresAt': datetime.now(timezone.utc) - timedelta(seconds=1)}})
    assert req(anon, 'POST', '/api/auth/reset-password', json={'token': reset_email[0], 'password': OWNER['password']}).status_code == 400


def test_failed_delivery_cancels_link_and_does_not_expose_account(anon, monkeypatch):
    from database import db
    async def fail(*args):
        return {'delivered': False}
    monkeypatch.setattr('utils.notifications.send_email', fail)
    real = req(anon, 'POST', '/api/auth/forgot-password', json={'email': OWNER['email']})
    missing = req(anon, 'POST', '/api/auth/forgot-password', json={'email': 'missing@example.com'})
    assert real.status_code == missing.status_code == 200
    assert real.json() == missing.json()
    user = anon.portal.call(db.auth_users.find_one, {'email': OWNER['email']})
    assert anon.portal.call(db.password_reset_tokens.find_one, {'_id': user['id']}) is None


def test_password_change_requires_current_password_and_revokes_sessions(anon):
    login = req(anon, 'POST', '/api/auth/login', json=OWNER)
    old_access = login.json()['token']
    old_refresh = anon.cookies.get('refresh_token')
    wrong = req(anon, 'POST', '/api/auth/change-password', json={'currentPassword': 'wrong', 'password': OWNER['password']})
    assert wrong.status_code == 400
    changed = req(anon, 'POST', '/api/auth/change-password', json={'currentPassword': OWNER['password'], 'password': OWNER['password']})
    assert changed.status_code == 200
    anon.cookies.clear()
    headers = {'Authorization': f'Bearer {old_access}'}
    assert req(anon, 'GET', '/api/auth/me', headers=headers).status_code == 401
    assert req(anon, 'GET', '/api/users', headers=headers).status_code == 401
    anon.cookies.set('refresh_token', old_refresh)
    assert req(anon, 'POST', '/api/auth/refresh').status_code == 401
    anon.cookies.clear()
    assert req(anon, 'POST', '/api/auth/login', json=OWNER).status_code == 200


def test_password_change_requires_authentication(anon):
    assert req(anon, 'POST', '/api/auth/change-password', json={'currentPassword': OWNER['password'], 'password': OWNER['password']}).status_code == 401
