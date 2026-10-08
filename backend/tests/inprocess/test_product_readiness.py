"""Production actions must respect tenant boundaries and report real outcomes."""
import asyncio
import uuid

import pytest

from database import db
from services import bookings_partner_client as mirror
from tests.inprocess.conftest import req


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture
def draft(client, owner_headers):
    account = req(client, 'POST', '/api/social/accounts', headers=owner_headers,
                  json={'platform': 'instagram', 'handle': 'planning_' + uuid.uuid4().hex})
    assert account.status_code == 200
    response = req(client, 'POST', '/api/social/posts', headers=owner_headers, json={
        'platform': 'instagram', 'postType': 'post', 'caption': 'Draft to keep', 'status': 'draft',
    })
    assert response.status_code == 200
    yield response.json()
    run(db.social_posts.delete_one({'id': response.json()['id']}))
    run(db.social_accounts.delete_one({'id': account.json()['id']}))


def test_unavailable_publisher_cannot_claim_success_or_change_draft(client, owner_headers, draft):
    response = req(client, 'POST', f"/api/social/posts/{draft['id']}/publish", headers=owner_headers)
    assert response.status_code == 503
    stored = run(db.social_posts.find_one({'id': draft['id']}))
    assert stored['status'] == 'draft'
    assert not stored.get('publishedAt')


@pytest.mark.parametrize('status', ['published', 'failed'])
def test_client_cannot_forge_provider_status(client, owner_headers, draft, status):
    body = {'platform': 'instagram', 'postType': 'post', 'caption': 'Forgery', 'status': status}
    assert req(client, 'POST', '/api/social/posts', headers=owner_headers, json=body).status_code == 400
    assert req(client, 'PATCH', f"/api/social/posts/{draft['id']}", headers=owner_headers,
               json={'status': status}).status_code == 400


def test_old_stub_publications_are_displayed_as_simulated(client, owner_headers, draft):
    run(db.social_posts.update_one({'id': draft['id']}, {'$set': {
        'status': 'published', 'publishProvider': 'stub', 'publishedAt': '2026-01-01',
    }}))
    rows = req(client, 'GET', '/api/social/posts', headers=owner_headers).json()
    row = next(p for p in rows if p['id'] == draft['id'])
    assert row['status'] == 'simulated' and row['publishedAt'] is None
    published = req(client, 'GET', '/api/social/posts?status=published', headers=owner_headers).json()
    assert all(p['id'] != draft['id'] for p in published)


def configure(monkeypatch):
    for key, value in {'API_URL': 'https://bookings.example.test', 'API_KEY': 'test-value',
                       'VENUE_ID': 'venue-a', 'BUSINESS_ID': 'business-a'}.items():
        monkeypatch.setenv('NUA_BOOKINGS_' + key, value)


def test_mirror_requires_explicit_business_mapping(monkeypatch):
    configure(monkeypatch)
    assert mirror.enabled('business-a')
    assert not mirror.enabled('business-b')
    assert not mirror.enabled(None)
    monkeypatch.delenv('NUA_BOOKINGS_BUSINESS_ID')
    assert not mirror.enabled('business-a')


def test_foreign_or_unowned_reservations_never_enqueue(monkeypatch):
    from services import reservation_store
    configure(monkeypatch)
    async def scenario():
        for business_id in [None, '', 'business-b']:
            await reservation_store._enqueue({'id': 'foreign', 'businessId': business_id}, False, None)
        assert await db.booking_sync_outbox.count_documents({'reservationId': 'foreign'}) == 0
    run(scenario())


def test_new_snapshot_invalidates_old_delivery_ack(monkeypatch):
    from services import reservation_store, booking_sync
    configure(monkeypatch)
    reservation = {'id': uuid.uuid4().hex, 'businessId': 'business-a', 'date': '2027-01-01', 'time': '18:00'}

    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def put(self, url, json, headers):
            import httpx
            assert json['version'] == 1
            await reservation_store._enqueue(reservation, True, None)
            return httpx.Response(200)
    monkeypatch.setattr(booking_sync.httpx, 'AsyncClient', Client)
    async def scenario():
        await reservation_store._enqueue(reservation, False, None)
        await booking_sync.deliver_next()
        job = await db.booking_sync_outbox.find_one({'reservationId': reservation['id']})
        assert job['status'] == 'pending' and job['version'] == 2
        assert job['snapshot']['deleted'] is True
        await db.booking_sync_outbox.delete_one({'_id': job['_id']})
    run(scenario())
