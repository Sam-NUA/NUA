"""Reservation + outbox transaction proofs on an isolated replica-set DB."""
import asyncio
import os
from pathlib import Path
import sys
import uuid

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['DB_NAME'] = 'nua_reservation_test_' + uuid.uuid4().hex
os.environ['MONGO_URL'] = os.environ.get('TEST_MONGO_URL', 'mongodb://127.0.0.1:27018/?replicaSet=nua-test')
os.environ.update({'NUA_BOOKINGS_API_URL': 'https://bookings.example.test',
                   'NUA_BOOKINGS_API_KEY': 'test-key', 'NUA_BOOKINGS_VENUE_ID': 'remote',
                   'NUA_BOOKINGS_BUSINESS_ID': 'business-a'})
from database import db, client
from services import reservation_store
from services.booking_rules_engine import capacity_lock

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)


def run(coro):
    return loop.run_until_complete(coro)


@pytest.fixture(autouse=True)
def clean():
    run(client.drop_database(db.name))
    async def prepare():
        for name in ('reservations', 'booking_sync_outbox', 'booking_capacity_locks', 'businesses', 'customers', 'transactions', 'loyalty_ledger'):
            await db.create_collection(name)
        await db.transactions.create_index(
            [("businessId", 1), ("clientOpId", 1)], unique=True,
            partialFilterExpression={"clientOpId": {"$type": "string"}})
    run(prepare())
    yield
    run(client.drop_database(db.name))


def reservation(**changes):
    return {'id': 'reservation-a', 'businessId': 'business-a', 'date': '2027-01-10',
            'time': '18:00', 'guestName': 'Guest', 'status': 'confirmed', **changes}


def test_create_update_delete_record_durable_versions_and_tombstone():
    async def scenario():
        await reservation_store.insert_one(reservation())
        await reservation_store.update_one({'id': 'reservation-a'}, {'$set': {'status': 'cancelled'}})
        row = await db.booking_sync_outbox.find_one({})
        assert row['version'] == 2 and row['snapshot']['status'] == 'cancelled'
        await reservation_store.delete_one({'id': 'reservation-a'})
        assert await db.reservations.count_documents({}) == 0
        row = await db.booking_sync_outbox.find_one({})
        assert row['version'] == 3 and row['snapshot']['deleted'] is True
        assert 'contact_name' not in row['snapshot']
    run(scenario())


def test_outbox_failure_rolls_back_reservation_mutation(monkeypatch):
    async def broken(*args, **kwargs):
        raise RuntimeError('injected outbox failure')

    async def scenario():
        await reservation_store.insert_one(reservation())
        monkeypatch.setattr(reservation_store, '_enqueue', broken)
        with pytest.raises(RuntimeError):
            await reservation_store.update_one({'id': 'reservation-a'}, {'$set': {'status': 'cancelled'}})
        assert (await db.reservations.find_one({}))['status'] == 'confirmed'
        assert (await db.booking_sync_outbox.find_one({}))['version'] == 1
    run(scenario())


def test_other_business_is_never_mirrored():
    async def scenario():
        await reservation_store.insert_one(reservation(businessId='business-b'))
        assert await db.reservations.count_documents({}) == 1
        assert await db.booking_sync_outbox.count_documents({}) == 0
    run(scenario())


def test_expired_capacity_holder_cannot_commit_even_if_it_resumes():
    async def scenario():
        async with capacity_lock('business-a', '2027-01-10'):
            await db.booking_capacity_locks.update_many({}, {'$set': {'expiresAt': '2000'}})
            with pytest.raises(HTTPException) as exc:
                await reservation_store.insert_one(reservation())
            assert exc.value.status_code == 409
        assert await db.reservations.count_documents({}) == 0
        assert await db.booking_sync_outbox.count_documents({}) == 0
    run(scenario())


def test_native_capacity_contention_commits_one_record():
    async def scenario():
        async def attempt(i):
            async with capacity_lock('business-a', '2027-01-10'):
                if await db.reservations.count_documents({'date': '2027-01-10'}):
                    return False
                await reservation_store.insert_one(reservation(id=f'reservation-{i}'))
                return True
        assert sum(await asyncio.gather(*(attempt(i) for i in range(8)))) == 1
        assert await db.booking_sync_outbox.count_documents({}) == 1
    run(scenario())


# POS point redemption uses the same isolated replica set, never mongomock.
from services import pos_sale_store
from pymongo.errors import AutoReconnect


async def seed_points():
    await db.customers.insert_many([
        {"id": "guest", "businessId": "business-a", "points": 100},
        {"id": "guest", "businessId": "business-b", "points": 200},
    ])


def point_sale(op="sale-op", **changes):
    return {"id": "sale-" + uuid.uuid4().hex, "businessId": "business-a", "clientOpId": op, **changes}


def test_pos_concurrent_same_operation_debits_once():
    async def scenario():
        await seed_points()
        results = await asyncio.gather(*(
            pos_sale_store.insert_with_redemptions(db, point_sale(), [("guest", 30, .3)])
            for _ in range(8)))
        assert sum(inserted for _, inserted in results) == 1
        assert len({sale["id"] for sale, _ in results}) == 1
        assert (await db.customers.find_one({"businessId": "business-a"}))["points"] == 70
        assert (await db.customers.find_one({"businessId": "business-b"}))["points"] == 200
        assert await db.transactions.count_documents({}) == 1
        assert await db.loyalty_ledger.count_documents({"type": "redeem"}) == 1
    run(scenario())


def test_pos_concurrent_distinct_sales_cannot_overdraw():
    async def scenario():
        await seed_points()
        async def attempt(i):
            try:
                return await pos_sale_store.insert_with_redemptions(db, point_sale(str(i)), [("guest", 60, .6)])
            except HTTPException as exc:
                assert exc.status_code == 400
                return None
        results = await asyncio.gather(*(attempt(i) for i in range(4)))
        assert sum(result is not None for result in results) == 1
        assert (await db.customers.find_one({"businessId": "business-a"}))["points"] == 40
        assert await db.transactions.count_documents({}) == 1
    run(scenario())


@pytest.mark.parametrize("second_guest", ["missing", "locked"])
def test_pos_split_failure_aborts_prior_guest_and_ledger(second_guest):
    async def scenario():
        await seed_points()
        if second_guest == "locked":
            await db.customers.insert_one({"id": "locked", "businessId": "business-a", "points": 100, "loyaltyLocked": True})
        with pytest.raises(HTTPException) as exc:
            await pos_sale_store.insert_with_redemptions(
                db, point_sale(), [("guest", 30, .3), (second_guest, 20, .2)])
        assert exc.value.status_code == (403 if second_guest == "locked" else 400)
        assert (await db.customers.find_one({"id": "guest", "businessId": "business-a"}))["points"] == 100
        assert await db.transactions.count_documents({}) == 0
        assert await db.loyalty_ledger.count_documents({}) == 0
    run(scenario())


def test_pos_insert_failure_after_debit_aborts_every_write():
    class BrokenCollection:
        def __getattr__(self, name):
            return getattr(db.transactions, name)
        async def insert_one(self, *args, **kwargs):
            # Prove the debit really happened inside this transaction.
            assert (await db.customers.find_one({"businessId": "business-a"}, session=kwargs["session"]))["points"] == 70
            raise RuntimeError("injected sale insert failure")
    class BrokenDB:
        transactions = BrokenCollection()
        def __getattr__(self, name):
            return getattr(db, name)
    async def scenario():
        await seed_points()
        with pytest.raises(RuntimeError):
            await pos_sale_store.insert_with_redemptions(BrokenDB(), point_sale(), [("guest", 30, .3)])
        assert (await db.customers.find_one({"businessId": "business-a"}))["points"] == 100
        assert await db.loyalty_ledger.count_documents({}) == 0
        assert await db.transactions.count_documents({}) == 0
    run(scenario())


def test_pos_commit_then_lost_response_is_replay_safe(monkeypatch):
    real_transaction = pos_sale_store._transaction
    async def lose_response(operation):
        await real_transaction(operation)
        raise AutoReconnect("injected loss after real commit")
    async def scenario():
        await seed_points()
        monkeypatch.setattr(pos_sale_store, "_transaction", lose_response)
        with pytest.raises(AutoReconnect):
            await pos_sale_store.insert_with_redemptions(db, point_sale(), [("guest", 30, .3)])
        monkeypatch.setattr(pos_sale_store, "_transaction", real_transaction)
        _, inserted = await pos_sale_store.insert_with_redemptions(db, point_sale(), [("guest", 30, .3)])
        assert inserted is False
        assert (await db.customers.find_one({"businessId": "business-a"}))["points"] == 70
        assert await db.transactions.count_documents({}) == 1
        assert await db.loyalty_ledger.count_documents({}) == 1
    run(scenario())
