"""Concurrency claim for cron-triggered ticks.

Vercel Cron invokes an HTTP endpoint on a schedule instead of running a
perpetual in-process loop — the loop can't survive an idle instance being
retired between invocations. A claim here is what stands in for "only one
loop iteration runs at a time": two overlapping invocations (a slow
previous run, or two instances cron fired at once) must not both execute
the same tick. The same lock doubles as the "don't run more often than
every N seconds" throttle for jobs whose real cadence is coarser than the
cron schedule that drives them (e.g. an hourly job polled every minute).
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Optional
from database import db
from pymongo.errors import DuplicateKeyError
import logging

logger = logging.getLogger(__name__)


async def try_claim(job_name: str, ttl_seconds: int) -> bool:
    """True if this invocation now owns job_name for ttl_seconds.

    An expired or never-claimed lock is claimed atomically. A lock still
    held by someone else makes the upsert collide on _id and fail with a
    duplicate-key error instead of silently overwriting a live claim —
    same pattern as routes/auth.py's _insert_seed_user.
    """
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    try:
        await db.scheduler_locks.find_one_and_update(
            {"_id": job_name, "$or": [
                {"lockedUntil": {"$exists": False}},
                {"lockedUntil": {"$lt": now_iso}},
            ]},
            {"$set": {"lockedUntil": (now + timedelta(seconds=ttl_seconds)).isoformat(),
                      "claimedAt": now_iso}},
            upsert=True,
        )
        return True
    except DuplicateKeyError:
        return False


async def release(job_name: str) -> None:
    """Free the lock early so the next real-cadence tick isn't blocked by
    the full ttl_seconds — used by short jobs (e.g. the booking-sync drain)
    where the lock exists only to stop two overlapping invocations, not to
    throttle how often the job itself may run."""
    now_iso = datetime.now(timezone.utc).isoformat()
    await db.scheduler_locks.update_one({"_id": job_name}, {"$set": {"lockedUntil": now_iso}})


async def last_run(job_name: str) -> Optional[dict]:
    return await db.scheduler_locks.find_one({"_id": job_name}, {"_id": 0})
