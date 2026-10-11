"""services/observability.py's check_health() reported ashScheduler/
coursingScheduler from the LOCAL in-process scheduler loop's is_running() —
correctly, intentionally False on Vercel (server.py only starts those loops
when not IS_VERCEL; Vercel Cron hits /api/cron/* directly instead). That
made GET /api/health report "degraded" permanently on Vercel regardless of
whether Cron invocations were actually succeeding, and said nothing about
Cron's real health either way. On Vercel, check_health now reads
cron_jobs.last_run's own claim record instead.
"""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from conftest import req
from database import db


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture
def on_vercel(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    yield
    _run(db.scheduler_locks.delete_many({"_id": {"$in": ["ash-hourly", "coursing-tick"]}}))


def test_health_is_not_degraded_on_vercel_when_cron_has_recently_run(client, on_vercel):
    now_iso = datetime.now(timezone.utc).isoformat()
    _run(db.scheduler_locks.update_one(
        {"_id": "ash-hourly"}, {"$set": {"_id": "ash-hourly", "claimedAt": now_iso}}, upsert=True))
    _run(db.scheduler_locks.update_one(
        {"_id": "coursing-tick"}, {"$set": {"_id": "coursing-tick", "claimedAt": now_iso}}, upsert=True))

    r = req(client, "GET", "/api/health")
    assert r.status_code == 200, r.text[:300]
    body = r.json()
    assert body["checks"]["ashCron"]["ok"] is True
    assert body["checks"]["coursingCron"]["ok"] is True
    assert "ashScheduler" not in body["checks"], "Vercel mode must not report the local-loop check at all"
    assert body["status"] == "ok"


def test_health_flags_coursing_cron_as_unhealthy_once_stale_on_vercel(client, on_vercel):
    stale_iso = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    _run(db.scheduler_locks.update_one(
        {"_id": "ash-hourly"}, {"$set": {"_id": "ash-hourly", "claimedAt": datetime.now(timezone.utc).isoformat()}},
        upsert=True))
    _run(db.scheduler_locks.update_one(
        {"_id": "coursing-tick"}, {"$set": {"_id": "coursing-tick", "claimedAt": stale_iso}}, upsert=True))

    r = req(client, "GET", "/api/health")
    assert r.status_code == 200, r.text[:300]
    body = r.json()
    assert body["checks"]["coursingCron"]["ok"] is False
    assert body["status"] == "degraded"


def test_health_does_not_report_degraded_for_a_cron_job_never_yet_observed(client, on_vercel):
    """A fresh deployment with no claim history yet is "unknown", not
    "unhealthy" — matches this check's existing not-False-means-ok
    convention for every other "ok: None" case."""
    r = req(client, "GET", "/api/health")
    assert r.status_code == 200, r.text[:300]
    body = r.json()
    assert body["checks"]["ashCron"]["ok"] is None
    assert body["checks"]["coursingCron"]["ok"] is None
    assert body["status"] == "ok"


def test_health_uses_local_scheduler_checks_when_not_on_vercel(client, monkeypatch):
    monkeypatch.delenv("VERCEL", raising=False)
    r = req(client, "GET", "/api/health")
    assert r.status_code == 200, r.text[:300]
    body = r.json()
    assert "ashScheduler" in body["checks"]
    assert "coursingScheduler" in body["checks"]
    assert "ashCron" not in body["checks"]
