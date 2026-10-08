"""Cold starts must not create implicit staff access or revert account changes."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import mongomock_motor
import pytest
from pymongo.errors import DuplicateKeyError


@pytest.fixture
def bootstrap(monkeypatch):
    from routes import auth

    database = mongomock_motor.AsyncMongoMockClient().bootstrap
    monkeypatch.setattr(auth, "db", database)
    monkeypatch.setenv("ADMIN_EMAIL", "bootstrap@example.test")
    monkeypatch.setenv("ADMIN_PASSWORD", "initial-test-secret")
    monkeypatch.delenv("SEED_DEMO_STAFF", raising=False)
    return auth, database


def test_owner_only_and_preserves_later_account_changes(bootstrap, monkeypatch):
    auth, db = bootstrap

    async def scenario():
        await auth.seed_admin()
        owner = await db.auth_users.find_one({})
        assert await db.auth_users.count_documents({}) == 1
        assert auth.verify_password("initial-test-secret", owner["password_hash"])
        await db.auth_users.update_one({"email": owner["email"]}, {"$set": {
            "password_hash": "changed-by-user", "status": "disabled", "role": "cashier"
        }})
        monkeypatch.setenv("ADMIN_PASSWORD", "different-bootstrap-secret")
        await asyncio.gather(auth.seed_admin(), auth.seed_admin())
        saved = await db.auth_users.find_one({})
        assert await db.auth_users.count_documents({}) == 1
        assert saved["id"] == owner["id"]
        assert saved["password_hash"] == "changed-by-user"
        assert saved["status"] == "disabled"
        assert saved["role"] == "cashier"

    asyncio.get_event_loop().run_until_complete(scenario())


def test_demo_accounts_require_explicit_opt_in(bootstrap, monkeypatch):
    auth, db = bootstrap
    monkeypatch.setenv("SEED_DEMO_STAFF", "true")

    async def scenario():
        await auth.seed_admin()
        assert await db.auth_users.count_documents({}) == 4
        await db.auth_users.update_one({"email": "manager@nua.com"}, {"$set": {"role": "cashier"}})
        await auth.seed_admin()
        assert (await db.auth_users.find_one({"email": "manager@nua.com"}))["role"] == "cashier"

    asyncio.get_event_loop().run_until_complete(scenario())


def test_missing_bootstrap_secret_creates_nothing(bootstrap, monkeypatch):
    auth, db = bootstrap
    monkeypatch.delenv("ADMIN_PASSWORD")
    asyncio.get_event_loop().run_until_complete(auth.seed_admin())
    assert asyncio.get_event_loop().run_until_complete(db.auth_users.count_documents({})) == 0


def test_duplicate_insert_race_only_ignored_for_existing_email(bootstrap, monkeypatch):
    auth, _ = bootstrap
    users = SimpleNamespace(update_one=AsyncMock(side_effect=DuplicateKeyError("race")),
                            find_one=AsyncMock(return_value={"email": "owner@example.test"}))
    monkeypatch.setattr(auth, "db", SimpleNamespace(auth_users=users))
    asyncio.get_event_loop().run_until_complete(auth._insert_seed_user({"email": "owner@example.test"}))
    users.find_one.return_value = None
    with pytest.raises(DuplicateKeyError):
        asyncio.get_event_loop().run_until_complete(auth._insert_seed_user({"email": "owner@example.test"}))


def test_admin_email_env_is_normalized_to_lowercase(bootstrap, monkeypatch):
    """ADMIN_EMAIL saved with any uppercase in Vercel must still match the
    lowercased email login() always queries with."""
    auth, db = bootstrap
    monkeypatch.setenv("ADMIN_EMAIL", "Bootstrap@Example.TEST")

    async def scenario():
        await auth.seed_admin()
        owner = await db.auth_users.find_one({"role": "owner"})
        assert owner["email"] == "bootstrap@example.test"

    asyncio.get_event_loop().run_until_complete(scenario())


def test_fresh_bootstrap_with_admin_pin_enables_pin_login(bootstrap, monkeypatch):
    """A brand-new owner document created while ADMIN_PIN is set gets a
    working PIN alongside the password, in the same create-once insert."""
    auth, db = bootstrap
    from routes import staff_management
    # pin_login() reads the module-level `db` staff_management imported from
    # database.py directly; point it at the same isolated mongomock db this
    # fixture gave `auth.db`, so the two modules agree on what "the database"
    # is for this test.
    monkeypatch.setattr(staff_management, "db", db)
    monkeypatch.setenv("ADMIN_PIN", "4321")

    async def scenario():
        await auth.seed_admin()
        owner = await db.auth_users.find_one({"role": "owner"})
        assert owner["pin"] == "4321"
        result = await staff_management.pin_login({"pin": "4321"})
        assert "token" in result
        assert result["user"]["id"] == owner["id"]
        assert result["user"]["role"] == "owner"

    asyncio.get_event_loop().run_until_complete(scenario())


def test_invalid_admin_pin_is_skipped_at_seed_time_with_a_warning(bootstrap, monkeypatch, caplog):
    """An ADMIN_PIN that isn't 2-4 digits must never be written to the
    account — pin_login() matches PINs verbatim, so seeding a bad value
    would silently brick PIN sign-in instead of failing loudly now."""
    import logging
    auth, db = bootstrap
    monkeypatch.setenv("ADMIN_PIN", "abcd")

    async def scenario():
        with caplog.at_level(logging.WARNING, logger="routes.auth"):
            await auth.seed_admin()
        owner = await db.auth_users.find_one({"role": "owner"})
        assert "pin" not in owner
        assert any("ADMIN_PIN" in record.message for record in caplog.records)

    asyncio.get_event_loop().run_until_complete(scenario())


def test_existing_owner_email_casing_is_self_healed_without_duplicate(bootstrap, monkeypatch):
    """An owner created before email normalization (or typed in with the
    wrong case by hand) must become reachable by the lowercased ADMIN_EMAIL
    login always queries with — without ever minting a second owner account
    or touching its password."""
    auth, db = bootstrap

    async def scenario():
        await auth.seed_admin()
        owner = await db.auth_users.find_one({"role": "owner"})
        # Simulate a pre-normalization account stored with mixed case.
        await db.auth_users.update_one({"id": owner["id"]}, {"$set": {"email": "Bootstrap@Example.TEST"}})
        await auth.seed_admin()
        assert await db.auth_users.count_documents({"role": "owner"}) == 1
        healed = await db.auth_users.find_one({"role": "owner"})
        assert healed["id"] == owner["id"]
        assert healed["email"] == "bootstrap@example.test"
        # Password/role/status from the self-heal itself are untouched.
        assert auth.verify_password("initial-test-secret", healed["password_hash"])

    asyncio.get_event_loop().run_until_complete(scenario())
