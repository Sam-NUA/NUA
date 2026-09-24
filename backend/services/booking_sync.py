"""Deliver the latest native reservation projection, with restart recovery."""
import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from database import db
from services.bookings_partner_client import _config

log = logging.getLogger(__name__)
MAX_ATTEMPTS = 10
_worker = None


def now():
    return datetime.now(timezone.utc)


async def deliver_next():
    stamp = now().isoformat()
    await db.booking_sync_outbox.update_many(
        {'status': 'delivering', 'lease_until': {'$lte': stamp}, 'attempts': {'$gte': MAX_ATTEMPTS}},
        {'$set': {'status': 'failed', 'last_error': 'outcome_unknown'},
         '$unset': {'claim_token': '', 'lease_until': ''}},
    )
    token = uuid.uuid4().hex
    job = await db.booking_sync_outbox.find_one_and_update({
        'attempts': {'$lt': MAX_ATTEMPTS}, '$or': [
            {'status': {'$in': ['pending', 'retrying']}, 'next_attempt_at': {'$lte': stamp}},
            {'status': 'delivering', 'lease_until': {'$lte': stamp}},
        ]}, {'$set': {'status': 'delivering', 'claim_token': token,
                     'lease_until': (now() + timedelta(seconds=60)).isoformat()},
             '$inc': {'attempts': 1}}, sort=[('updated_at', 1)], return_document=True)
    if job is None:
        return False
    config = _config(job['businessId'])
    state = {'status': 'delivered', 'last_error': None, 'delivered_at': now().isoformat()}
    if not config or config['url'] != job['target_url'] or config['venue'] != job['venue_id']:
        state = {'status': 'failed', 'last_error': 'mapping_changed'}
    else:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.put(
                    f"{config['url']}/v1/venues/{config['venue']}/external-reservations/{job['source_id']}",
                    json={**job['snapshot'], 'version': job['version']},
                    headers={'Authorization': f"Bearer {config['key']}"})
            if not 200 <= response.status_code < 300:
                retryable = response.status_code in (408, 429) or response.status_code >= 500
                state = {'status': 'retrying' if retryable else 'failed',
                         'last_error': f'http_{response.status_code}'}
        except httpx.HTTPError as exc:
            state = {'status': 'retrying', 'last_error': type(exc).__name__}
    if state['status'] == 'retrying':
        state['status'] = 'failed' if job['attempts'] >= MAX_ATTEMPTS else 'retrying'
        state['next_attempt_at'] = (now() + timedelta(seconds=min(900, 2 ** job['attempts']))).isoformat()
    # A concurrent edit replaces the desired snapshot and invalidates this
    # claim. An older acknowledgement must never mark the new version sent.
    await db.booking_sync_outbox.update_one(
        {'_id': job['_id'], 'version': job['version'], 'claim_token': token},
        {'$set': state, '$unset': {'claim_token': '', 'lease_until': ''}})
    return True


async def drain(limit=20):
    delivered = 0
    for _ in range(limit):
        if not await deliver_next():
            break
        delivered += 1
    return delivered


async def _run():
    while True:
        try:
            await drain()
        except Exception:
            log.exception('Booking projection worker failed')
        await asyncio.sleep(1)


async def start_worker():
    global _worker
    await db.booking_sync_outbox.create_index([('status', 1), ('next_attempt_at', 1)])
    await db.booking_sync_outbox.create_index([('businessId', 1), ('status', 1)])
    if _worker is None or _worker.done():
        _worker = asyncio.create_task(_run())


async def stop_worker():
    global _worker
    if _worker is not None:
        _worker.cancel()
        try:
            await _worker
        except asyncio.CancelledError:
            pass
        _worker = None
