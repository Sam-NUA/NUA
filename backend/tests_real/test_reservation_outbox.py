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
        for name in ('reservations', 'booking_sync_outbox', 'booking_capacity_locks', 'businesses'):
            await db.create_collection(name)
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
