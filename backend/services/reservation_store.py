"""Reservation persistence with an atomic, coalescing integration outbox.

All reservation writers use this module. When mirroring is configured, the
reservation mutation and latest desired projection commit together. Deletes
retain a tombstone. A crash cannot lose a committed change; later versions
supersede earlier deliveries. No HTTP request runs inside the transaction.
"""
import copy
import hashlib
import os
from datetime import datetime, timezone

from fastapi import HTTPException
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern

from database import db, client
from services.bookings_partner_client import _config


async def _enqueue(doc, deleted, session):
    config = _config(doc.get('businessId'))
    if not config:
        return
    local_id = doc.get('id')
    if not local_id:
        raise HTTPException(409, 'A synced reservation requires a stable id')
    business = await db.businesses.find_one({'id': doc['businessId']}, session=session)
    source_id = hashlib.sha256((doc['businessId'] + ':' + local_id).encode()).hexdigest()
    snapshot = {'deleted': deleted, 'source_timezone': (business or {}).get('timezone') or 'UTC'}
    if not deleted:
        snapshot.update({
            'contact_name': doc.get('guestName', 'Guest'),
            'contact_email': doc.get('guestEmail'), 'contact_phone': doc.get('guestPhone'),
            'party_size': doc.get('partySize', 2), 'date': doc.get('date'), 'time': doc.get('time'),
            'duration': doc.get('duration', 90), 'status': doc.get('status', 'confirmed'),
        })
    now = datetime.now(timezone.utc).isoformat()
    await db.booking_sync_outbox.update_one({'_id': source_id}, {
        '$inc': {'version': 1},
        '$set': {'businessId': doc['businessId'], 'reservationId': local_id,
                 'source_id': source_id, 'snapshot': snapshot, 'status': 'pending',
                 'target_url': config['url'], 'venue_id': config['venue'],
                 'attempts': 0, 'next_attempt_at': now, 'updated_at': now},
        '$unset': {'claim_token': '', 'lease_until': '', 'last_error': ''},
    }, upsert=True, session=session)


async def _mutate(method, *args, **kwargs):
    from services.booking_rules_engine import active_capacity_leases
    leases = active_capacity_leases.get()
    if not leases and not _config(os.environ.get('NUA_BOOKINGS_BUSINESS_ID')):
        return await getattr(db.reservations, method)(*args, **kwargs)
    if kwargs.get('session') is not None:
        raise RuntimeError('Reservation persistence owns its transaction boundary')

    if method == "insert_many" and len(args[0]) > 1000:
        raise HTTPException(409, "Split bulk reservation inserts into at most 1000 records")

    async def operation(session):
        for lock_id, token in leases:
            fenced = await db.booking_capacity_locks.find_one_and_update(
                {'_id': lock_id, 'token': token,
                 'expiresAt': {'$gt': datetime.now(timezone.utc).isoformat()}},
                {'$inc': {'fence': 1}}, session=session)
            if fenced is None:
                raise HTTPException(409, 'Booking capacity lease expired; retry confirmation')
        call_args = copy.deepcopy(args)
        if method.startswith('insert'):
            before = []
        else:
            before = await db.reservations.find(call_args[0], session=session).to_list(1001)
            if len(before) > 1000:
                raise HTTPException(409, 'Split bulk reservation mutations into at most 1000 records')
            if method in ('update_one', 'delete_one', 'find_one_and_update'):
                before = before[:1]
        result = await getattr(db.reservations, method)(*call_args, **kwargs, session=session)
        if method == 'insert_one':
            ids = [result.inserted_id]
        elif method == 'insert_many':
            ids = result.inserted_ids
        else:
            ids = [row['_id'] for row in before]
            if getattr(result, 'upserted_id', None) is not None:
                ids.append(result.upserted_id)
        after = await db.reservations.find({'_id': {'$in': ids}}, session=session).to_list(1000)
        if method.startswith('delete'):
            remaining = {row['_id'] for row in after}
            for doc in before:
                if doc['_id'] not in remaining:
                    await _enqueue(doc, True, session)
        else:
            for doc in after:
                await _enqueue(doc, False, session)
        return result

    return await _transaction(operation)


async def _transaction(operation):
    async with await client.start_session() as session:
        return await session.with_transaction(operation, read_concern=ReadConcern('snapshot'),
                                               write_concern=WriteConcern('majority'))


async def insert_one(*args, **kwargs):
    return await _mutate('insert_one', *args, **kwargs)


async def insert_many(*args, **kwargs):
    return await _mutate('insert_many', *args, **kwargs)


async def update_one(*args, **kwargs):
    return await _mutate('update_one', *args, **kwargs)


async def update_many(*args, **kwargs):
    return await _mutate('update_many', *args, **kwargs)


async def find_one_and_update(*args, **kwargs):
    return await _mutate('find_one_and_update', *args, **kwargs)


async def delete_one(*args, **kwargs):
    return await _mutate('delete_one', *args, **kwargs)


async def delete_many(*args, **kwargs):
    return await _mutate('delete_many', *args, **kwargs)
