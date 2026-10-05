import uuid
import pytest
from database import db
from services import loyalty_product as product

@pytest.fixture
def loyalty(client, monkeypatch):
    monkeypatch.setenv('LOYALTY_PRODUCT_SIGNUP_ENABLED', 'true')
    async def operation(fn): return await fn(None)
    monkeypatch.setattr(product, 'transaction', operation)
    client.cookies.clear()
    def register():
        r = client.post('/api/loyalty-product/signup', json={'name':'Owner','venueName':'Club','email':uuid.uuid4().hex+'@example.com','password':'owner-pilot-password'})
        assert r.status_code == 201, r.text
        client.cookies.clear()
        h={'Authorization':'Bearer '+r.json()['token']}
        a=client.get('/api/loyalty-product/account',headers=h).json(); p=a['program'];p['published']=True
        r=client.put('/api/loyalty-product/program',headers=h,json=p)
        assert r.status_code==200,r.text
        return a['businessId'],h
    return register

def join(client,bid):
    body={'name':'Member One','email':uuid.uuid4().hex+'@example.com','password':'member-pilot-password','acceptTerms':True,'marketingConsent':False}
    base='/api/loyalty-product/portal/'+bid
    r=client.post(base+'/join',json=body); assert r.status_code==201,r.text
    h={'Authorization':'Bearer '+r.json()['token']}
    r=client.get(base+'/me',headers=h); assert r.status_code==200,r.text
    return base,h,r.json()['member'],body

def reward(client,h,points=100):
    rid=str(uuid.uuid4());r=client.put('/api/loyalty-product/rewards/'+rid,headers=h,json={'name':'Coffee','description':'One coffee','points':points,'active':True})
    assert r.status_code==200,r.text
    return rid

def award(client,h,mid,points=200):
    body={'requestId':str(uuid.uuid4()),'points':points,'reason':'Receipt 100'}
    r=client.post('/api/loyalty-product/members/'+mid+'/points',headers=h,json=body);assert r.status_code==200,r.text
    return body,r.json()

def test_disabled_registration(anon,monkeypatch):
    monkeypatch.delenv('LOYALTY_PRODUCT_SIGNUP_ENABLED',raising=False)
    assert anon.get('/api/loyalty-product/availability').json()['signupEnabled'] is False
    assert anon.post('/api/loyalty-product/signup',json={'name':'Owner','venueName':'Club','email':'closed@example.com','password':'owner-pilot-password'}).status_code==503

def test_ledger_redemption_refund_and_password_lifecycle(client,loyalty):
    bid,h=loyalty();base,m,member,credentials=join(client,bid)
    assert client.portal.call(db.tenant_licenses.count_documents,{'tenantId':bid})==0
    assert member['points']==0 and 'passwordHash' not in member
    body,result=award(client,h,member['id'],600);path='/api/loyalty-product/members/'+member['id']+'/points'
    assert client.post(path,headers=h,json=body).json()==result
    assert client.post(path,headers=h,json={**body,'points':601}).status_code==409
    rid=reward(client,h);claim={'requestId':str(uuid.uuid4())};path=base+'/rewards/'+rid+'/claim'
    r=client.post(path,headers=m,json=claim);assert r.status_code==200,r.text
    assert client.post(path,headers=m,json=claim).json()==r.json()
    state=client.get(base+'/me',headers=m).json()
    assert state['member']['points']==500 and state['member']['tier']=='Silver' and len(state['ledger'])==2
    resolve='/api/loyalty-product/redemptions/'+r.json()['redemptionId']+'/resolve'
    for _ in range(2): assert client.post(resolve,headers=h,json={'action':'cancel'}).status_code==200
    state=client.get(base+'/me',headers=m).json()
    assert state['member']['points']==600 and state['member']['earnedPoints']==600 and len(state['ledger'])==3
    assert client.post(resolve,headers=h,json={'action':'fulfil'}).status_code==409
    r=client.put(base+'/preferences',headers=m,json={'marketingConsent':True,'currentPassword':credentials['password'],'newPassword':'changed-member-password'})
    assert r.json()['signInAgain'] is True
    assert client.get(base+'/me',headers=m).status_code==401
    r=client.post(base+'/login',json={'email':credentials['email'],'password':'changed-member-password'}); assert r.status_code==200
    new={'Authorization':'Bearer '+r.json()['token']}
    assert client.get(base+'/me',headers=new).json()['member']['marketingConsent'] is True
    assert client.post(base+'/logout',headers=new).status_code==200
    assert client.get(base+'/me',headers=new).status_code==401

def test_tenant_and_member_isolation(client,loyalty):
    a,ha=loyalty();b,hb=loyalty();pa,ma,one,_=join(client,a);pb,mb,two,_=join(client,b)
    for path in ['/api/customers','/api/transactions','/api/booking-product/account','/api/license/me']:
        assert client.get(path,headers={**ha,'X-Business-Id':'default'}).status_code==403
    assert client.get(pb+'/me',headers=ma).status_code==401
    assert client.get(pa+'/me',headers=ha).status_code==401
    assert client.get('/api/loyalty-product/members',headers=ma).status_code in (401,403)
    assert client.get('/api/loyalty-product/members/'+one['id'],headers=hb).status_code==404
    award(client,ha,one['id']);data=client.get(pb+'/export',headers=mb).json()
    assert len(data['members'])==1 and data['members'][0]['id']==two['id'] and data['ledger']==[]
    assert 'passwordHash' not in str(data)
    assert client.post('/api/online/orders',json={'business':a,'items':[{'productId':'x','quantity':1}]}).status_code==404
    assert client.post(pa+'/join',json={'name':'Intruder','email':'i@example.com','password':'member-pilot-password','acceptTerms':True,'points':100}).status_code==422

def test_cancel_preserves_pending_commitments(client,loyalty):
    bid,h=loyalty();base,m,member,_=join(client,bid);award(client,h,member['id']);rid=reward(client,h)
    r=client.post(base+'/rewards/'+rid+'/claim',headers=m,json={'requestId':str(uuid.uuid4())})
    client.portal.call(db.product_accounts.update_one,{'_id':bid},{'$set':{'products.booking':{'state':'active'}}})
    assert client.post('/api/loyalty-product/cancel',headers=h).json()['products']['booking']['state']=='active'
    assert client.get(base).json()['canJoin'] is False
    assert client.get(base+'/export',headers=m).status_code==200
    assert client.get('/api/loyalty-product/export',headers=h).status_code==200
    assert client.post(base+'/rewards/'+rid+'/claim',headers=m,json={'requestId':str(uuid.uuid4())}).status_code==403
    assert client.post('/api/loyalty-product/redemptions/'+r.json()['redemptionId']+'/resolve',headers=h,json={'action':'fulfil'}).status_code==200

def test_balance_pause_and_expiry(client,loyalty):
    bid,h=loyalty();base,m,member,_=join(client,bid);rid=reward(client,h)
    assert client.post(base+'/rewards/'+rid+'/claim',headers=m,json={'requestId':str(uuid.uuid4())}).status_code==409
    assert client.put('/api/loyalty-product/rewards/'+rid,headers=h,json={'name':'Bad','points':-1}).status_code==422
    for status in ('paused','active'):
        assert client.put('/api/loyalty-product/members/'+member['id']+'/status',headers=h,json={'status':status}).status_code==200
        assert client.get(base+'/me',headers=m).status_code==401
    client.portal.call(db.product_accounts.update_one,{'_id':bid},{'$set':{'products.loyalty.trialEndsAt':'2000-01-01T00:00:00+00:00'}})
    assert client.get('/api/loyalty-product/account',headers=h).json()['canWrite'] is False
    assert client.put('/api/loyalty-product/rewards/'+rid,headers=h,json={'name':'Coffee','points':50}).status_code==403

def test_export_and_scoped_backup(client,loyalty):
    import io,tarfile
    from bson import json_util
    from services.backup import create_backup
    bid,h=loyalty();base,m,one,_=join(client,bid);_,_,two,_=join(client,bid)
    award(client,h,one['id']);award(client,h,two['id'])
    data=client.get(base+'/export',headers=m).json();assert len(data['members'])==1 and len(data['ledger'])==1
    assert data['ledger'][0]['memberId']==one['id']
    async def backup(): return await create_backup(business_id=bid)
    archive=client.portal.call(backup)
    with tarfile.open(fileobj=io.BytesIO(archive),mode='r:gz') as tar:
        rows=json_util.loads(tar.extractfile('loyalty_product_ledger.json').read());assert len(rows)==2 and all(r['businessId']==bid for r in rows)

def test_shared_rate_limit(client,loyalty):
    bid,_=loyalty()
    for _ in range(30): assert client.get('/api/loyalty-product/portal/'+bid).status_code==200
    assert client.get('/api/loyalty-product/portal/'+bid,headers={'X-Forwarded-For':'1.2.3.4'}).status_code==429
