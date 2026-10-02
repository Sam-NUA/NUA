"""Daily automatic backup restore-drill (services/backup_scheduler.py) and
its status endpoint — the scheduled analog of the existing manual
POST /ops/backup/drill."""
import asyncio
import pytest
from unittest.mock import AsyncMock

from conftest import req


@pytest.fixture(autouse=True)
def private_backup_store(monkeypatch):
    from services import durable_backups
    async def retain(archive, business_id=None):
        return {"id": "scheduler-test", "verified": True}, archive
    monkeypatch.setattr(durable_backups, "retain", AsyncMock(side_effect=retain))


def test_force_drill_now_records_a_passing_drill():
    from services import backup_scheduler
    from database import db

    result = asyncio.get_event_loop().run_until_complete(backup_scheduler.force_drill_now())
    assert result["ok"] is True
    assert "report" in result

    today = asyncio.get_event_loop().run_until_complete(
        db.backup_drills.find_one({"date": result["date"]}, {"_id": 0}))
    assert today["ok"] is True


def test_drill_status_endpoint_reports_the_last_drill(client, owner_headers):
    from services import backup_scheduler
    asyncio.get_event_loop().run_until_complete(backup_scheduler.force_drill_now())

    r = req(client, "GET", "/api/ops/backup/drill-status", headers=owner_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] is True
    assert body["lastDrill"]["ok"] is True


def test_drill_status_requires_owner(anon):
    assert req(anon, "GET", "/api/ops/backup/drill-status").status_code == 401
