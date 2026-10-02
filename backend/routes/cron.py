"""Vercel Cron entry points for jobs that used to be perpetual in-process
loops (services/nua_scheduler.py, coursing_scheduler.py, backup_scheduler.py,
booking_sync.py). Vercel can retire an idle instance between requests, so a
`while True: await asyncio.sleep(...)` loop started in one invocation is not
guaranteed to still be running by the time its next tick is due — these
routes let Vercel Cron (see vercel.json's `crons`) drive the same tick logic
request-by-request instead.

Vercel invokes cron paths with GET and sends `Authorization: Bearer
$CRON_SECRET` automatically when that env var is set — see
https://vercel.com/docs/cron-jobs/manage-cron-jobs. POST is also accepted
here for manual/local triggering (curl, this repo's own tests) where that
header has to be set by hand.

server.py still starts the old in-process loops when NOT running on Vercel
(`os.environ.get("VERCEL") != "1"`) — this pod's supervisor-managed process
is long-lived, so the original design is correct there and these routes are
simply unused in that environment.
"""
from __future__ import annotations
import hmac
import os
from fastapi import APIRouter, Header, HTTPException
from typing import Optional

router = APIRouter(prefix="/cron")


def _require_cron_secret(authorization: Optional[str]) -> None:
    secret = os.environ.get("CRON_SECRET")
    if not secret:
        raise HTTPException(status_code=503, detail="Cron is not configured (CRON_SECRET unset)")
    expected = f"Bearer {secret}"
    if not authorization or not hmac.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="Invalid cron credential")


@router.api_route("/ash-hourly", methods=["GET", "POST"])
async def cron_ash_hourly(authorization: Optional[str] = Header(None)):
    _require_cron_secret(authorization)
    from services import cron_jobs, nua_scheduler
    # Throttle to roughly the real cadence even if the Vercel schedule
    # polls more often than the job should actually run.
    ttl = nua_scheduler._hourly_interval_seconds() - 5
    if not await cron_jobs.try_claim("ash-hourly", ttl_seconds=max(ttl, 30)):
        return {"ran": False, "reason": "already claimed by another invocation"}
    result = await nua_scheduler.run_tick_once()
    return {"ran": True, **result}


@router.api_route("/coursing-tick", methods=["GET", "POST"])
async def cron_coursing_tick(authorization: Optional[str] = Header(None)):
    _require_cron_secret(authorization)
    from services import cron_jobs, coursing_scheduler
    ttl = coursing_scheduler._interval_seconds() - 5
    if not await cron_jobs.try_claim("coursing-tick", ttl_seconds=max(ttl, 15)):
        return {"ran": False, "reason": "already claimed by another invocation"}
    fired = await coursing_scheduler._tick_once()
    return {"ran": True, "coursesFired": fired}


@router.api_route("/backup-drill-check", methods=["GET", "POST"])
async def cron_backup_drill_check(authorization: Optional[str] = Header(None)):
    _require_cron_secret(authorization)
    from services import cron_jobs, backup_scheduler
    # Idempotent per calendar day already (db.backup_drills) — this lock
    # only prevents two invocations racing the same tick, not daily reruns.
    if not await cron_jobs.try_claim("backup-drill-check", ttl_seconds=300):
        return {"ran": False, "reason": "already claimed by another invocation"}
    await backup_scheduler._maybe_run_drill()
    status = await backup_scheduler.drill_status()
    return {"ran": True, **status}


@router.api_route("/booking-sync-drain", methods=["GET", "POST"])
async def cron_booking_sync_drain(authorization: Optional[str] = Header(None)):
    _require_cron_secret(authorization)
    from services import cron_jobs, booking_sync
    # Short lock: this job's real cadence is "as often as possible" (it's
    # draining a delivery queue), the claim only stops two invocations
    # processing the queue at the exact same instant.
    if not await cron_jobs.try_claim("booking-sync-drain", ttl_seconds=10):
        return {"ran": False, "reason": "already claimed by another invocation"}
    delivered = await booking_sync.drain(limit=50)
    await cron_jobs.release("booking-sync-drain")
    return {"ran": True, "delivered": delivered}
