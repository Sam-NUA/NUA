"""Reservation + outbox transaction proofs on an isolated replica-set DB."""
import asyncio
import os
from pathlib import Path
import sys
import uuid

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('JWT_SECRET', 'isolated-replica-test-secret-not-for-production')
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
        for name in ('reservations', 'booking_sync_outbox', 'booking_capacity_locks', 'businesses',
                     'auth_users', 'product_accounts', 'loyalty_product_members',
                     'loyalty_product_rewards', 'loyalty_product_ledger', 'loyalty_product_redemptions'):
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


# Standalone Loyalty uses the same isolated replica set and real transactions.
def loyalty_setup():
    from types import SimpleNamespace
    from services import loyalty_product as product
    from routes.loyalty_product import Program, Join, Adjustment, Reward
    async def scenario():
        os.environ['LOYALTY_PRODUCT_SIGNUP_ENABLED'] = 'true'
        user = await product.signup(SimpleNamespace(name='Owner', venueName='Club',
            email=uuid.uuid4().hex+'@example.com', password='real-test-password'))
        bid = user['businessId']
        account = await product.account_for(bid)
        await product.configure(bid, Program(**{**account['program'], 'published': True}))
        email = uuid.uuid4().hex+'@example.com'
        await product.join(bid, Join(name='Member', email=email, password='real-member-password', acceptTerms=True))
        mid = product.member_id(bid, email)
        await product.mutate_points(bid, mid, Adjustment(requestId=uuid.uuid4(), points=100, reason='Receipt test'), user['id'])
        rid = str(uuid.uuid4())
        await product.save_reward(bid, rid, Reward(name='Coffee', points=100))
        return product, bid, mid, rid
    return run(scenario())


def test_loyalty_real_concurrent_claims_cannot_overspend():
    product, bid, mid, rid = loyalty_setup()
    from routes.loyalty_product import Claim
    async def scenario():
        async def claim():
            try:
                return await product.mutate_points(bid, mid, Claim(requestId=uuid.uuid4()), mid, reward_id=rid)
            except HTTPException as exc:
                assert exc.status_code == 409
                return None
        results = await asyncio.gather(*(claim() for _ in range(8)))
        assert sum(r is not None for r in results) == 1
        assert (await product.member_for(bid, mid))['points'] == 0
        assert await db.loyalty_product_redemptions.count_documents({'businessId':bid}) == 1
        assert await db.loyalty_product_ledger.count_documents({'businessId':bid}) == 2
    run(scenario())


def test_loyalty_real_replay_and_concurrent_refund_are_exactly_once():
    product, bid, mid, rid = loyalty_setup()
    from routes.loyalty_product import Claim
    async def scenario():
        data = Claim(requestId=uuid.uuid4())
        results = await asyncio.gather(*(product.mutate_points(bid, mid, data, mid, reward_id=rid) for _ in range(4)))
        assert all(r == results[0] for r in results)
        receipt = results[0]['redemptionId']
        await asyncio.gather(*(product.resolve_redemption(bid, receipt, 'cancel', 'owner') for _ in range(4)))
        member = await product.member_for(bid, mid)
        assert member['points'] == 100 and member['earnedPoints'] == 100
        assert await db.loyalty_product_ledger.count_documents({'businessId':bid}) == 3
    run(scenario())


def test_loyalty_transaction_failure_rolls_back_points_and_receipt(monkeypatch):
    product, bid, mid, rid = loyalty_setup()
    from routes.loyalty_product import Claim
    original = product.transaction
    async def failing(operation):
        async def write_then_fail(session):
            await operation(session)
            raise RuntimeError('injected failure before commit')
        return await original(write_then_fail)
    monkeypatch.setattr(product, 'transaction', failing)
    async def scenario():
        with pytest.raises(RuntimeError):
            await product.mutate_points(bid, mid, Claim(requestId=uuid.uuid4()), mid, reward_id=rid)
        assert (await product.member_for(bid, mid))['points'] == 100
        assert await db.loyalty_product_redemptions.count_documents({'businessId':bid}) == 0
        assert await db.loyalty_product_ledger.count_documents({'businessId':bid}) == 1
    run(scenario())
