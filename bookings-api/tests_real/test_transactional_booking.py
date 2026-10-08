"""Real replica-set proofs. Never run against a user database."""
import asyncio
import os
from pathlib import Path
import sys
import uuid

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['BOOKINGS_DB_NAME'] = 'nua_release_test_' + uuid.uuid4().hex
os.environ['BOOKINGS_MONGO_URL'] = os.environ.get('TEST_MONGO_URL', 'mongodb://127.0.0.1:27018/?replicaSet=nua-test')
from database import db, client
import routes_v1
from models import BookingCreate, BookingUpdate, ExternalReservation

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)


def run(coro):
    return loop.run_until_complete(coro)


@pytest.fixture(autouse=True)
def clean():
    run(client.drop_database(db.name))
    yield
    run(client.drop_database(db.name))


async def setup(authority='platform'):
    partner = {'id': 'partner-a', 'test_mode': False}
    venue = {'id': 'venue-a', 'partner_id': partner['id'], 'authority': authority,
             'timezone': 'Australia/Melbourne', 'default_duration_minutes': 90}
    await db.venues.insert_one(dict(venue))
    await db.resources.insert_one({'id': 'table-a', 'venue_id': venue['id'], 'capacity_min': 1, 'capacity_max': 4})
    # Creating collections outside the transactions also supports older replica sets.
    for name in ('bookings', 'usage_events', 'webhook_outbox', 'waitlist', 'external_reservations'):
        await db.create_collection(name)
    return partner


def body(**changes):
    return BookingCreate(**{'venue_id': 'venue-a', 'contact_name': 'Guest', 'party_size': 2,
                            'start_time': '2027-01-10T18:00:00', **changes})


def test_last_table_has_one_winner_under_concurrency():
    async def scenario():
        partner = await setup()

        async def attempt(i):
            try:
                return await routes_v1.create_booking(body(), partner, f'key-{i}')
            except HTTPException as exc:
                return exc.status_code
        results = await asyncio.gather(*(attempt(i) for i in range(12)))
        assert sum(isinstance(r, dict) for r in results) == 1
        assert results.count(409) == 11
        assert await db.bookings.count_documents({}) == 1
        assert await db.usage_events.count_documents({}) == 1
        assert await db.webhook_outbox.count_documents({}) == 1
    run(scenario())


def test_concurrent_retries_commit_one_booking_and_one_event():
    async def scenario():
        partner = await setup()
        results = await asyncio.gather(*(routes_v1.create_booking(body(), partner, 'retry') for _ in range(8)))
        assert len({r['id'] for r in results}) == 1
        assert await db.bookings.count_documents({}) == 1
        assert await db.webhook_outbox.count_documents({}) == 1
    run(scenario())


def test_side_effect_failure_rolls_back_the_booking(monkeypatch):
    async def broken(*args, **kwargs):
        raise RuntimeError('injected event-store failure')

    async def scenario():
        partner = await setup()
        monkeypatch.setattr(routes_v1.webhooks, 'emit', broken)
        with pytest.raises(RuntimeError):
            await routes_v1.create_booking(body(), partner, 'rollback')
        assert await db.bookings.count_documents({}) == 0
        assert await db.usage_events.count_documents({}) == 0
    run(scenario())


def test_restore_rechecks_capacity_and_waitlist_reserves_real_inventory():
    async def scenario():
        partner = await setup()
        first = await routes_v1.create_booking(body(), partner, 'first')
        await db.waitlist.insert_one({'id': 'waiting', 'venue_id': 'venue-a', 'party_size': 2,
                                     'contact_name': 'Waiting', 'status': 'waiting', 'joined_at': '2026'})
        await routes_v1.update_booking(first['id'], BookingUpdate(status='cancelled'), partner)
        entry = await db.waitlist.find_one({'id': 'waiting'})
        assert entry['status'] == 'seated'
        allocated = await db.bookings.find_one({'id': entry['booking_id']})
        assert allocated['status'] == 'seated' and allocated['resource_id'] == 'table-a'
        with pytest.raises(HTTPException) as exc:
            await routes_v1.update_booking(first['id'], BookingUpdate(status='confirmed'), partner)
        assert exc.value.status_code == 409
        assert (await db.bookings.find_one({'id': first['id']}))['status'] == 'cancelled'
    run(scenario())


def test_projection_versions_prevent_stale_resurrection():
    async def scenario():
        partner = await setup('external')
        source = 'a' * 64
        second = ExternalReservation(version=2, date='2027-01-10', time='18:00', source_timezone='Australia/Melbourne')
        assert (await routes_v1.sync_external('venue-a', source, second, partner))['applied']
        await routes_v1.sync_external('venue-a', source, ExternalReservation(version=3, deleted=True), partner)
        assert not (await routes_v1.sync_external('venue-a', source, second, partner))['applied']
        row = await db.external_reservations.find_one({})
        assert row['deleted'] is True and row['version'] == 3
        assert 'contact_name' not in row
        with pytest.raises(HTTPException) as exc:
            await routes_v1.create_booking(body(), partner, 'dual-authority')
        assert exc.value.status_code == 409
    run(scenario())


def test_processes_competing_for_same_capacity():
    async def scenario():
        await setup()
        code = """
import asyncio,json,sys
from fastapi import HTTPException
from models import BookingCreate
from routes_v1 import create_booking
async def main():
 try:
  r=await create_booking(BookingCreate(venue_id='venue-a',contact_name='Guest',start_time='2027-01-10T18:00:00'),{'id':'partner-a','test_mode':False},sys.argv[1])
  print(json.dumps({'ok':r['id']}))
 except HTTPException as e: print(json.dumps({'status':e.status_code}))
asyncio.run(main())
"""
        processes = [await asyncio.create_subprocess_exec(
            sys.executable, '-c', code, f'process-{i}', cwd=str(Path(__file__).resolve().parents[1]),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE) for i in range(2)]
        outputs = await asyncio.gather(*(p.communicate() for p in processes))
        import json
        results = [json.loads(out.decode().strip()) for out, err in outputs]
        assert sum('ok' in r for r in results) == 1
        assert sum(r.get('status') == 409 for r in results) == 1
    run(scenario())


def test_manual_waitlist_seating_is_atomic_and_replayable():
    from models import WaitlistSeat, WaitlistUpdate

    async def scenario():
        partner = await setup()
        await db.waitlist.insert_one({'id': 'waiting-a', 'venue_id': 'venue-a', 'status': 'waiting',
                                     'party_size': 2, 'contact_name': 'Guest'})
        request = WaitlistSeat(start_time='2027-01-10T18:00:00')
        responses = await asyncio.gather(*(routes_v1.seat_waitlist('waiting-a', request, partner) for _ in range(5)))
        assert len({r['id'] for r in responses}) == 1
        assert await db.bookings.count_documents({}) == 1
        assert await db.webhook_outbox.count_documents({}) == 2
        with pytest.raises(HTTPException) as error:
            await routes_v1.update_waitlist('waiting-a', WaitlistUpdate(status='abandoned'), partner)
        assert error.value.status_code == 409
    run(scenario())
