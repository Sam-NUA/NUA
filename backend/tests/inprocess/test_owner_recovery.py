"""Owner recovery: the operator-only, last-resort path to restore owner
access when the password is wrong/forgotten and email delivery isn't
configured. Gated entirely on OWNER_RECOVERY_KEY, never on a user token.
"""
from conftest import OWNER, req


RECOVERY_KEY = "test-only-owner-recovery-key"


def _clear_recovery_lock():
    from database import db
    import asyncio
    asyncio.get_event_loop().run_until_complete(
        db.login_attempts.delete_one({"identifier": "owner-recovery"}))


def test_wrong_recovery_key_is_rejected_and_locked_after_five_attempts(anon):
    try:
        for _ in range(5):
            r = req(anon, "POST", "/api/auth/owner-recovery/initiate",
                    json={"recoveryKey": "not-the-key", "email": OWNER["email"]})
            assert r.status_code == 401
        locked = req(anon, "POST", "/api/auth/owner-recovery/initiate",
                     json={"recoveryKey": "not-the-key", "email": OWNER["email"]})
        assert locked.status_code == 429
        # Even the correct key is locked out during the bucket's window — this
        # is a shared bucket, not a per-attempt check, by design (see auth.py).
        still_locked = req(anon, "POST", "/api/auth/owner-recovery/initiate",
                           json={"recoveryKey": RECOVERY_KEY, "email": OWNER["email"]})
        assert still_locked.status_code == 429
    finally:
        # This test deliberately locks the single shared recovery bucket —
        # must clear it, or every later test in this file inherits the lockout.
        _clear_recovery_lock()


def test_correct_key_wrong_target_email_is_rejected(anon):
    r = req(anon, "POST", "/api/auth/owner-recovery/initiate",
            json={"recoveryKey": RECOVERY_KEY, "email": "someone-else@nua-recovery-test.com"})
    assert r.status_code == 409


def test_full_recovery_flow_resets_owner_password_and_token_is_single_use(anon):
    initiate = req(anon, "POST", "/api/auth/owner-recovery/initiate",
                   json={"recoveryKey": RECOVERY_KEY, "email": OWNER["email"]})
    assert initiate.status_code == 200, initiate.text
    token = initiate.json()["token"]
    assert token

    complete = req(anon, "POST", "/api/auth/owner-recovery/complete",
                   json={"token": token, "password": "BrandNewOwnerPass2026!"})
    assert complete.status_code == 200, complete.text

    login_new = req(anon, "POST", "/api/auth/login",
                    json={"email": OWNER["email"], "password": "BrandNewOwnerPass2026!"})
    assert login_new.status_code == 200
    assert login_new.json()["user"]["role"] == "owner"

    login_old = req(anon, "POST", "/api/auth/login", json=OWNER)
    assert login_old.status_code == 401

    replay = req(anon, "POST", "/api/auth/owner-recovery/complete",
                json={"token": token, "password": "AnotherAttempt2026!"})
    assert replay.status_code == 400

    # Restore the fixture-wide owner password so later tests in the same
    # session that rely on OWNER still log in.
    restore = req(anon, "POST", "/api/auth/owner-recovery/initiate",
                  json={"recoveryKey": RECOVERY_KEY, "email": OWNER["email"]})
    restore_token = restore.json()["token"]
    req(anon, "POST", "/api/auth/owner-recovery/complete",
        json={"token": restore_token, "password": OWNER["password"]})


def test_complete_rejects_short_password(anon):
    initiate = req(anon, "POST", "/api/auth/owner-recovery/initiate",
                   json={"recoveryKey": RECOVERY_KEY, "email": OWNER["email"]})
    token = initiate.json()["token"]
    r = req(anon, "POST", "/api/auth/owner-recovery/complete", json={"token": token, "password": "short"})
    assert r.status_code == 400

    # The rejected short password must not have consumed the token.
    ok = req(anon, "POST", "/api/auth/owner-recovery/complete",
            json={"token": token, "password": OWNER["password"]})
    assert ok.status_code == 200


def _unset_owner_pin():
    from database import db
    import asyncio
    asyncio.get_event_loop().run_until_complete(
        db.auth_users.update_one({"email": OWNER["email"]}, {"$unset": {"pin": ""}}))


def test_complete_with_pin_sets_owner_pin_atomically_and_pin_login_works(anon):
    initiate = req(anon, "POST", "/api/auth/owner-recovery/initiate",
                   json={"recoveryKey": RECOVERY_KEY, "email": OWNER["email"]})
    token = initiate.json()["token"]

    complete = req(anon, "POST", "/api/auth/owner-recovery/complete",
                   json={"token": token, "password": OWNER["password"], "pin": "9402"})
    assert complete.status_code == 200, complete.text

    try:
        pin_login = req(anon, "POST", "/api/auth/pin-login", json={"pin": "9402"})
        assert pin_login.status_code == 200, pin_login.text
        assert pin_login.json()["user"]["role"] == "owner"
    finally:
        _unset_owner_pin()


def test_complete_rejects_invalid_pin_format_without_consuming_token(anon):
    initiate = req(anon, "POST", "/api/auth/owner-recovery/initiate",
                   json={"recoveryKey": RECOVERY_KEY, "email": OWNER["email"]})
    token = initiate.json()["token"]
    r = req(anon, "POST", "/api/auth/owner-recovery/complete",
            json={"token": token, "password": OWNER["password"], "pin": "abcd"})
    assert r.status_code == 400

    # The rejected pin must not have consumed the token, and must not have
    # been silently dropped — the whole request is rejected.
    ok = req(anon, "POST", "/api/auth/owner-recovery/complete",
            json={"token": token, "password": OWNER["password"]})
    assert ok.status_code == 200


def test_complete_without_pin_field_leaves_existing_pin_untouched(anon):
    initiate1 = req(anon, "POST", "/api/auth/owner-recovery/initiate",
                    json={"recoveryKey": RECOVERY_KEY, "email": OWNER["email"]})
    token1 = initiate1.json()["token"]
    seed = req(anon, "POST", "/api/auth/owner-recovery/complete",
              json={"token": token1, "password": OWNER["password"], "pin": "9405"})
    assert seed.status_code == 200, seed.text

    try:
        initiate2 = req(anon, "POST", "/api/auth/owner-recovery/initiate",
                        json={"recoveryKey": RECOVERY_KEY, "email": OWNER["email"]})
        token2 = initiate2.json()["token"]
        r = req(anon, "POST", "/api/auth/owner-recovery/complete",
                json={"token": token2, "password": OWNER["password"]})
        assert r.status_code == 200, r.text

        from database import db
        import asyncio
        owner = asyncio.get_event_loop().run_until_complete(
            db.auth_users.find_one({"email": OWNER["email"]}))
        assert owner.get("pin") == "9405"
    finally:
        _unset_owner_pin()


def test_recovery_selects_second_owner_and_rejects_pin_collision(anon):
    import asyncio
    from database import db
    from routes.auth import hash_password
    loop = asyncio.get_event_loop()
    second = {"id": "recovery-second-owner", "email": "SecondOwner@example.com", "name": "Second", "role": "owner", "businessId": "second", "status": "active", "password_hash": hash_password("OriginalPass2026!"), "pin": "8462"}
    loop.run_until_complete(db.auth_users.insert_one(second))
    try:
        token = req(anon, "POST", "/api/auth/owner-recovery/initiate", json={"recoveryKey": RECOVERY_KEY, "email": "secondowner@example.com"}).json()["token"]
        changed = req(anon, "POST", "/api/auth/owner-recovery/complete", json={"token": token, "password": "SecondNewPass2026!"})
        assert changed.status_code == 200, changed.text
        saved = loop.run_until_complete(db.auth_users.find_one({"id": second["id"]}))
        assert saved["pin"] == "8462"
        token = req(anon, "POST", "/api/auth/owner-recovery/initiate", json={"recoveryKey": RECOVERY_KEY, "email": OWNER["email"]}).json()["token"]
        rejected = req(anon, "POST", "/api/auth/owner-recovery/complete", json={"token": token, "password": "ShouldNotChange2026!", "pin": "8462"})
        assert rejected.status_code == 409
    finally:
        loop.run_until_complete(db.auth_users.delete_one({"id": second["id"]}))


def test_duplicate_pin_never_selects_an_arbitrary_account(anon):
    import asyncio
    from database import db
    loop = asyncio.get_event_loop()
    for ident in ("duplicate-pin-a", "duplicate-pin-b"):
        loop.run_until_complete(db.auth_users.insert_one({"id": ident, "email": ident + "@example.com", "name": ident, "pin": "9753", "role": "owner", "status": "active"}))
    try:
        response = req(anon, "POST", "/api/auth/pin-login", json={"pin": "9753"})
        assert response.status_code == 401
    finally:
        loop.run_until_complete(db.auth_users.delete_many({"id": {"$in": ["duplicate-pin-a", "duplicate-pin-b"]}}))
