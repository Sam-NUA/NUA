"""Vercel-cron entry points (routes/cron.py) and the concurrency claim they
rely on (services/cron_jobs.py) — these replace the perpetual in-process
loops on Vercel, where an idle instance can be retired between requests."""
import asyncio

from conftest import req


CRON_SECRET = "test-only-cron-secret"


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_try_claim_blocks_until_expiry_then_releases_immediately():
    from services import cron_jobs
    from database import db

    async def scenario():
        await db.scheduler_locks.delete_many({"_id": "unit-test-job"})
        assert await cron_jobs.try_claim("unit-test-job", ttl_seconds=60, owner_token="test-owner") is True
        # Still held — a second claim attempt must not also succeed.
        assert await cron_jobs.try_claim("unit-test-job", ttl_seconds=60) is False
        # Releasing frees it immediately, before the ttl would have.
        await cron_jobs.release("unit-test-job", "test-owner")
        assert await cron_jobs.try_claim("unit-test-job", ttl_seconds=60, owner_token="test-owner") is True
        await db.scheduler_locks.delete_many({"_id": "unit-test-job"})

    _run(scenario())


def test_try_claim_two_concurrent_callers_only_one_wins():
    from services import cron_jobs
    from database import db

    async def scenario():
        await db.scheduler_locks.delete_many({"_id": "unit-test-race"})
        results = await asyncio.gather(
            cron_jobs.try_claim("unit-test-race", ttl_seconds=60),
            cron_jobs.try_claim("unit-test-race", ttl_seconds=60),
        )
        assert sorted(results) == [False, True]
        await db.scheduler_locks.delete_many({"_id": "unit-test-race"})

    _run(scenario())


def test_cron_endpoints_reject_missing_or_wrong_secret(anon):
    for path in ("/api/cron/coursing-tick", "/api/cron/booking-sync-drain",
                 "/api/cron/backup-drill-check", "/api/cron/ash-hourly"):
        no_auth = req(anon, "GET", path)
        assert no_auth.status_code == 401, f"{path}: {no_auth.text[:200]}"
        wrong = req(anon, "GET", path, headers={"Authorization": "Bearer not-the-secret"})
        assert wrong.status_code == 401, f"{path}: {wrong.text[:200]}"


def test_coursing_tick_runs_once_then_is_claimed_by_a_second_call(anon):
    from database import db
    _run(db.scheduler_locks.delete_many({"_id": "coursing-tick"}))
    headers = {"Authorization": f"Bearer {CRON_SECRET}"}
    first = req(anon, "GET", "/api/cron/coursing-tick", headers=headers)
    assert first.status_code == 200, first.text[:200]
    assert first.json()["ran"] is True
    second = req(anon, "GET", "/api/cron/coursing-tick", headers=headers)
    assert second.status_code == 200
    assert second.json() == {"ran": False, "reason": "already claimed by another invocation"}
    _run(db.scheduler_locks.delete_many({"_id": "coursing-tick"}))


def test_booking_sync_drain_releases_its_lock_so_it_can_run_again_immediately(anon):
    from database import db
    _run(db.scheduler_locks.delete_many({"_id": "booking-sync-drain"}))
    headers = {"Authorization": f"Bearer {CRON_SECRET}"}
    first = req(anon, "GET", "/api/cron/booking-sync-drain", headers=headers)
    assert first.status_code == 200, first.text[:200]
    assert first.json()["ran"] is True
    # Unlike coursing-tick, this job releases its lock on success — a
    # back-to-back call must not be rejected as still-claimed.
    second = req(anon, "GET", "/api/cron/booking-sync-drain", headers=headers)
    assert second.status_code == 200
    assert second.json()["ran"] is True
    _run(db.scheduler_locks.delete_many({"_id": "booking-sync-drain"}))


def test_expired_invocation_cannot_release_new_owner_lease():
    from database import db
    from services import cron_jobs
    async def scenario():
        job = "fencing-test"
        await db.scheduler_locks.delete_one({"_id": job})
        assert await cron_jobs.try_claim(job, -1, owner_token="old")
        assert await cron_jobs.try_claim(job, 60, owner_token="new")
        await cron_jobs.release(job, "old")
        assert not await cron_jobs.try_claim(job, 60)
        await cron_jobs.release(job, "new")
        assert await cron_jobs.try_claim(job, 60)
    _run(scenario())


def test_cron_records_success_failure_and_recovery(anon, monkeypatch):
    from database import db
    from services import coursing_scheduler, cron_jobs
    headers = {"Authorization": f"Bearer {CRON_SECRET}"}
    async def broken():
        raise RuntimeError("private provider error must not be persisted")
    async def working():
        return 2
    _run(db.scheduler_locks.delete_one({"_id": "coursing-tick"}))
    monkeypatch.setattr(coursing_scheduler, "_tick_once", broken)
    failed = req(anon, "GET", "/api/cron/coursing-tick", headers=headers)
    assert failed.status_code == 500
    row = _run(cron_jobs.last_run("coursing-tick"))
    assert row["status"] == "failed" and row["lastFailureAt"]
    assert "lastSuccessAt" not in row
    assert row["lastErrorType"] == "RuntimeError"
    assert "private provider" not in str(row)
    _run(cron_jobs.release("coursing-tick", row["ownerToken"]))
    monkeypatch.setattr(coursing_scheduler, "_tick_once", working)
    assert req(anon, "GET", "/api/cron/coursing-tick", headers=headers).status_code == 200
    row = _run(cron_jobs.last_run("coursing-tick"))
    assert row["status"] == "succeeded" and row["lastSuccessAt"]
    assert row["lastErrorType"] is None
    _run(db.scheduler_locks.delete_one({"_id": "coursing-tick"}))


def test_stale_cron_owner_cannot_publish_success_or_failure():
    from services import cron_jobs
    from database import db
    async def scenario():
        job = "finish-fencing"
        assert await cron_jobs.try_claim(job, -1, owner_token="old")
        assert await cron_jobs.try_claim(job, 60, owner_token="new")
        assert not await cron_jobs.finish(job, "old")
        assert not await cron_jobs.finish(job, "old", error_type="RuntimeError")
        row = await cron_jobs.last_run(job)
        assert row["status"] == "running" and "lastSuccessAt" not in row
        assert await cron_jobs.finish(job, "new")
        await db.scheduler_locks.delete_one({"_id": job})
    _run(scenario())


def test_partial_hourly_failure_is_not_success(anon, monkeypatch):
    from services import nua_scheduler, cron_jobs
    from database import db
    async def partial():
        return {"businessesScanned": 2, "failures": 1}
    monkeypatch.setattr(nua_scheduler, "run_tick_once", partial)
    _run(db.scheduler_locks.delete_one({"_id": "ash-hourly"}))
    response = req(anon, "GET", "/api/cron/ash-hourly", headers={"Authorization": f"Bearer {CRON_SECRET}"})
    assert response.status_code == 500
    row = _run(cron_jobs.last_run("ash-hourly"))
    assert row["status"] == "failed" and "lastSuccessAt" not in row
    _run(db.scheduler_locks.delete_one({"_id": "ash-hourly"}))


def test_hourly_worker_preserves_caught_partial_failure(monkeypatch):
    from types import SimpleNamespace
    from services import nua_scheduler, predictive_signals, ops_signals
    class Rows:
        async def to_list(self, limit):
            return [{"id": "cron-test-business"}]
    monkeypatch.setattr(nua_scheduler, "db", SimpleNamespace(businesses=SimpleNamespace(find=lambda *a, **k: Rows())))
    async def broken(**kwargs):
        raise RuntimeError("injected insight failure")
    async def predictive():
        return {"emitted": 0}
    async def ops():
        return {"server": {"emitted": 0}, "client": {"emitted": 0}}
    monkeypatch.setattr(nua_scheduler.nua_intelligence, "run_all_insights", broken)
    monkeypatch.setattr(predictive_signals, "scan_and_emit_predicted_stockouts", predictive)
    monkeypatch.setattr(ops_signals, "scan_and_emit", ops)
    result = _run(nua_scheduler.run_tick_once())
    assert result == {"businessesScanned": 1, "failures": 1}


def test_failed_course_fire_is_not_reported_as_completed(monkeypatch):
    import pytest
    from database import db
    from services import coursing_scheduler, coursing
    from routes import kitchen
    async def config(**kwargs):
        return {"enabled": True, "autoFireTiming": True}
    async def broken(*args, **kwargs):
        raise RuntimeError("injected fire failure")
    monkeypatch.setattr(coursing, "get_config", config)
    monkeypatch.setattr(coursing, "due_auto_fires", lambda *a: [1])
    monkeypatch.setattr(kitchen, "fire_course_internal", broken)
    _run(db.kitchen_orders.insert_one({"id": "cron-fire-test", "businessId": "cron-test-business", "status": "new"}))
    try:
        with pytest.raises(RuntimeError, match="scheduled course fires failed"):
            _run(coursing_scheduler._tick_once())
    finally:
        _run(db.kitchen_orders.delete_one({"id": "cron-fire-test"}))
