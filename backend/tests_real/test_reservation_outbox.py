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
        for name in ('reservations', 'booking_sync_outbox', 'booking_capacity_locks', 'businesses', 'customers', 'transactions', 'loyalty_ledger', 'products', 'stock_transfers',
                     'appointments', 'appointment_calendars', 'services', 'auth_users'):
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


# Real replica-set proofs: inprocess's transaction double is never loaded here.
from routes import stock_transfers, appointments
from models.appointment import AppointmentCreate, AppointmentUpdate
from services import consistency_store


async def seed_transfer():
    await db.products.insert_one({'id': 'transfer-product', 'name': 'Widget',
                                 'businessId': 'business-a', 'stockByLocation': {'A': 20, 'B': 0}})
    user = {'id': 'owner', 'businessId': 'business-a', 'name': 'Owner'}
    data = stock_transfers.StockTransferCreate(productId='transfer-product', fromLocation='A', toLocation='B', quantity=5)
    return user, data


def test_stock_receive_cancel_contention_commits_one_outcome():
    async def scenario():
        user, data = await seed_transfer()
        transfer = await stock_transfers.create_transfer(data, user)
        async def attempt(i):
            try:
                fn = stock_transfers.receive_transfer if i % 2 else stock_transfers.cancel_transfer
                return await fn(transfer['id'], user)
            except HTTPException as exc:
                assert exc.status_code == 400
        results = await asyncio.gather(*(attempt(i) for i in range(8)))
        assert sum(r is not None for r in results) == 1
        row = await db.stock_transfers.find_one({'id': transfer['id']})
        stock = (await db.products.find_one({'id': data.productId}))['stockByLocation']
        assert stock == ({'A': 15, 'B': 5} if row['status'] == 'received' else {'A': 20, 'B': 0})
    run(scenario())


def test_stock_insert_failure_aborts_real_source_debit(monkeypatch):
    class BrokenTransfers:
        async def insert_one(self, *args, **kwargs):
            product = await db.products.find_one({'id': 'transfer-product'}, session=kwargs['session'])
            assert product['stockByLocation']['A'] == 15
            raise RuntimeError('injected transfer failure')
    class BrokenDB:
        stock_transfers = BrokenTransfers()
        def __getattr__(self, name):
            return getattr(db, name)
    async def scenario():
        user, data = await seed_transfer()
        monkeypatch.setattr(stock_transfers, 'db', BrokenDB())
        with pytest.raises(RuntimeError, match='injected'):
            await stock_transfers.create_transfer(data, user)
        assert (await db.products.find_one({'id': data.productId}))['stockByLocation']['A'] == 20
        assert await db.stock_transfers.count_documents({}) == 0
    run(scenario())


def test_stock_status_failure_aborts_real_destination_credit(monkeypatch):
    class BrokenTransfers:
        def __getattr__(self, name):
            return getattr(db.stock_transfers, name)
        async def find_one_and_update(self, *args, **kwargs):
            product = await db.products.find_one({'id': 'transfer-product'}, session=kwargs['session'])
            assert product['stockByLocation']['B'] == 5
            raise RuntimeError('injected status failure')
    class BrokenDB:
        stock_transfers = BrokenTransfers()
        def __getattr__(self, name):
            return getattr(db, name)
    async def scenario():
        user, data = await seed_transfer()
        transfer = await stock_transfers.create_transfer(data, user)
        monkeypatch.setattr(stock_transfers, 'db', BrokenDB())
        with pytest.raises(RuntimeError, match='injected status failure'):
            await stock_transfers.receive_transfer(transfer['id'], user)
        assert (await db.products.find_one({'id': data.productId}))['stockByLocation'] == {'A': 15, 'B': 0}
        assert (await db.stock_transfers.find_one({'id': transfer['id']}))['status'] == 'in_transit'
    run(scenario())


def test_stock_concurrent_source_debits_cannot_oversell():
    async def scenario():
        user, data = await seed_transfer()
        data.quantity = 15
        async def attempt():
            try:
                return await stock_transfers.create_transfer(data, user)
            except HTTPException as exc:
                assert exc.status_code in (400, 409)
        results = await asyncio.gather(*(attempt() for _ in range(8)))
        assert sum(r is not None for r in results) == 1
        assert (await db.products.find_one({'id': data.productId}))['stockByLocation']['A'] == 5
        assert await db.stock_transfers.count_documents({}) == 1
    run(scenario())


async def seed_appointment(business_id='business-a'):
    await db.services.insert_one({'id': 'service-' + business_id, 'businessId': business_id,
                                 'name': 'Service', 'durationMinutes': 60, 'price': 50})
    await db.auth_users.insert_one({'id': 'staff-' + business_id, 'businessId': business_id, 'name': 'Staff'})
    user = {'id': 'staff-' + business_id, 'businessId': business_id}
    data = AppointmentCreate(customerName='Client', staffId=user['id'], serviceId='service-' + business_id,
                             date='2027-04-10', time='10:00')
    return user, data


def test_appointment_concurrent_check_insert_has_one_winner():
    async def scenario():
        user, data = await seed_appointment()
        async def attempt():
            try:
                return await appointments.create_appointment(data, user)
            except HTTPException as exc:
                assert exc.status_code == 409
        results = await asyncio.gather(*(attempt() for _ in range(8)))
        assert sum(r is not None for r in results) == 1
        assert await db.appointments.count_documents({}) == 1
        assert await db.appointment_calendars.count_documents({}) == 1
        other, other_data = await seed_appointment('business-b')
        await appointments.create_appointment(other_data, other)
        assert await db.appointments.count_documents({'businessId': 'business-b'}) == 1
    run(scenario())


def test_appointment_concurrent_reschedules_and_reactivation_are_fenced():
    async def scenario():
        user, data = await seed_appointment()
        first = await appointments.create_appointment(data, user)
        second = await appointments.create_appointment(data.model_copy(update={'time': '11:00'}), user)
        async def attempt(appointment_id):
            try:
                return await appointments.update_appointment(appointment_id, AppointmentUpdate(time='12:00'), user)
            except HTTPException as exc:
                assert exc.status_code == 409
        results = await asyncio.gather(attempt(first.id), attempt(second.id))
        assert sum(r is not None for r in results) == 1
        await appointments.cancel_appointment(first.id, user)
        row = await db.appointments.find_one({'id': first.id})
        await appointments.create_appointment(data.model_copy(update={'time': row['time']}), user)
        with pytest.raises(HTTPException) as exc:
            await appointments.update_appointment(first.id, AppointmentUpdate(status='confirmed'), user)
        assert exc.value.status_code == 409
    run(scenario())


def test_appointment_no_show_retries_tally_customer_once():
    async def scenario():
        user, data = await seed_appointment()
        await db.customers.insert_one({'id': 'no-show-customer', 'businessId': 'business-a'})
        data.customerId = 'no-show-customer'
        appointment = await appointments.create_appointment(data, user)
        await asyncio.gather(*(appointments.no_show_appointment(appointment.id, fee=25, user=user) for _ in range(8)))
        assert (await db.customers.find_one({'id': data.customerId}))['noShowCount'] == 1
    run(scenario())


def test_consistency_store_does_not_fall_back_if_sessions_fail(monkeypatch):
    async def unavailable():
        raise RuntimeError('sessions unavailable')
    async def scenario():
        user, data = await seed_transfer()
        monkeypatch.setattr(consistency_store.client, 'start_session', unavailable)
        with pytest.raises(RuntimeError, match='sessions unavailable'):
            await stock_transfers.create_transfer(data, user)
        assert (await db.products.find_one({'id': data.productId}))['stockByLocation']['A'] == 20
        assert await db.stock_transfers.count_documents({}) == 0
    run(scenario())
