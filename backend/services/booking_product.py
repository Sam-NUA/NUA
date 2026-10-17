"""Isolated Booking pilot accounts; no paid entitlement is invented here."""
import functools
import hashlib
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError
from database import db, client
from middleware.actor_context import set_actor_context, get_actor_context

PREFIX = 'nb_'

def is_booking_account(business_id):
    return isinstance(business_id, str) and business_id.startswith(PREFIX)

def now():
    return datetime.now(timezone.utc)

def trial_open(account):
    sub = (account or {}).get('products', {}).get('booking', {})
    try:
        end = datetime.fromisoformat(sub['trialEndsAt'])
        return sub.get('state') == 'trialing' and end > now()
    except (KeyError, ValueError, TypeError):
        return False

async def transaction(operation):
    from services.booking_rules_engine import active_capacity_leases
    async def guarded(session):
        for lock_id, token in active_capacity_leases.get():
            fenced = await db.booking_capacity_locks.find_one_and_update(
                {'_id': lock_id, 'token': token, 'expiresAt': {'$gt': now().isoformat()}},
                {'$inc': {'fence': 1}}, session=session)
            if fenced is None:
                raise HTTPException(409, 'Product lease expired; please retry.')
        return await operation(session)
    async with await client.start_session() as session:
        return await session.with_transaction(guarded)

def lifecycle_lock(fn):
    @functools.wraps(fn)
    async def wrapped(business_id, *args, **kwargs):
        from services.booking_rules_engine import _acquire_one
        try:
            async with _acquire_one('product-lifecycle:' + business_id):
                return await fn(business_id, *args, **kwargs)
        except TimeoutError:
            raise HTTPException(409, 'Another account operation is completing; please retry.')
    return wrapped

async def account_for(business_id):
    account = await db.product_accounts.find_one({'_id': business_id})
    if not account:
        raise HTTPException(404, 'Booking account not found')
    return account

async def require_booking(business_id):
    account = await account_for(business_id)
    if not trial_open(account):
        raise HTTPException(403, 'Booking is read-only. Your trial has ended or was cancelled.')
    return account

async def signup(data):
    if os.environ.get('BOOKING_PRODUCT_SIGNUP_ENABLED', 'false').lower() != 'true':
        raise HTTPException(503, 'Booking pilot registration is not open yet.')
    from routes.auth import hash_password
    business_id = PREFIX + uuid.uuid4().hex
    email = str(data.email).lower()
    # Existing unique email index also fences concurrent registrations.
    await db.auth_users.create_index('email', unique=True)
    stamp = now().isoformat()
    account = {'_id': business_id, 'businessId': business_id, 'createdAt': stamp,
               'products': {'booking': {'plan': 'pilot', 'state': 'trialing',
                 'trialEndsAt': (now() + timedelta(days=14)).isoformat()}},
               'venue': {'name': data.venueName, 'timezone': data.timezone,
                         'openTime': '17:00', 'closeTime': '22:00', 'capacity': 40,
                         'maxPartySize': 10, 'published': False}}
    user = {'id': str(uuid.uuid4()), 'businessId': business_id,
            'email': email, 'name': data.name, 'role': 'owner', 'status': 'active',
            'password_hash': hash_password(data.password), 'createdAt': stamp}
    set_actor_context({**get_actor_context(), 'businessId': business_id})
    async def create(session):
        await db.auth_users.insert_one(dict(user), session=session)
        await db.businesses.insert_one({'id': business_id, 'name': data.venueName,
            'timezone': data.timezone, 'type': 'restaurant', 'onboardingComplete': True,
            'ownerId': user['id']}, session=session)
        await db.product_accounts.insert_one(dict(account), session=session)
    try:
        await transaction(create)
    except DuplicateKeyError:
        raise HTTPException(409, 'Unable to register this email. Try signing in.')
    return user

@lifecycle_lock
async def save_venue(business_id, data):
    # Only typed venue fields reach this update; no product/billing state input.
    await require_booking(business_id)
    async def update(session):
        await db.product_accounts.update_one({'_id': business_id}, {'$set': {'venue': data.model_dump()}}, session=session)
        await db.businesses.update_one({'id': business_id}, {'$set': {'name': data.name, 'timezone': data.timezone}}, session=session)
    await transaction(update)
    return await account_for(business_id)

@lifecycle_lock
async def cancel(business_id):
    async def update(session):
        await db.product_accounts.update_one({'_id': business_id}, {'$set': {
            'products.booking.state': 'cancelled', 'products.booking.cancelledAt': now().isoformat(),
            'venue.published': False}}, session=session)
    await transaction(update)
    return await account_for(business_id)

@lifecycle_lock
async def book(business_id, data, *, guest=False):
    from services.booking_rules_engine import capacity_lock, validate_and_enrich_booking, BookingRuleViolation
    from services import reservation_store
    from models.reservation import Reservation
    from zoneinfo import ZoneInfo
    account = await require_booking(business_id)
    venue = account['venue']
    if guest and not venue['published']:
        raise HTTPException(404, 'Booking page is not available')
    local = datetime.combine(data.date, data.time).replace(tzinfo=ZoneInfo(venue['timezone']))
    if local.astimezone(timezone.utc).astimezone(local.tzinfo).replace(tzinfo=None) != local.replace(tzinfo=None):
        raise HTTPException(422, 'This local time does not exist because the clocks change. Choose another time.')
    if local <= now() or local > now() + timedelta(days=60):
        raise HTTPException(422, 'Choose a future booking within 60 days.')
    hhmm = data.time.strftime('%H:%M')
    if not venue['openTime'] <= hhmm < venue['closeTime']:
        raise HTTPException(422, 'Choose a time within the booking hours.')
    if data.partySize > venue['maxPartySize']:
        raise HTTPException(422, 'Please contact the venue for a larger party.')
    payload = data.model_dump(mode='json', exclude={'requestId'})
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    key = 'booking:' + business_id + ':' + str(data.requestId)
    async def existing():
        doc = await db.reservations.find_one({'_id': key, 'businessId': business_id})
        if doc and doc.get('requestFingerprint') != fingerprint:
            raise HTTPException(409, 'This request ID was already used for different booking details.')
        return doc
    def reply(doc):
        return {'id': doc['id'], 'status': doc['status'], 'date': doc['date'], 'time': doc['time']}
    set_actor_context({**get_actor_context(), 'businessId': business_id})
    try:
        async with capacity_lock(business_id, data.date.isoformat()):
            prior = await existing()
            if prior:
                return reply(prior)
            # Recheck entitlement after waiting for capacity, before any write.
            await require_booking(business_id)
            docs = await db.reservations.find({'businessId': business_id, 'date': data.date.isoformat(),
                'status': {'$in': ['confirmed', 'seated']}}).to_list(None)
            minute = data.time.hour * 60 + data.time.minute
            covers = 0
            for doc in docs:
                hh, mm = map(int, doc['time'].split(':'))
                start = hh * 60 + mm
                if start < minute + 90 and start + doc.get('duration', 90) > minute:
                    covers += doc['partySize']
            if covers + data.partySize > venue['capacity']:
                raise HTTPException(409, 'This time does not have enough capacity. Please choose another time.')
            enrichment = await validate_and_enrich_booking(date=data.date.isoformat(), time=hhmm,
                party_size=data.partySize, source='online', business_id=business_id)
            doc = Reservation(guestName=data.guestName, guestEmail=str(data.guestEmail),
                guestPhone=data.guestPhone, partySize=data.partySize, date=data.date.isoformat(),
                time=hhmm, specialRequests=data.specialRequests, businessId=business_id,
                source='online' if guest else 'phone', **enrichment).model_dump()
            doc.update({'_id': key, 'requestFingerprint': fingerprint, 'product': 'booking'})
            try:
                await reservation_store.insert_one(doc)
            except DuplicateKeyError:
                prior = await existing()
                if prior:
                    return reply(prior)
                raise
            return reply(doc)
    except (TimeoutError, BookingRuleViolation) as exc:
        raise HTTPException(409, str(exc))
