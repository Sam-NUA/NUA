"""routes/auth.py's login/2FA brute-force lockout used to key its counter
on `f"{request.client.host}:{email}"` / `f"2fa:{request.client.host}:{user_id}"`
— looked like a stricter per-IP-per-account guard, but was actually WEAKER
than keying on the account alone. This deployment runs uvicorn with
`--proxy-headers --forwarded-allow-ips '*'` (Dockerfile, railway.json),
so `request.client.host` reflects a caller-supplied X-Forwarded-For
verbatim whenever the container is reachable without a header-stripping
proxy in front of it — reproduced directly against a real uvicorn
instance with these exact flags during the second release-closure pass
(a minimal probe app confirmed `request.client.host` becomes whatever a
plain `curl -H "X-Forwarded-For: <anything>"` sends, with zero proxy in
the loop). Concatenating that spoofable value into the lockout key let an
attacker mint a fresh bucket every single request by rotating the header,
resetting the failed-attempt count to zero each time regardless of the
fixed target email/user_id.

Fixed: the identifier is now the account alone (`acct:{email}` /
`2fa:{user_id}`), so the lockout can no longer be reset by varying a
client-supplied header — the actual code-level guarantee this test
checks. (This sandbox's TestClient doesn't run through uvicorn's real
ProxyHeadersMiddleware, so an end-to-end "attacker rotates a fake IP over
HTTP" exploit can't be reproduced inside this harness — see the
standalone-uvicorn reproduction noted above and in
TRUST_RELEASE_FINAL_REPORT.md instead. This test proves the mechanism
directly and deterministically: the stored identifier has no IP component
at all, and 5 failed attempts locks the account regardless of request
metadata.)
"""
import asyncio

import pyotp
import pytest

from conftest import OWNER, req


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture
def enrolled_2fa(client, owner_headers):
    """Same enrol/teardown pattern as test_two_factor.py's own `enrolled`
    fixture — kept local rather than imported so this file has no ordering
    dependency on that module."""
    setup = req(client, "POST", "/api/auth/2fa/setup", headers=owner_headers, json={}).json()
    totp = pyotp.TOTP(setup["secret"])
    r = req(client, "POST", "/api/auth/2fa/verify", headers=owner_headers, json={"code": totp.now()})
    assert r.status_code == 200, r.text[:200]
    try:
        yield totp
    finally:
        from database import db
        _run(db.auth_users.update_one(
            {"email": OWNER["email"]},
            {"$unset": {"twoFactorSecret": "", "twoFactorEnabled": "",
                       "twoFactorSecretPending": "", "recoveryCodes": "",
                       "twoFactorEnabledAt": ""}}))
        _run(db.trusted_devices.delete_many({}))
        _run(db.settings.delete_one({"key": "two_factor_policy"}))
        client.cookies.clear()


def _cleanup(email):
    from database import db
    _run(db.login_attempts.delete_many({"identifier": {"$regex": email}}))
    _run(db.auth_users.delete_many({"email": email}))


def test_login_lockout_identifier_has_no_ip_component(client, owner_headers):
    email = "bruteforce-lockout-test@nua.com"
    _cleanup(email)
    try:
        r = client.post("/api/auth/register", headers=owner_headers, json={
            "name": "Bruteforce Test", "email": email, "password": "RealPassword2026!",
        })
        assert r.status_code == 200, r.text[:200]
        client.cookies.clear()

        for _ in range(5):
            r = client.post("/api/auth/login", json={"email": email, "password": "wrong-password"})
            assert r.status_code == 401, r.text[:200]

        locked = client.post("/api/auth/login", json={"email": email, "password": "wrong-password"})
        assert locked.status_code == 429, (
            f"5 failed attempts against one account must lock it out, got {locked.status_code}: {locked.text[:200]}"
        )

        from database import db
        stored = _run(db.login_attempts.find_one({"identifier": f"acct:{email}"}, {"_id": 0}))
        assert stored is not None, "the lockout counter must be keyed as 'acct:{email}', with no IP component"
        assert stored.get("count", 0) >= 5

        # A correct password still can't get in while locked — proves the
        # lockout is enforced on the account, not merely counted.
        still_locked = client.post("/api/auth/login", json={"email": email, "password": "RealPassword2026!"})
        assert still_locked.status_code == 429
    finally:
        _cleanup(email)


def test_2fa_challenge_lockout_is_keyed_on_user_id_not_ip(client, owner_headers, enrolled_2fa):
    """Drives a real login -> 2FA challenge flow end to end: 5 wrong TOTP
    codes must lock the challenge out, and the stored lockout counter must
    be keyed purely on user_id (no request.client.host component)."""
    from database import db

    login = client.post("/api/auth/login", json=OWNER)
    assert login.status_code == 200, login.text[:200]
    body = login.json()
    assert body.get("twoFactorRequired") is True
    challenge_token = body["challengeToken"]
    user = _run(db.auth_users.find_one({"email": OWNER["email"]}, {"_id": 0, "id": 1}))
    user_id = user["id"]

    for _ in range(5):
        r = client.post("/api/auth/2fa/challenge", json={"challengeToken": challenge_token, "code": "000000"})
        assert r.status_code == 401, r.text[:200]

    locked = client.post("/api/auth/2fa/challenge", json={"challengeToken": challenge_token, "code": "000000"})
    assert locked.status_code == 429, (
        f"5 wrong codes must lock the 2FA challenge, got {locked.status_code}: {locked.text[:200]}"
    )

    try:
        stored = _run(db.login_attempts.find_one({"identifier": f"2fa:{user_id}"}, {"_id": 0}))
        assert stored is not None, "the 2FA lockout counter must be keyed as '2fa:{user_id}', with no IP component"
        assert stored.get("count", 0) >= 5

        # Even the correct code can't get in while locked.
        still_locked = client.post("/api/auth/2fa/challenge", json={
            "challengeToken": challenge_token, "code": enrolled_2fa.now()})
        assert still_locked.status_code == 429
    finally:
        # This test deliberately locks out the shared OWNER fixture account's
        # 2FA challenge — must clear it, or every later test that logs in as
        # OWNER inherits the lockout.
        _run(db.login_attempts.delete_many({"identifier": f"2fa:{user_id}"}))
