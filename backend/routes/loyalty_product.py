"""Explicit merchant and member authentication boundaries for standalone Loyalty."""
from typing import Annotated, Literal
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request, Response, Query
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator
from database import db
from deps import get_user
from services import loyalty_product as product

router = APIRouter(prefix='/loyalty-product')
Text = Annotated[str, Field(min_length=1, max_length=120)]
Password = Annotated[str, Field(min_length=12, max_length=72)]
def password_bytes(value: str) -> str:
    if len(value.encode()) > 72: raise ValueError("Password must be at most 72 UTF-8 bytes")
    return value

class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')

class Signup(Strict):
    name: Text
    venueName: Text
    email: EmailStr
    password: Password
    _password = field_validator("password")(password_bytes)

class Tier(Strict):
    name: Text
    threshold: Annotated[int, Field(strict=True, ge=0, le=1000000000)]

class Program(Strict):
    name: Text
    description: Annotated[str, Field(max_length=500)]
    terms: Annotated[str, Field(min_length=10, max_length=5000)]
    published: bool
    tiers: Annotated[list[Tier], Field(min_length=1, max_length=5)]
    @model_validator(mode='after')
    def ordered(self):
        values = [t.threshold for t in self.tiers]
        if values[0] != 0 or values != sorted(set(values)) or len({t.name for t in self.tiers}) != len(values):
            raise ValueError('Tiers need unique names and increasing thresholds starting at zero.')
        return self

class Reward(Strict):
    name: Text
    description: Annotated[str, Field(max_length=500)] = ''
    points: Annotated[int, Field(strict=True, ge=1, le=1000000)]
    active: bool = True

class Join(Strict):
    name: Text
    email: EmailStr
    password: Password
    acceptTerms: Literal[True]
    marketingConsent: bool = False
    _password = field_validator('password')(password_bytes)

class Login(Strict):
    email: EmailStr
    password: Annotated[str, Field(min_length=1, max_length=72)]
    _password = field_validator('password')(password_bytes)

class Adjustment(Strict):
    requestId: UUID
    points: Annotated[int, Field(strict=True, ge=-1000000, le=1000000)]
    reason: Annotated[str, Field(min_length=3, max_length=300)]
    @field_validator('points')
    @classmethod
    def nonzero(cls, value):
        if value == 0: raise ValueError('Points must not be zero')
        return value

class Claim(Strict):
    requestId: UUID
    expectedPoints: Annotated[int, Field(strict=True, ge=1, le=1000000)]

class MemberStatus(Strict):
    status: Literal['active', 'paused']

class Resolution(Strict):
    action: Literal['fulfil', 'cancel']

class Preferences(Strict):
    marketingConsent: bool
    currentPassword: Annotated[str, Field(max_length=72)] | None = None
    newPassword: Password | None = None
    @field_validator('newPassword', 'currentPassword')
    @classmethod
    def bytes_limit(cls, value):
        if value is not None and len(value.encode()) > 72: raise ValueError('Password must be at most 72 UTF-8 bytes')
        return value

async def owner(user=Depends(get_user)):
    if user.get('role') != 'owner' or not product.is_account(user.get('businessId')):
        raise HTTPException(403, 'A standalone Loyalty owner account is required')
    return user

async def member(business_id: str, request: Request):
    authorization = request.headers.get('authorization', '')
    if not authorization.startswith('Bearer '):
        raise HTTPException(401, 'Please sign in to your membership.')
    return await product.authenticate(authorization[7:], business_id)

def snapshot(account):
    return {'businessId': account['_id'], 'program': account['program'], 'products': account['products'],
            'canWrite': product.active(account), 'billingAvailable': False, 'memberPath': '/members/v/' + account['_id']}

@router.get('/availability')
async def availability():
    import os
    return {'signupEnabled': os.environ.get('LOYALTY_PRODUCT_SIGNUP_ENABLED', 'false').lower() == 'true'}

@router.post('/signup', status_code=201)
async def signup(data: Signup, response: Response):
    from routes.auth import create_access_token, create_refresh_token, _set_tokens
    user = await product.signup(data)
    token = create_access_token(user['id'], user['email'], user['role'], user['businessId'])
    _set_tokens(response, token, create_refresh_token(user['id']))
    return {'token': token}

@router.get('/account')
async def account(user=Depends(owner)):
    return snapshot(await product.account_for(user['businessId']))

@router.put('/program')
async def program(data: Program, user=Depends(owner)):
    return snapshot(await product.configure(user['businessId'], data))

@router.post('/cancel')
async def cancel(user=Depends(owner)):
    return snapshot(await product.cancel(user['businessId']))

@router.get('/members')
async def members(user=Depends(owner), q: str = Query('', max_length=120), offset: int = Query(0, ge=0)):
    import re
    bid = user['businessId']; account = await product.account_for(bid)
    query: dict = {'businessId': bid}
    if q: query['$or'] = [{'name': {'$regex': re.escape(q), '$options': 'i'}}, {'email': {'$regex': re.escape(q), '$options': 'i'}}]
    rows = await db.loyalty_product_members.find(query, product.MEMBER_PUBLIC).sort('createdAt', -1).skip(offset).limit(50).to_list(50)
    return {'members': [product.present_member(m, account['program']) for m in rows], 'total': await db.loyalty_product_members.count_documents(query)}

@router.get('/members/{member_id}')
async def detail(member_id: str, user=Depends(owner)):
    bid = user['businessId']; account = await product.account_for(bid)
    row = await product.member_for(bid, member_id)
    ledger = await db.loyalty_product_ledger.find({'businessId': bid, 'memberId': member_id}, {'_id': 0, 'fingerprint': 0}).sort('createdAt', -1).limit(100).to_list(100)
    return {'member': product.present_member(row, account['program']), 'ledger': ledger}

@router.put('/members/{member_id}/status')
async def status(member_id: str, data: MemberStatus, user=Depends(owner)):
    return await product.update_member(user['businessId'], member_id, data)

@router.post('/members/{member_id}/points')
async def points(member_id: str, data: Adjustment, user=Depends(owner)):
    return await product.mutate_points(user['businessId'], member_id, data, user['id'])

@router.get('/rewards')
async def rewards(user=Depends(owner)):
    return await db.loyalty_product_rewards.find({'businessId': user['businessId']}, {'_id': 0}).sort('name', 1).limit(500).to_list(500)

@router.put('/rewards/{reward_id}')
async def reward(reward_id: UUID, data: Reward, user=Depends(owner)):
    return await product.save_reward(user['businessId'], str(reward_id), data)

@router.get('/redemptions')
async def redemptions(user=Depends(owner), offset: int = Query(0, ge=0)):
    return await db.loyalty_product_redemptions.find({'businessId': user['businessId']}, {'_id': 0}).sort('createdAt', -1).skip(offset).limit(50).to_list(50)

@router.post('/redemptions/{redemption_id}/resolve')
async def resolve(redemption_id: UUID, data: Resolution, user=Depends(owner)):
    return await product.resolve_redemption(user['businessId'], str(redemption_id), data.action, user['id'])

@router.get('/export')
async def export(user=Depends(owner)):
    return await product.export(user['businessId'])

# Public/member prefix bypasses STAFF auth only. Private member endpoints all
# require the dedicated audience-bound token; no merchant cookie grants access.
@router.get('/portal/{business_id}')
async def public_program(business_id: str):
    account = await product.account_for(business_id)
    return {'program': account['program'], 'canJoin': product.active(account) and account['program']['published'], 'canRedeem': product.active(account)}

@router.post('/portal/{business_id}/join', status_code=201)
async def join(business_id: str, data: Join):
    return await product.join(business_id, data)

@router.post('/portal/{business_id}/login')
async def login(business_id: str, data: Login):
    return await product.login(business_id, data)

@router.get('/portal/{business_id}/me')
async def me(business_id: str, current=Depends(member)):
    account = await product.account_for(business_id)
    scope = {'businessId': business_id, 'memberId': current['id']}
    ledger = await db.loyalty_product_ledger.find(scope, {'_id': 0, 'fingerprint': 0, 'actor': 0}).sort('createdAt', -1).limit(100).to_list(100)
    redemptions = await db.loyalty_product_redemptions.find(scope, {'_id': 0, 'resolvedBy': 0}).sort('createdAt', -1).limit(100).to_list(100)
    rewards = await db.loyalty_product_rewards.find({'businessId': business_id, 'active': True}, {'_id': 0}).sort('points', 1).limit(500).to_list(500)
    return {'member': product.present_member(current, account['program']), 'ledger': ledger, 'redemptions': redemptions, 'rewards': rewards}

@router.post('/portal/{business_id}/rewards/{reward_id}/claim')
async def claim(business_id: str, reward_id: UUID, data: Claim, current=Depends(member)):
    return await product.mutate_points(business_id, current['id'], data, current['id'], reward_id=str(reward_id))

@router.put('/portal/{business_id}/preferences')
async def preferences(business_id: str, data: Preferences, current=Depends(member)):
    return await product.member_update(business_id, current, data)

@router.post('/portal/{business_id}/logout')
async def logout(business_id: str, current=Depends(member)):
    await db.loyalty_product_members.update_one({'id': current['id'], 'businessId': business_id}, {'$inc': {'sessionVersion': 1}})
    return {'signedOut': True}

@router.get('/portal/{business_id}/export')
async def member_export(business_id: str, current=Depends(member)):
    return await product.export(business_id, current['id'])
