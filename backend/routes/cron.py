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
import uuid
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



async def _execute(job_name, ttl, work, *, release=False):
    from services import cron_jobs
    owner_token = uuid.uuid4().hex
    if not await cron_jobs.try_claim(job_name, ttl_seconds=ttl, owner_token=owner_token):
        return {"ran": False, "reason": "already claimed by another invocation"}
    try:
        result = await work()
        if result.get("failures", 0):
            raise RuntimeError("Scheduled work reported partial failures")
        if not await cron_jobs.finish(job_name, owner_token):
            raise HTTPException(409, "Job lease replaced before completion")
        return {"ran": True, **result}
    except BaseException as exc:
        try:
            await cron_jobs.finish(job_name, owner_token, error_type=type(exc).__name__)
        except Exception:
            # No false success is recorded if the database is unavailable.
            import logging
            logging.getLogger(__name__).exception("Could not record cron failure")
        raise
    finally:
        if release:
            await cron_jobs.release(job_name, owner_token)


@router.api_route("/ash-hourly", methods=["GET", "POST"])
async def cron_ash_hourly(authorization: Optional[str] = Header(None)):
    _require_cron_secret(authorization)
    from services import nua_scheduler
    return await _execute("ash-hourly", max(nua_scheduler._hourly_interval_seconds() - 5, 30),
                          nua_scheduler.run_tick_once)


@router.api_route("/coursing-tick", methods=["GET", "POST"])
async def cron_coursing_tick(authorization: Optional[str] = Header(None)):
    _require_cron_secret(authorization)
    from services import coursing_scheduler
    async def work():
        return {"coursesFired": await coursing_scheduler._tick_once()}
    return await _execute("coursing-tick", max(coursing_scheduler._interval_seconds() - 5, 15), work)


@router.api_route("/backup-drill-check", methods=["GET", "POST"])
async def cron_backup_drill_check(authorization: Optional[str] = Header(None)):
    _require_cron_secret(authorization)
    from services import backup_scheduler
    async def work():
        await backup_scheduler._maybe_run_drill()
        status = await backup_scheduler.drill_status()
        if (status.get("lastDrill") or {}).get("ok") is False:
            raise RuntimeError("Backup restore drill failed")
        return status
    return await _execute("backup-drill-check", 300, work)


@router.api_route("/booking-sync-drain", methods=["GET", "POST"])
async def cron_booking_sync_drain(authorization: Optional[str] = Header(None)):
    _require_cron_secret(authorization)
    from services import booking_sync
    async def work():
        return {"delivered": await booking_sync.drain(limit=50)}
    return await _execute("booking-sync-drain", 300, work, release=True)
