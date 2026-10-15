"""Real request handlers; the shared fixture doubles transaction aborts only."""
import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from conftest import req
from database import db
from models.appointment import AppointmentCreate, AppointmentUpdate
from routes import appointments, stock_transfers


def _id():
    return 'consistency-' + uuid.uuid4().hex


@pytest.fixture(autouse=True)
def clean_generated_records(client):
    yield
    async def cleanup():
        prefix = {'$regex': '^consistency-'}
        for name in ('products', 'customers', 'services'):
            await db[name].delete_many({'id': prefix})
        await db.appointments.delete_many({'$or': [{'id': prefix}, {'serviceId': prefix}]})
        await db.stock_transfers.delete_many({'productId': prefix})
        await db.client_intake.delete_many({'$or': [{'customerId': prefix}, {'appointmentId': prefix}]})
        await db.transactions.delete_many({'businessId': {'$regex': '^analytics-consistency-'}})
        await db.channel_menus.delete_many({'productId': prefix})
    client.portal.call(cleanup)


def _break_transfer_write(monkeypatch, method, broken):
    # Motor/mongomock return a new collection wrapper on attribute access;
    # patch the handler's database boundary so fault injection actually runs.
    collection = db.stock_transfers
    class Transfers:
        def __getattr__(self, name):
            return broken if name == method else getattr(collection, name)
    class Database:
        stock_transfers = Transfers()
        def __getattr__(self, name):
            return getattr(db, name)
    monkeypatch.setattr(stock_transfers, 'db', Database())


def _user(client, headers):
    return req(client, 'GET', '/api/auth/me', headers=headers).json()


def _transfer_fixture(client, user):
    product_id = _id()
    client.portal.call(db.products.insert_one, {
        'id': product_id, 'name': 'Concurrent stock', 'businessId': user['businessId'],
        'stockByLocation': {'Source': 20, 'Destination': 0}})
    return stock_transfers.StockTransferCreate(
        productId=product_id, fromLocation='Source', toLocation='Destination', quantity=5)


@pytest.mark.parametrize('actions', [('receive', 'receive'), ('cancel', 'cancel'), ('receive', 'cancel')])
def test_transfer_competing_terminal_actions_apply_stock_once(client, owner_headers, actions):
    user = _user(client, owner_headers)
    data = _transfer_fixture(client, user)

    async def scenario():
        transfer = await stock_transfers.create_transfer(data, user)
        async def attempt(action):
            try:
                fn = stock_transfers.receive_transfer if action == 'receive' else stock_transfers.cancel_transfer
                return await fn(transfer['id'], user)
            except HTTPException as exc:
                assert exc.status_code == 400
        results = await asyncio.gather(*(attempt(a) for a in actions))
        assert sum(r is not None for r in results) == 1
        row = await db.stock_transfers.find_one({'id': transfer['id']})
        product = await db.products.find_one({'id': data.productId})
        assert product['stockByLocation'] == ({'Source': 15, 'Destination': 5}
                                               if row['status'] == 'received' else {'Source': 20, 'Destination': 0})
    client.portal.call(scenario)


def test_transfer_insert_failure_rolls_back_source_debit(client, owner_headers, monkeypatch):
    user = _user(client, owner_headers)
    data = _transfer_fixture(client, user)

    async def broken(*args, **kwargs):
        assert (await db.products.find_one({'id': data.productId}))['stockByLocation']['Source'] == 15
        raise RuntimeError('injected insert failure')
    _break_transfer_write(monkeypatch, 'insert_one', broken)
    with pytest.raises(RuntimeError, match='injected'):
        client.portal.call(stock_transfers.create_transfer, data, user)
    assert client.portal.call(db.products.find_one, {'id': data.productId})['stockByLocation']['Source'] == 20


def test_transfer_status_failure_rolls_back_destination_credit(client, owner_headers, monkeypatch):
    user = _user(client, owner_headers)
    data = _transfer_fixture(client, user)
    transfer = client.portal.call(stock_transfers.create_transfer, data, user)

    async def broken(*args, **kwargs):
        assert (await db.products.find_one({'id': data.productId}))['stockByLocation']['Destination'] == 5
        raise RuntimeError('injected status failure')
    _break_transfer_write(monkeypatch, 'find_one_and_update', broken)
    with pytest.raises(RuntimeError, match='injected'):
        client.portal.call(stock_transfers.receive_transfer, transfer['id'], user)
    assert client.portal.call(db.products.find_one, {'id': data.productId})['stockByLocation'] == {'Source': 15, 'Destination': 0}
    assert client.portal.call(db.stock_transfers.find_one, {'id': transfer['id']})['status'] == 'in_transit'


def _appointment_fixture(client, user):
    service_id = _id()
    client.portal.call(db.services.insert_one, {
        'id': service_id, 'businessId': user['businessId'], 'name': 'Concurrent service',
        'durationMinutes': 45, 'price': 50})
    return AppointmentCreate(customerName='Concurrent client', staffId=user['id'], serviceId=service_id,
                             date='2027-04-10', time='10:00')


def test_concurrent_appointments_and_reconfirmation_cannot_overlap(client, owner_headers):
    user = _user(client, owner_headers)
    data = _appointment_fixture(client, user)

    async def scenario():
        async def attempt():
            try:
                return await appointments.create_appointment(data, user)
            except HTTPException as exc:
                assert exc.status_code == 409
        results = await asyncio.gather(*(attempt() for _ in range(4)))
        winner = next(r for r in results if r is not None)
        assert sum(r is not None for r in results) == 1
        await appointments.cancel_appointment(winner.id, user)
        replacement = await appointments.create_appointment(data, user)
        with pytest.raises(HTTPException) as exc:
            await appointments.update_appointment(winner.id, AppointmentUpdate(status='confirmed'), user)
        assert exc.value.status_code == 409
        # Adjacent appointments still work; changing one into the occupied slot does not.
        adjacent = await appointments.create_appointment(data.model_copy(update={'time': '10:45'}), user)
        with pytest.raises(HTTPException) as exc:
            await appointments.update_appointment(adjacent.id, AppointmentUpdate(time='10:15'), user)
        assert exc.value.status_code == 409
        assert (await db.appointments.find_one({'id': adjacent.id}))['time'] == '10:45'
        await appointments.cancel_appointment(replacement.id, user)
        await appointments.cancel_appointment(adjacent.id, user)
    client.portal.call(scenario)


@pytest.mark.parametrize('field,collection', [('customerId', 'customers'), ('appointmentId', 'appointments')])
@pytest.mark.parametrize('ownership', ['foreign', 'missing', 'quarantined'])
def test_intake_rejects_invalid_tenant_reference_without_writing(client, owner_headers, field, collection, ownership):
    reference = _id()
    if ownership != 'missing':
        client.portal.call(db[collection].insert_one, {
            'id': reference, 'businessId': 'foreign-business' if ownership == 'foreign' else 'default',
            '_ownershipQuarantined': ownership == 'quarantined'})
    result = req(client, 'POST', '/api/client-intake', headers=owner_headers,
                 json={'customerName': 'Reference test', field: reference})
    assert result.status_code == 404, result.text
    assert client.portal.call(db.client_intake.count_documents, {field: reference}) == 0


def test_owned_intake_references_and_walkins_remain_valid(client, owner_headers):
    customer, appointment = _id(), _id()
    client.portal.call(db.customers.insert_one, {'id': customer, 'businessId': 'default'})
    client.portal.call(db.appointments.insert_one, {'id': appointment, 'businessId': 'default'})
    result = req(client, 'POST', '/api/client-intake', headers=owner_headers,
                 json={'customerName': 'Owned references', 'customerId': customer, 'appointmentId': appointment})
    assert result.status_code == 200, result.text
    walkin = req(client, 'POST', '/api/client-intake', headers=owner_headers, json={'customerName': 'Walk in'})
    assert walkin.status_code == 200, walkin.text


def test_slow_mover_ranking_uses_bson_sale_timestamp_not_created_at(client, owner_headers):
    # Isolate the fixture venue rather than assuming the session DB is empty.
    from routes.channel_menus import ai_discount_slow_movers
    biz = 'analytics-' + _id()
    product_ids = [_id() for _ in range(3)]
    now = datetime.now(timezone.utc)
    async def scenario():
        await db.products.insert_many([
            {'id': p, 'businessId': biz, 'name': str(i), 'price': 10} for i, p in enumerate(product_ids)])
        await db.transactions.insert_many([
            {'businessId': biz, 'timestamp': now, 'items': [{'productId': product_ids[0], 'productName': '0', 'quantity': 20}]},
            {'businessId': biz, 'timestamp': now - timedelta(days=30), 'createdAt': now.isoformat(),
             'items': [{'productId': product_ids[1], 'quantity': 100}]},
            {'businessId': 'foreign', 'timestamp': now, 'items': [{'productId': product_ids[2], 'quantity': 100}]},
        ])
        result = await ai_discount_slow_movers('website', {'bottomN': 2}, {'businessId': biz})
        assert {r['productId'] for r in result['applied']} == set(product_ids[1:])
        assert all(r['soldQty'] == 0 for r in result['applied'])
        assert await db.channel_menus.count_documents({'businessId': 'foreign', 'productId': {'$in': product_ids}}) == 0
    client.portal.call(scenario)


@pytest.mark.parametrize('reference', ['missing', 'foreign'])
def test_appointment_create_and_update_reject_foreign_customer(client, owner_headers, reference):
    user = _user(client, owner_headers)
    data = _appointment_fixture(client, user).model_copy(update={'date': '2027-04-11'})
    customer_id = _id()
    if reference == 'foreign':
        client.portal.call(db.customers.insert_one, {'id': customer_id, 'businessId': 'foreign'})
    bad = req(client, 'POST', '/api/appointments', headers=owner_headers,
              json={**data.model_dump(), 'customerId': customer_id})
    assert bad.status_code == 404, bad.text
    good = req(client, 'POST', '/api/appointments', headers=owner_headers, json=data.model_dump())
    assert good.status_code == 200, good.text
    changed = req(client, 'PUT', '/api/appointments/' + good.json()['id'], headers=owner_headers,
                  json={'customerId': customer_id})
    assert changed.status_code == 404, changed.text
    row = client.portal.call(db.appointments.find_one, {'id': good.json()['id']})
    assert row['customerId'] is None


@pytest.mark.parametrize('date,time,duration', [('invalid', '10:00', 30), ('2027-04-11', '25:00', 30),
                                               ('2027-04-11', '10:00', 0), ('2027-04-11', '10:00', -30)])
def test_invalid_appointment_windows_fail_before_insertion(client, owner_headers, date, time, duration):
    user = _user(client, owner_headers)
    data = _appointment_fixture(client, user).model_copy(update={'date': date, 'time': time})
    client.portal.call(db.services.update_one, {'id': data.serviceId}, {'$set': {'durationMinutes': duration}})
    result = req(client, 'POST', '/api/appointments', headers=owner_headers, json=data.model_dump())
    assert result.status_code == 400, result.text
    assert client.portal.call(db.appointments.count_documents, {'serviceId': data.serviceId}) == 0
