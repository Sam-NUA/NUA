import uuid
from datetime import datetime, timedelta, timezone
import pytest
from database import db
from services import booking_product

@pytest.fixture
def pilot(client, monkeypatch):
    monkeypatch.setenv('BOOKING_PRODUCT_SIGNUP_ENABLED', 'true')
    async def execute(operation): return await operation(None)
    monkeypatch.setattr(booking_product, 'transaction', execute)
    client.cookies.clear()
    def register():
        r = client.post('/api/booking-product/signup', json={'name': 'Pilot Owner',
            'venueName': 'Test Venue', 'email': f'{uuid.uuid4().hex}@example.com',
            'password': 'test-pilot-password', 'timezone': 'Australia/Melbourne'})
        assert r.status_code == 201, r.text
        client.cookies.clear()
        return r.json(), {'Authorization': 'Bearer ' + r.json()['token']}
    return register

def payload(**kw):
    return {'requestId': str(uuid.uuid4()), 'guestName': 'Guest', 'guestEmail': 'guest@example.com',
            'partySize': 2, 'date': (datetime.now(timezone.utc) + timedelta(days=2)).date().isoformat(),
            'time': '18:00', **kw}

def publish(client, headers, **kw):
    venue = client.get('/api/booking-product/account', headers=headers).json()['venue']
    venue.update(published=True, **kw)
    r = client.put('/api/booking-product/venue', headers=headers, json=venue)
    assert r.status_code == 200, r.text
    return r.json()

def test_pilot_off_by_default(anon, monkeypatch):
    monkeypatch.delenv('BOOKING_PRODUCT_SIGNUP_ENABLED', raising=False)
    assert anon.get('/api/booking-product/availability').json()['signupEnabled'] is False
    r = anon.post('/api/booking-product/signup', json={'name':'Owner', 'venueName':'Venue',
        'email':'off@example.com', 'password':'test-pilot-password'})
    assert r.status_code == 503

def test_full_booking_lifecycle(client, pilot):
    account, headers = pilot()
    assert client.portal.call(db.tenant_licenses.count_documents, {'tenantId':account['businessId']}) == 0
    state = publish(client, headers)
    assert state['products']['booking']['state'] == 'trialing'
    url = '/api/booking-product/public/' + account['businessId']
    booking = payload(); r = client.post(url, json=booking)
    assert r.status_code == 201, r.text
    assert set(r.json()) == {'id','status','date','time'}
    assert client.post(url, json=booking).json() == r.json()
    assert client.post(url, json={**booking, 'guestName':'Different'}).status_code == 409
    listed = client.get('/api/booking-product/reservations', params={'day':booking['date']}, headers=headers)
    assert len(listed.json()) == 1
    client.portal.call(db.product_accounts.update_one, {'_id':account['businessId']}, {'$set': {'products.loyalty': {'state':'active'}}})
    cancelled = client.post('/api/booking-product/cancel', headers=headers)
    assert cancelled.json()['products']['loyalty']['state'] == 'active'
    assert client.post(url, json=payload()).status_code == 403
    assert client.get(url).status_code == 404
    assert client.get('/api/booking-product/export', headers=headers).status_code == 200
    assert client.post('/api/booking-product/reservations/'+r.json()['id']+'/cancel', headers=headers).status_code == 200

def test_owner_cannot_access_pos_or_forge_tenant(client, pilot, monkeypatch):
    account, headers = pilot(); monkeypatch.setenv('LICENSE_ENFORCEMENT_ENABLED','false')
    for method, path in [('GET','/api/transactions'),('POST','/api/auth/register'),('GET','/api/customers'),('POST','/api/products'),('GET','/api/license/me'),('GET','/api/business/default')]:
        r = client.request(method, path, headers={**headers, 'X-Tenant-Id':'default','X-Business-Id':'default'},json={})
        assert r.status_code == 403, (path,r.text)
    assert client.post('/api/booking-product/signup', json={'name':'bad','venueName':'bad',
        'email':'bad@example.com','password':'test-pilot-password','businessId':'default'}).status_code == 422
    assert client.post('/api/online/orders', json={'business':account['businessId'], 'items':[{'productId':'not-a-product','quantity':1}]}).status_code == 404

def test_tenant_isolation_capacity_expiry(client, pilot):
    a, ha = pilot(); b, hb = pilot()
    publish(client, ha, capacity=2, maxPartySize=2); publish(client, hb)
    item = payload(); r = client.post('/api/booking-product/reservations', headers=ha, json=item)
    assert r.status_code == 201, r.text
    assert client.post('/api/booking-product/reservations', headers=ha,json=payload(time='18:30')).status_code == 409
    assert client.post('/api/booking-product/reservations', headers=hb,json=payload()).status_code == 201
    assert client.post('/api/booking-product/reservations/'+r.json()['id']+'/cancel',headers=hb).status_code == 404
    docs=client.get('/api/booking-product/export',headers=hb).json()['reservations']
    assert all(d['businessId']==b['businessId'] for d in docs)
    client.portal.call(db.product_accounts.update_one,{'_id':a['businessId']},{'$set':{'products.booking.trialEndsAt': '2000-01-01T00:00:00+00:00'}})
    assert client.get('/api/booking-product/account',headers=ha).json()['canWrite'] is False
    assert client.post('/api/booking-product/reservations',headers=ha,json=payload(time='20:00')).status_code == 403
    assert client.get('/api/booking-product/export',headers=ha).status_code == 200

def test_input_and_entitlement_mutation_rejected(client,pilot):
    a,h=pilot();state=publish(client,h)
    assert client.put('/api/booking-product/venue',headers=h,json={**state['venue'],'products':{'pos':{'state':'active'}}}).status_code==422
    assert client.put('/api/booking-product/venue',headers=h,json={**state['venue'],'timezone':'Bad/Zone'}).status_code==422
    assert client.put('/api/booking-product/venue',headers=h,json={**state['venue'],'closeTime':'01:00'}).status_code==422
    assert client.post('/api/booking-product/reservations',headers=h,json=payload(depositPaid=True)).status_code==422
    assert client.post('/api/booking-product/reservations',headers=h,json=payload(time='12:00')).status_code==422
    assert client.post('/api/booking-product/reservations',headers=h,json=payload(date='2000-01-01')).status_code==422

def test_cancel_serializes_with_inflight_booking(client, pilot, monkeypatch):
    import asyncio
    from services import reservation_store
    from routes.booking_product import Booking
    a,h = pilot(); publish(client,h)
    original = reservation_store.insert_one
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        async def paused(*args, **kwargs):
            entered.set()
            await release.wait()
            return await original(*args, **kwargs)
        monkeypatch.setattr(reservation_store, 'insert_one', paused)
        pending = asyncio.create_task(booking_product.book(a['businessId'], Booking(**payload())))
        await asyncio.wait_for(entered.wait(), 2)
        cancelling = asyncio.create_task(booking_product.cancel(a['businessId']))
        await asyncio.sleep(.05)
        assert not cancelling.done()
        release.set()
        await pending
        result = await cancelling
        assert result['products']['booking']['state'] == 'cancelled'
        with pytest.raises(Exception) as exc:
            await booking_product.book(a['businessId'], Booking(**payload()))
        assert exc.value.status_code == 403
    client.portal.call(scenario)

def test_scoped_backup_preserves_product_account(client, pilot):
    import io, tarfile
    from bson import json_util
    from services import backup
    a,h=pilot(); b,_=pilot()
    async def scenario():
        archive = await backup.create_backup(business_id=a['businessId'])
        with tarfile.open(fileobj=io.BytesIO(archive), mode='r:gz') as tar:
            rows = json_util.loads(tar.extractfile('product_accounts.json').read())
        assert len(rows) == 1
        assert rows[0]['_id'] == a['businessId']
        assert rows[0]['products']['booking']['state'] == 'trialing'
    client.portal.call(scenario)
