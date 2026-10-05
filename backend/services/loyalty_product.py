"""Standalone Loyalty: tenant-scoped members and an atomic, append-only ledger.

No POS or payment integration is implied. Every balance mutation and receipt is
committed in a Mongo transaction; no process-local balance or lock is trusted.
"""
import hashlib
import json
import os
import uuid
from datetime import timedelta
import jwt
from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError
from services import booking_product as shared
from database import db, client
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern

now = shared.now
async def transaction(operation):
    async with await client.start_session() as session:
        return await session.with_transaction(operation, read_concern=ReadConcern('snapshot'),
                                              write_concern=WriteConcern('majority'))

PREFIX = 'nl_'
AUDIENCE = 'nua-loyalty-member'
MEMBER_PUBLIC = {'_id': 0, 'passwordHash': 0, 'sessionVersion': 0, 'emailKey': 0}


def is_account(value):
    return isinstance(value, str) and value.startswith(PREFIX)


def active(account):
    sub = account.get('products', {}).get('loyalty', {})
    return shared.trial_open({'products': {'booking': sub}})


async def account_for(business_id, session=None, write=False):
    account = await db.product_accounts.find_one({'_id': business_id}, session=session)
    if not account or not is_account(business_id):
        raise HTTPException(404, 'Loyalty account not found')
    if write and not active(account):
        raise HTTPException(403, 'Loyalty is read-only. The trial ended or was cancelled.')
    return account


async def touch_account(business_id, session, write=True):
    # All mutations write the account document inside the transaction. This
    # conflicts with cancellation/config changes even across cold instances.
    account = await account_for(business_id, session, write=write)
    await db.product_accounts.update_one({'_id': business_id}, {'$inc': {'revision': 1}}, session=session)
    return account


async def signup(data):
    if os.environ.get('LOYALTY_PRODUCT_SIGNUP_ENABLED', 'false').lower() != 'true':
        raise HTTPException(503, 'Loyalty pilot registration is not open yet.')
    from routes.auth import hash_password
    await db.auth_users.create_index('email', unique=True)
    bid = PREFIX + uuid.uuid4().hex
    stamp = now().isoformat()
    user = {'id': str(uuid.uuid4()), 'businessId': bid, 'email': str(data.email).lower(),
            'name': data.name, 'role': 'owner', 'status': 'active',
            'password_hash': hash_password(data.password), 'createdAt': stamp}
    account = {'_id': bid, 'businessId': bid, 'createdAt': stamp, 'revision': 0,
               'products': {'loyalty': {'plan': 'pilot', 'state': 'trialing',
                   'trialEndsAt': (now() + timedelta(days=14)).isoformat()}},
               'program': {'name': data.venueName, 'description': 'Earn points and choose rewards.',
                   'published': False, 'terms': 'Points have no cash value. Rewards are fulfilled by the venue.',
                   'tiers': [{'name': 'Member', 'threshold': 0}, {'name': 'Silver', 'threshold': 500},
                             {'name': 'Gold', 'threshold': 1500}]}}
    async def create(session):
        await db.auth_users.insert_one(dict(user), session=session)
        await db.businesses.insert_one({'id': bid, 'name': data.venueName, 'ownerId': user['id'],
            'onboardingComplete': True, 'type': 'loyalty'}, session=session)
        await db.product_accounts.insert_one(account, session=session)
    try:
        await transaction(create)
    except DuplicateKeyError:
        raise HTTPException(409, 'Unable to register this email. Try signing in.')
    return user


async def configure(bid, data):
    async def operation(session):
        await touch_account(bid, session)
        await db.product_accounts.update_one({'_id': bid}, {'$set': {'program': data.model_dump()}}, session=session)
    await transaction(operation)
    return await account_for(bid)


async def cancel(bid):
    async def operation(session):
        await touch_account(bid, session, write=False)
        await db.product_accounts.update_one({'_id': bid}, {'$set': {
            'products.loyalty.state': 'cancelled', 'products.loyalty.cancelledAt': now().isoformat(),
            'program.published': False}}, session=session)
    await transaction(operation)
    return await account_for(bid)


def member_id(bid, email):
    return 'lm_' + hashlib.sha256((bid + ':' + str(email).lower()).encode()).hexdigest()


def token_for(member):
    return jwt.encode({'sub': member['id'], 'businessId': member['businessId'],
        'aud': AUDIENCE, 'type': 'loyalty_member', 'version': member['sessionVersion'],
        'iat': now(), 'exp': now() + timedelta(hours=8)}, os.environ['JWT_SECRET'], algorithm='HS256')


async def authenticate(token, bid):
    try:
        payload = jwt.decode(token, os.environ['JWT_SECRET'], algorithms=['HS256'], audience=AUDIENCE,
                             options={'require': ['exp', 'iat', 'sub', 'businessId', 'version', 'type']})
        if payload['type'] != 'loyalty_member' or payload['businessId'] != bid:
            raise ValueError('scope')
        member = await db.loyalty_product_members.find_one({'id': payload['sub'], 'businessId': bid})
        if not member or member['sessionVersion'] != payload['version'] or member['status'] != 'active':
            raise ValueError('session')
        return member
    except (jwt.InvalidTokenError, ValueError, KeyError):
        raise HTTPException(401, 'Please sign in to this membership again.')


async def join(bid, data):
    from routes.auth import hash_password
    mid = member_id(bid, data.email)
    member = {'_id': mid, 'id': mid, 'businessId': bid, 'name': data.name,
        'email': str(data.email).lower(), 'passwordHash': hash_password(data.password),
        'sessionVersion': 0, 'status': 'active', 'points': 0, 'earnedPoints': 0,
        'marketingConsent': data.marketingConsent, 'termsAcceptedAt': now().isoformat(),
        'createdAt': now().isoformat()}
    async def operation(session):
        account = await touch_account(bid, session)
        if not account['program']['published']:
            raise HTTPException(403, 'New memberships are currently closed.')
        member['acceptedTerms'] = account['program']['terms']
        await db.loyalty_product_members.insert_one(dict(member), session=session)
    try:
        await transaction(operation)
    except DuplicateKeyError:
        raise HTTPException(409, 'Unable to join with these details. Try signing in.')
    return {'token': token_for(member)}


async def login(bid, data):
    from routes.auth import verify_password, hash_password
    await account_for(bid)
    member = await db.loyalty_product_members.find_one({'_id': member_id(bid, data.email), 'businessId': bid})
    # Constant-cost password verification also for unknown identities.
    hashed = member['passwordHash'] if member else hash_password('unmatched-member-password')
    valid = verify_password(data.password, hashed)
    if not member or not valid or member['status'] != 'active':
        raise HTTPException(401, 'Email or password is incorrect, or membership is paused.')
    return {'token': token_for(member)}


def present_member(member, program):
    result = {k: v for k, v in member.items() if k not in ('_id', 'passwordHash', 'sessionVersion', 'emailKey')}
    tiers = program['tiers']
    result['tier'] = next(t['name'] for t in reversed(tiers) if member['earnedPoints'] >= t['threshold'])
    result['nextTier'] = next((t for t in tiers if t['threshold'] > member['earnedPoints']), None)
    return result


async def member_for(bid, mid, session=None):
    member = await db.loyalty_product_members.find_one({'id': mid, 'businessId': bid}, session=session)
    if not member:
        raise HTTPException(404, 'Member not found')
    return member


async def update_member(bid, mid, data):
    async def operation(session):
        await touch_account(bid, session)
        await member_for(bid, mid, session)
        await db.loyalty_product_members.update_one({'id': mid, 'businessId': bid},
            {'$set': {'status': data.status}, '$inc': {'sessionVersion': 1}}, session=session)
    await transaction(operation)
    return {'status': data.status}


async def save_reward(bid, rid, data):
    async def operation(session):
        await touch_account(bid, session)
        await db.loyalty_product_rewards.update_one({'_id': bid + ':' + rid}, {'$set': {
            **data.model_dump(), 'id': rid, 'businessId': bid, 'updatedAt': now().isoformat()}}, upsert=True, session=session)
    await transaction(operation)
    return {'id': rid}


def fingerprint(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


async def mutate_points(bid, mid, data, actor, *, reward_id=None):
    key = bid + ':' + str(data.requestId)
    intent = {'memberId': mid, 'actor': actor, 'rewardId': reward_id,
              'data': data.model_dump(mode='json', exclude={'requestId'})}
    digest = fingerprint(intent)
    async def operation(session):
        previous = await db.loyalty_product_ledger.find_one({'_id': key}, session=session)
        if previous:
            if previous['fingerprint'] != digest:
                raise HTTPException(409, 'Request ID already used for different details.')
            return previous['result']
        await touch_account(bid, session)
        member = await member_for(bid, mid, session)
        if member['status'] != 'active':
            raise HTTPException(403, 'Membership is paused.')
        reward = None
        if reward_id:
            reward = await db.loyalty_product_rewards.find_one({'id': reward_id, 'businessId': bid, 'active': True}, session=session)
            if not reward:
                raise HTTPException(404, 'Reward is not available')
            delta, reason, kind = -reward['points'], 'Reward: ' + reward['name'], 'redeem'
        else:
            delta, reason, kind = data.points, data.reason, 'adjustment'
        balance = member['points'] + delta
        if balance < 0:
            raise HTTPException(409, 'Not enough points.')
        if balance > 1000000000:
            raise HTTPException(409, 'Points balance limit reached.')
        # Conflict detection and transactional retry serialize competing redemptions.
        changed = await db.loyalty_product_members.update_one({'id': mid, 'businessId': bid, 'points': member['points']},
            {'$inc': {'points': delta, 'earnedPoints': max(delta, 0)}}, session=session)
        if changed.modified_count != 1:
            raise HTTPException(409, 'Balance changed. Please retry.')
        result = {'points': balance, 'entryId': key}
        if reward:
            rid = str(uuid.uuid4())
            await db.loyalty_product_redemptions.insert_one({'_id': rid, 'id': rid,
                'businessId': bid, 'memberId': mid, 'memberName': member['name'],
                'rewardId': reward_id, 'rewardName': reward['name'], 'points': reward['points'],
                'status': 'pending', 'createdAt': now().isoformat()}, session=session)
            result['redemptionId'] = rid
        await db.loyalty_product_ledger.insert_one({'_id': key, 'businessId': bid, 'memberId': mid,
            'points': delta, 'balanceAfter': balance, 'kind': kind, 'reason': reason, 'actor': actor,
            'createdAt': now().isoformat(), 'fingerprint': digest, 'result': result}, session=session)
        return result
    try:
        return await transaction(operation)
    except DuplicateKeyError:
        previous = await db.loyalty_product_ledger.find_one({'_id': key})
        if previous and previous['fingerprint'] == digest:
            return previous['result']
        raise HTTPException(409, 'Request ID already used. Refresh and try again.')


async def resolve_redemption(bid, rid, action, actor):
    async def operation(session):
        # Honour or refund existing commitments even after trial cancellation.
        await touch_account(bid, session, write=False)
        receipt = await db.loyalty_product_redemptions.find_one({'id': rid, 'businessId': bid}, session=session)
        if not receipt:
            raise HTTPException(404, 'Redemption not found')
        status = 'fulfilled' if action == 'fulfil' else 'cancelled'
        if receipt['status'] == status:
            return {'status': status}
        if receipt['status'] != 'pending':
            raise HTTPException(409, 'This redemption has already been resolved.')
        await db.loyalty_product_redemptions.update_one({'id': rid, 'businessId': bid, 'status': 'pending'},
            {'$set': {'status': status, 'resolvedAt': now().isoformat(), 'resolvedBy': actor}}, session=session)
        if action == 'cancel':
            member = await member_for(bid, receipt['memberId'], session)
            await db.loyalty_product_members.update_one({'id': member['id'], 'businessId': bid},
                {'$inc': {'points': receipt['points']}}, session=session)
            await db.loyalty_product_ledger.insert_one({'_id': 'refund:' + rid, 'businessId': bid,
                'memberId': member['id'], 'points': receipt['points'], 'balanceAfter': member['points'] + receipt['points'],
                'kind': 'refund', 'reason': 'Cancelled reward: ' + receipt['rewardName'], 'actor': actor,
                'createdAt': now().isoformat()}, session=session)
        return {'status': status}
    return await transaction(operation)


async def member_update(bid, member, data):
    from routes.auth import verify_password, hash_password
    changes = {'marketingConsent': data.marketingConsent}
    if data.newPassword:
        if not data.currentPassword or not verify_password(data.currentPassword, member['passwordHash']):
            raise HTTPException(403, 'Current password is incorrect.')
        changes['passwordHash'] = hash_password(data.newPassword)
    update = {'$set': changes}
    if data.newPassword:
        update['$inc'] = {'sessionVersion': 1}
    result = await db.loyalty_product_members.update_one({'id': member['id'], 'businessId': bid,
        'sessionVersion': member['sessionVersion'], 'status': 'active'}, update)
    if not result.matched_count:
        raise HTTPException(401, 'Please sign in again.')
    return {'signInAgain': bool(data.newPassword)}


async def export(bid, mid=None):
    scope = {'businessId': bid, **({'memberId': mid} if mid else {})}
    result = {}
    for name in ('members', 'ledger', 'rewards', 'redemptions'):
        query = scope if name in ('ledger', 'redemptions') else {'businessId': bid, **({'id': mid} if name == 'members' and mid else {})}
        projection = MEMBER_PUBLIC if name == 'members' else {'_id': 0, 'fingerprint': 0, 'actor': 0, 'resolvedBy': 0}
        docs = await db['loyalty_product_' + name].find(query, projection).limit(10001).to_list(10001)
        if len(docs) > 10000:
            raise HTTPException(409, 'Contact support for exports above 10,000 records per collection.')
        result[name] = docs
    return result
