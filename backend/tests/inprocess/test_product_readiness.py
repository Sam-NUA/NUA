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


def test_foreign_or_unowned_reservations_never_schedule_mirror(monkeypatch):
    configure(monkeypatch)

    def fail_if_scheduled(coro):
        coro.close()
        pytest.fail('unauthorized mirror scheduled')
    monkeypatch.setattr(mirror.asyncio, 'create_task', fail_if_scheduled)
    for business_id in [None, '', 'business-b']:
        reservation = {'id': 'foreign', 'businessId': business_id, 'bookingsPlatformId': 'remote'}
        mirror.mirror_reservation_created(reservation)
        mirror.mirror_reservation_status(reservation, 'cancelled')


def test_mirror_sends_stable_retry_key_and_scopes_remote_id_write(monkeypatch):
    configure(monkeypatch)
    calls, tasks = [], []
    real_create_task = asyncio.create_task

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, json, headers):
            import httpx
            calls.append(headers)
            return httpx.Response(200, json={'id': 'remote-a'})

    monkeypatch.setattr(mirror.httpx, 'AsyncClient', Client)
    monkeypatch.setattr(mirror.asyncio, 'create_task', lambda coro: tasks.append(real_create_task(coro)))

    async def scenario():
        reservation = {'id': uuid.uuid4().hex, 'businessId': 'business-a',
                       'date': '2027-01-01', 'time': '18:00'}
        await db.reservations.insert_one(dict(reservation))
        await db.reservations.insert_one({**reservation, 'businessId': 'business-b'})
        try:
            mirror.mirror_reservation_created(reservation)
            await asyncio.gather(*tasks)
            assert calls[0]['Idempotency-Key'] == 'counter:business-a:' + reservation['id']
            own = await db.reservations.find_one({'id': reservation['id'], 'businessId': 'business-a'})
            other = await db.reservations.find_one({'id': reservation['id'], 'businessId': 'business-b'})
            assert own['bookingsPlatformId'] == 'remote-a'
            assert 'bookingsPlatformId' not in other
        finally:
            await db.reservations.delete_many({'id': reservation['id']})
    run(scenario())
