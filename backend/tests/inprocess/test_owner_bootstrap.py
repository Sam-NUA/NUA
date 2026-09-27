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
