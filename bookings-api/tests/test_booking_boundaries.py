"""Partner, sandbox and retry boundaries exercised through the public API."""
import asyncio
import uuid

import pytest

from database import db


def provision(client, admin_headers):
    partner = client.post('/admin/partners', headers=admin_headers,
                          json={'name': 'Boundary ' + uuid.uuid4().hex}).json()
    live = {'Authorization': 'Bearer ' + partner['api_key']}
    test = {'Authorization': 'Bearer ' + partner['test_api_key']}
    return live, test


def venue(client, headers):
    result = client.post('/v1/venues', headers=headers, json={'name': 'Venue'}).json()
    resource = client.post(f"/v1/venues/{result['id']}/resources", headers=headers,
                           json={'name': 'Table', 'capacity_max': 6}).json()
    return result['id'], resource['id']


def booking_body(venue_id):
    return {'venue_id': venue_id, 'party_size': 2,
            'start_time': '2027-01-10T18:00:00', 'contact_name': 'Test Guest'}


def test_sandbox_cannot_read_or_modify_live_records(client, admin_headers):
    live, sandbox = provision(client, admin_headers)
    live_venue, resource = venue(client, live)
    test_venue, _ = venue(client, sandbox)
    booking = client.post('/v1/bookings', headers=live, json=booking_body(live_venue)).json()
    wait = client.post('/v1/waitlist', headers=live,
                       json={'venue_id': live_venue, 'contact_name': 'Waiting Guest'}).json()
    assert [v['id'] for v in client.get('/v1/venues', headers=live).json()] == [live_venue]
    assert [v['id'] for v in client.get('/v1/venues', headers=sandbox).json()] == [test_venue]
    for path in [f'/v1/venues/{live_venue}/resources',
                 f'/v1/venues/{live_venue}/availability?date=2027-01-10',
                 f'/v1/bookings?venue_id={live_venue}', f'/v1/waitlist?venue_id={live_venue}']:
        assert client.get(path, headers=sandbox).status_code == 404
    assert client.post('/v1/bookings', headers=sandbox, json=booking_body(live_venue)).status_code == 404
    assert client.patch('/v1/bookings/' + booking['id'], headers=sandbox,
                        json={'status': 'cancelled'}).status_code == 404
    assert client.patch('/v1/waitlist/' + wait['id'], headers=sandbox,
                        json={'status': 'seated'}).status_code == 404
    assert client.get(f'/v1/venues/{test_venue}/resources', headers=live).status_code == 404


def test_retry_returns_same_booking_without_duplicate_usage_or_event(client, admin_headers):
    live, _ = provision(client, admin_headers)
    venue_id, _ = venue(client, live)
    headers = {**live, 'Idempotency-Key': uuid.uuid4().hex}
    body = booking_body(venue_id)
    first = client.post('/v1/bookings', headers=headers, json=body)
    second = client.post('/v1/bookings', headers=headers, json=body)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert 'request_hash' not in second.json()

    async def counts():
        return (await db.bookings.count_documents({'venue_id': venue_id}),
                await db.usage_events.count_documents({'venue_id': venue_id}),
                await db.webhook_outbox.count_documents({'payload.venue_id': venue_id}))
    assert asyncio.run(counts()) == (1, 1, 1)
    changed = client.post('/v1/bookings', headers=headers, json={**body, 'contact_name': 'Changed'})
    assert changed.status_code == 409


def test_keys_are_partner_scoped_and_ownership_is_checked_before_replay(client, admin_headers):
    first, _ = provision(client, admin_headers)
    second, _ = provision(client, admin_headers)
    venue_a, _ = venue(client, first)
    venue_b, _ = venue(client, second)
    headers_a = {**first, 'Idempotency-Key': 'same-client-key'}
    headers_b = {**second, 'Idempotency-Key': 'same-client-key'}
    a = client.post('/v1/bookings', headers=headers_a, json=booking_body(venue_a))
    b = client.post('/v1/bookings', headers=headers_b, json=booking_body(venue_b))
    assert a.status_code == b.status_code == 200
    assert a.json()['id'] != b.json()['id']
    assert client.post('/v1/bookings', headers=headers_b, json=booking_body(venue_a)).status_code == 404


@pytest.mark.parametrize('key', ['', ' ', 'x' * 201])
def test_invalid_retry_keys_are_rejected(client, admin_headers, key):
    live, _ = provision(client, admin_headers)
    venue_id, _ = venue(client, live)
    assert client.post('/v1/bookings', headers={**live, 'Idempotency-Key': key},
                       json=booking_body(venue_id)).status_code == 400


def test_simultaneous_duplicate_inserts_have_one_winner(monkeypatch):
    import routes_v1
    from models import BookingCreate

    async def scenario():
        partner = {'id': uuid.uuid4().hex, 'test_mode': False}
        venue_id = uuid.uuid4().hex
        await db.venues.insert_one({'id': venue_id, 'partner_id': partner['id']})
        reached = 0
        barrier = asyncio.Event()

        async def allocate(*args, **kwargs):
            nonlocal reached
            reached += 1
            if reached == 2:
                barrier.set()
            await barrier.wait()
            return {'id': 'resource'}

        monkeypatch.setattr(routes_v1, 'allocate_resource', allocate)
        body = BookingCreate(**booking_body(venue_id))
        results = await asyncio.gather(*[
            routes_v1.create_booking(body, partner, 'concurrent-key') for _ in range(2)
        ])
        assert results[0]['id'] == results[1]['id']
        assert await db.bookings.count_documents({'venue_id': venue_id}) == 1
        assert await db.usage_events.count_documents({'venue_id': venue_id}) == 1
    asyncio.run(scenario())


def test_legacy_sandbox_rows_do_not_leak_or_consume_live_capacity(client, admin_headers):
    live, sandbox = provision(client, admin_headers)
    venue_id, resource_id = venue(client, live)
    legacy_id = uuid.uuid4().hex

    async def seed():
        await db.bookings.insert_one({
            'id': legacy_id, 'venue_id': venue_id, 'resource_id': resource_id,
            'test': True, 'status': 'confirmed',
            'start_time': '2027-01-10T18:00:00', 'end_time': '2027-01-10T19:30:00',
        })
        await db.waitlist.insert_one({'id': legacy_id, 'venue_id': venue_id,
                                     'test': True, 'status': 'waiting'})
    asyncio.run(seed())
    assert client.get(f'/v1/bookings?venue_id={venue_id}', headers=live).json() == []
    assert client.get(f'/v1/waitlist?venue_id={venue_id}', headers=live).json() == []
    assert client.patch('/v1/bookings/' + legacy_id, headers=live,
                        json={'status': 'cancelled'}).status_code == 404
    created = client.post('/v1/bookings', headers=live, json=booking_body(venue_id))
    assert created.status_code == 200
    sandbox_venue, _ = venue(client, sandbox)
    test_booking = client.post('/v1/bookings', headers=sandbox, json=booking_body(sandbox_venue))
    assert test_booking.status_code == 200 and test_booking.json()['test'] is True
