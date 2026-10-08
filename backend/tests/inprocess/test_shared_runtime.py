import asyncio
import uuid
from unittest.mock import AsyncMock

from database import db
from services.shared_runtime import SharedRuntime
from conftest import req


def test_feed_cursor_survives_new_instance_and_is_tenant_scoped():
    async def run():
        tenant = uuid.uuid4().hex
        first = SharedRuntime(db)
        start = await first.read(tenant)
        await first.publish(tenant, {"type": "sale.completed"})
        cold = SharedRuntime(db)
        result = await cold.read(tenant, start["cursor"])
        assert result["events"] == [{"type": "sale.completed"}]
        assert not (await cold.read(tenant, result["cursor"]))["events"]
        assert not (await cold.read("other-" + tenant, "empty"))["events"]
        assert (await cold.read(tenant, "evicted-cursor"))["reset"]
    asyncio.get_event_loop().run_until_complete(run())


def test_forged_tenant_header_does_not_reset_limit(client, owner_headers):
    import server
    async def fill():
        import jwt, os, time
        payload = jwt.decode(owner_headers["Authorization"][7:], os.environ["JWT_SECRET"], algorithms=["HS256"])
        key = f"user:{payload['businessId']}:{payload['sub']}"
        for _ in range(120):
            await SharedRuntime(db).allow(key, 120, 60, time.time())
    client.portal.call(fill)
    response = client.get('/api/realtime/events', headers={**owner_headers, 'X-Tenant-Id': uuid.uuid4().hex})
    assert response.status_code == 429
    assert int(response.headers['Retry-After']) > 0


def test_shared_limiter_fails_closed(client, monkeypatch, owner_headers):
    monkeypatch.setattr(SharedRuntime, 'allow', AsyncMock(side_effect=RuntimeError('offline')))
    assert req(client, 'GET', '/api/realtime/events', headers=owner_headers).status_code == 503


def test_feed_requires_login_and_never_caches(anon, owner_headers):
    assert anon.get('/api/realtime/events').status_code == 401
    response = anon.get('/api/realtime/events', headers=owner_headers)
    assert response.status_code == 200
    assert response.headers['Cache-Control'] == 'private, no-store'
