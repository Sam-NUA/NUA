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
