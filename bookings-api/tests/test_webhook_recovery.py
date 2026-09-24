import asyncio
from datetime import timedelta

import httpx
import pytest
from mongomock_motor import AsyncMongoMockClient

import webhooks


@pytest.fixture
def outbox(monkeypatch):
    database = AsyncMongoMockClient().webhook_recovery
    monkeypatch.setattr(webhooks, 'db', database)
    monkeypatch.setattr(webhooks, 'CAPTURE', None)
    return database.webhook_outbox


def transport(monkeypatch, status=200, error=None, calls=None):
    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, json):
            if calls is not None:
                calls.append(json['id'])
            if error:
                raise error
            return httpx.Response(status)
    monkeypatch.setattr(webhooks.httpx, 'AsyncClient', Client)


def enqueue():
    return webhooks.emit({'id': 'partner', 'webhook_url': 'https://example.test/hook'},
                         'booking.created', {'id': 'booking'})


def test_pending_event_survives_enqueue_without_a_running_worker(outbox, monkeypatch):
    calls = []
    transport(monkeypatch, calls=calls)

    async def scenario():
        await enqueue()
        assert await outbox.count_documents({'status': 'pending'}) == 1
        results = await asyncio.gather(webhooks.deliver_next(), webhooks.deliver_next())
        assert sorted(results) == [False, True]
        assert len(calls) == 1
        assert await outbox.count_documents({'status': 'delivered', 'attempts': 1}) == 1
    asyncio.run(scenario())


def test_retry_backoff_then_success_keeps_event_identity(outbox, monkeypatch):
    calls = []
    transport(monkeypatch, status=503, calls=calls)

    async def scenario():
        await enqueue()
        await webhooks.deliver_next()
        doc = await outbox.find_one({})
        assert doc['status'] == 'retrying'
        assert not await webhooks.deliver_next()
        await outbox.update_one({}, {'$set': {'next_attempt_at': '2000'}})
        transport(monkeypatch, calls=calls)
        assert await webhooks.deliver_next()
        assert calls == [doc['id'], doc['id']]
        assert (await outbox.find_one({}))['status'] == 'delivered'
    asyncio.run(scenario())


def test_worker_recovers_expired_claim(outbox, monkeypatch):
    transport(monkeypatch)

    async def scenario():
        await enqueue()
        await outbox.update_one({}, {'$set': {
            'status': 'delivering', 'attempts': 1, 'claim_token': 'dead-worker',
            'lease_until': (webhooks._now() - timedelta(seconds=1)).isoformat(),
        }})
        assert await webhooks.deliver_next()
        doc = await outbox.find_one({})
        assert doc['status'] == 'delivered' and doc['attempts'] == 2
        assert 'claim_token' not in doc
    asyncio.run(scenario())


def test_unknown_final_attempt_is_retained_for_reconciliation(outbox):
    async def scenario():
        await enqueue()
        await outbox.update_one({}, {'$set': {
            'status': 'delivering', 'attempts': webhooks.MAX_ATTEMPTS,
            'lease_until': '2000', 'claim_token': 'dead-worker',
        }})
        assert not await webhooks.deliver_next()
        doc = await outbox.find_one({})
        assert doc['status'] == 'failed'
        assert doc['last_error'] == 'delivery_outcome_unknown'
    asyncio.run(scenario())


@pytest.mark.parametrize('status', [400, 401, 403, 404])
def test_permanent_http_failure_is_not_retried(outbox, monkeypatch, status):
    transport(monkeypatch, status=status)

    async def scenario():
        await enqueue()
        await webhooks.deliver_next()
        assert (await outbox.find_one({}))['status'] == 'failed'
    asyncio.run(scenario())


def test_network_failure_exhausts_retry_budget_without_losing_record(outbox, monkeypatch):
    transport(monkeypatch, error=httpx.ConnectError('unreachable'))

    async def scenario():
        await enqueue()
        for _ in range(webhooks.MAX_ATTEMPTS):
            await outbox.update_one({}, {'$set': {'next_attempt_at': '2000'}})
            assert await webhooks.deliver_next()
        doc = await outbox.find_one({})
        assert doc['status'] == 'failed'
        assert doc['attempts'] == webhooks.MAX_ATTEMPTS
        assert not await webhooks.deliver_next()
    asyncio.run(scenario())
