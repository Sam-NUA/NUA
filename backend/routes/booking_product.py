"""Owner-operated Booking pilot. Existing POS licensing is not a dependency."""
from datetime import date, time
from typing import Annotated
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator
from database import db
from deps import get_user
from services import booking_product as product

router = APIRouter(prefix='/booking-product')
Text = Annotated[str, Field(min_length=1, max_length=120)]
def validate_timezone(value: str) -> str:
    try: ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError): raise ValueError('Choose a valid timezone')
    return value

class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

class Signup(StrictModel):
    name: Text
    venueName: Text
    email: EmailStr
    password: Annotated[str, Field(min_length=12, max_length=72)]
    timezone: str = 'Australia/Melbourne'
    @field_validator('password')
    @classmethod
    def password_bytes(cls, value):
        if len(value.encode()) > 72:
            raise ValueError('Password must be at most 72 UTF-8 bytes')
        return value
    _timezone = field_validator('timezone')(validate_timezone)

class Venue(StrictModel):
    name: Text
    timezone: str
    openTime: Annotated[str, Field(pattern=r'^([01]\d|2[0-3]):[0-5]\d$')]
    closeTime: Annotated[str, Field(pattern=r'^([01]\d|2[0-3]):[0-5]\d$')]
    capacity: Annotated[int, Field(ge=1, le=500)]
    maxPartySize: Annotated[int, Field(ge=1, le=50)]
    published: bool
    _timezone = field_validator('timezone')(validate_timezone)
    @model_validator(mode='after')
    def hours(self):
        if self.closeTime <= self.openTime:
            raise ValueError('Closing time must follow opening time; overnight service is not supported in this pilot')
        if self.maxPartySize > self.capacity:
            raise ValueError('Party limit cannot exceed venue capacity')
        return self

class Booking(StrictModel):
    requestId: UUID
    guestName: Text
    guestEmail: EmailStr
    guestPhone: Annotated[str, Field(max_length=40)] = ''
    partySize: Annotated[int, Field(ge=1, le=50)]
    date: date
    time: time
    specialRequests: Annotated[str, Field(max_length=1000)] = ''
    @field_validator('time')
    @classmethod
    def minute_precision(cls, value):
        if value.tzinfo or value.second or value.microsecond:
            raise ValueError('Use a venue-local time in hours and minutes')
        return value

async def owner(user=Depends(get_user)):
    if user.get('role') != 'owner' or not product.is_booking_account(user.get('businessId')):
        raise HTTPException(403, 'A Booking product owner account is required')
    return user

def snapshot(account):
    return {'businessId': account['_id'], 'venue': account['venue'], 'products': account['products'],
            'canWrite': product.trial_open(account), 'billingAvailable': False,
            'guestPath': '/book/v/' + account['_id']}

@router.get('/availability')
async def availability():
    import os
    return {'signupEnabled': os.environ.get('BOOKING_PRODUCT_SIGNUP_ENABLED', 'false').lower() == 'true',
            'trialDays': 14, 'billingAvailable': False}

@router.post('/signup', status_code=201)
async def signup(data: Signup, response: Response):
    from routes.auth import create_access_token, create_refresh_token, _set_tokens
    user = await product.signup(data)
    token = create_access_token(user['id'], user['email'], user['role'], user['businessId'])
    _set_tokens(response, token, create_refresh_token(user['id']))
    return {'token': token, 'businessId': user['businessId']}

@router.get('/account')
async def account(user=Depends(owner)):
    return snapshot(await product.account_for(user['businessId']))

@router.put('/venue')
async def venue(data: Venue, user=Depends(owner)):
    return snapshot(await product.save_venue(user['businessId'], data))

@router.post('/cancel')
async def cancel(user=Depends(owner)):
    return snapshot(await product.cancel(user['businessId']))

@router.get('/reservations')
async def reservations(day: date, user=Depends(owner)):
    return await db.reservations.find({'businessId': user['businessId'], 'product': 'booking',
        'date': day.isoformat()}, {'_id': 0, 'requestFingerprint': 0}).sort('time', 1).to_list(500)

@router.get('/export')
async def export(user=Depends(owner)):
    from fastapi.encoders import jsonable_encoder
    # Read access intentionally survives cancellation; JSON avoids spreadsheet formula injection.
    docs = await db.reservations.find({'businessId': user['businessId'], 'product': 'booking'},
        {'_id': 0, 'requestFingerprint': 0}).limit(10001).to_list(10001)
    if len(docs) > 10000:
        raise HTTPException(409, 'Contact support for an export above 10,000 bookings.')
    return jsonable_encoder({'venue': (await product.account_for(user['businessId']))['venue'], 'reservations': docs})

@router.post('/reservations', status_code=201)
async def create(data: Booking, user=Depends(owner)):
    return await product.book(user['businessId'], data)

@router.post('/reservations/{reservation_id}/cancel')
async def cancel_reservation(reservation_id: str, user=Depends(owner)):
    from services import reservation_store
    # Even an expired trial can cancel existing commitments. No guest money is taken in this pilot.
    result = await reservation_store.update_one({'businessId': user['businessId'], 'id': reservation_id,
        'product': 'booking'}, {'$set': {'status': 'cancelled', 'updatedAt': product.now().isoformat()}})
    if not result.matched_count: raise HTTPException(404, 'Booking not found')
    return {'status': 'cancelled'}

@router.get('/public/{business_id}')
async def public_venue(business_id: str):
    account = await product.account_for(business_id)
    if not product.trial_open(account) or not account['venue']['published']:
        raise HTTPException(404, 'Booking page is not available')
    return account['venue']

@router.post('/public/{business_id}', status_code=201)
async def public_book(business_id: str, data: Booking):
    return await product.book(business_id, data, guest=True)
