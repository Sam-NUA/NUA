"""Daily automatic backup restore-drill.

An owner can already trigger POST /ops/backup/drill by hand, but nobody
remembers to do that regularly, and a backup mechanism that silently starts
failing (a schema change, a full disk, a permissions problem) stays invisible
until the day it's actually needed — the worst possible time to find out.

This runs backup.run_restore_drill() once a day automatically and persists
the result, so "is our backup still good" is a fact you can look up instead
of an assumption. Same idempotent-per-day pattern as services/nua_scheduler.py's
digest: a db.backup_drills row keyed by date guards against double-firing.
"""
from __future__ import annotations
import asyncio
import logging
import os
from datetime import datetime, timezone
from database import db
from services import backup

logger = logging.getLogger(__name__)

_task: asyncio.Task | None = None


def _drill_hour() -> int:
    try:
        return int(os.environ.get("BACKUP_DRILL_HOUR_UTC", "3"))
    except Exception:
        return 3


async def _maybe_run_drill(*, force: bool = False) -> None:
    now = datetime.now(timezone.utc)
    if not force and now.hour < _drill_hour():
        return
    today_key = now.date().isoformat()
    existing = await db.backup_drills.find_one({"date": today_key}, {"_id": 0})
    if existing and not force:
        return
    try:
        report = await backup.run_restore_drill(retain=True)
    except Exception as exc:
        report = {"ok": False, "error": str(exc)}
        logger.warning("[backup] restore drill raised: %s", exc)
    await db.backup_drills.update_one(
        {"date": today_key},
        {"$set": {"date": today_key, "ranAt": now.isoformat(), "ok": report.get("ok"), "report": report}},
        upsert=True,
    )
    if report.get("ok"):
        logger.info("[backup] daily restore drill passed")
    else:
        logger.warning("[backup] daily restore drill FAILED: %s", report.get("archiveProblems") or report.get("error"))


async def _loop() -> None:
    interval = 3600
    logger.info(f"[backup] scheduler starting — checking hourly, drill hour {_drill_hour()} UTC")
    await asyncio.sleep(20)  # let app boot settle first
    while True:
        try:
            await _maybe_run_drill()
        except Exception as exc:
            logger.warning(f"[backup] scheduler loop error: {exc}")
        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            logger.info("[backup] scheduler cancelled — exiting cleanly")
            return


def start_scheduler() -> None:
    """Idempotent. Call once from `startup`."""
    global _task
    if _task and not _task.done():
        return
    if os.environ.get("BACKUP_DRILL_ENABLED", "true").lower() != "true":
        logger.info("[backup] scheduler disabled by BACKUP_DRILL_ENABLED=false")
        return
    _task = asyncio.create_task(_loop(), name="backup-drill-scheduler")


def stop_scheduler() -> None:
    if _task and not _task.done():
        _task.cancel()


async def drill_status() -> dict:
    """For Settings/Ops: last drill result + whether one's overdue."""
    latest = await db.backup_drills.find_one({}, {"_id": 0}, sort=[("date", -1)])
    now = datetime.now(timezone.utc)
    return {
        "enabled": os.environ.get("BACKUP_DRILL_ENABLED", "true").lower() == "true",
        "drillHourUtc": _drill_hour(),
        "lastDrill": latest,
        "serverTimeUtc": now.isoformat(),
    }


async def force_drill_now() -> dict:
    """Manual trigger — used by POST /ops/backup/drill to also keep the
    scheduled-drill record current, so a manually-run drill counts toward
    'have we verified today' the same as the automatic one."""
    today_key = datetime.now(timezone.utc).date().isoformat()
    await db.backup_drills.delete_one({"date": today_key})
    await _maybe_run_drill(force=True)
    return await db.backup_drills.find_one({"date": today_key}, {"_id": 0})
