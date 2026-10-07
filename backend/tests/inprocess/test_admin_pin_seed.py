"""seed_admin() bootstraps the owner's email/password idempotently from
ADMIN_EMAIL/ADMIN_PASSWORD — self-healing the password hash on every startup
if the env var changes. PIN login (POST /auth/pin-login) already works for
any active user with a `pin` field, owner included, with no role
restriction — but seed_admin() never set one, so the owner had no way to
sign in with a PIN. ADMIN_PIN closes that gap the same way ADMIN_PASSWORD
already works: optional, self-healing, no hardcoded fallback.
"""
import asyncio

from conftest import OWNER, req

from routes.auth import seed_admin


def _seed(loop):
    loop.run_until_complete(seed_admin())


def _clear_owner_pin(loop):
    from database import db
    loop.run_until_complete(
        db.auth_users.update_one({"email": OWNER["email"]}, {"$unset": {"pin": ""}})
    )


def test_admin_pin_seeds_a_working_owner_pin_login(client, monkeypatch):
    loop = asyncio.get_event_loop()
    monkeypatch.setenv("ADMIN_PIN", "9471")
    try:
        _seed(loop)
        r = req(client, "POST", "/api/auth/pin-login", json={"pin": "9471"})
        assert r.status_code == 200, r.text[:200]
        assert r.json()["user"]["email"] == OWNER["email"]
        assert r.json()["user"]["role"] == "owner"
    finally:
        _clear_owner_pin(loop)


def test_admin_pin_self_heals_to_a_new_value_on_restart(client, monkeypatch):
    """Changing ADMIN_PIN and restarting (i.e. seed_admin running again)
    must update the live PIN login, same as ADMIN_PASSWORD already does for
    the password hash — not just seed it once and ignore later changes."""
    loop = asyncio.get_event_loop()
    try:
        monkeypatch.setenv("ADMIN_PIN", "9471")
        _seed(loop)
        assert req(client, "POST", "/api/auth/pin-login", json={"pin": "9471"}).status_code == 200

        monkeypatch.setenv("ADMIN_PIN", "9472")
        _seed(loop)

        old = req(client, "POST", "/api/auth/pin-login", json={"pin": "9471"})
        assert old.status_code == 401, old.text[:200]

        new = req(client, "POST", "/api/auth/pin-login", json={"pin": "9472"})
        assert new.status_code == 200, new.text[:200]
        assert new.json()["user"]["email"] == OWNER["email"]
    finally:
        _clear_owner_pin(loop)


def test_invalid_admin_pin_is_rejected_at_seed_time_not_silently_accepted(client, monkeypatch, caplog):
    """A 1-digit or 5-digit ADMIN_PIN would 400 at login time via
    pin_login's own 2-4 digit check — seed_admin must catch this itself at
    startup (logging a warning) instead of seeding a PIN nothing can ever
    log in with."""
    loop = asyncio.get_event_loop()
    try:
        for bad_pin in ("1", "12345", "abcd"):
            monkeypatch.setenv("ADMIN_PIN", bad_pin)
            with caplog.at_level("WARNING"):
                _seed(loop)
            assert "ADMIN_PIN" in caplog.text

            from database import db
            owner = loop.run_until_complete(db.auth_users.find_one({"email": OWNER["email"]}))
            assert owner.get("pin") != bad_pin, f"invalid ADMIN_PIN {bad_pin!r} was seeded anyway"

            r = req(client, "POST", "/api/auth/pin-login", json={"pin": bad_pin[:4] or "1"})
            assert r.status_code in (400, 401)
            caplog.clear()
    finally:
        _clear_owner_pin(loop)


def test_admin_pin_unset_leaves_existing_pin_alone(client, monkeypatch):
    """No ADMIN_PIN in the environment must not touch an existing `pin`
    field — mirrors the 'no hardcoded fallback' posture already established
    for ADMIN_PASSWORD."""
    loop = asyncio.get_event_loop()
    try:
        monkeypatch.setenv("ADMIN_PIN", "9473")
        _seed(loop)

        monkeypatch.delenv("ADMIN_PIN", raising=False)
        _seed(loop)

        r = req(client, "POST", "/api/auth/pin-login", json={"pin": "9473"})
        assert r.status_code == 200, r.text[:200]
    finally:
        _clear_owner_pin(loop)
