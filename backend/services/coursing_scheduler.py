"""Background tick for course timing rules.

Timing is also evaluated whenever the POS reads a ticket, which covers any
table someone is actually looking at. This loop covers the ones nobody is:
a table whose server is busy elsewhere should still get its mains fired on
time.

Deliberately separate from the hourly `nua_scheduler` — that cadence is far
too coarse for something measured in minutes.
"""
import asyncio
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_task: Optional[asyncio.Task] = None


def _interval_seconds() -> int:
    try:
        return max(20, int(os.environ.get("COURSING_TICK_SECONDS", "60")))
    except ValueError:
        return 60


async def _tick_once() -> int:
    """Fire whatever is due. Returns how many courses fired."""
    from database import db
    from services import coursing

    rows = await db.kitchen_orders.find(
        {"status": {"$nin": ["served", "cancelled"]}}, {"_id": 0}).to_list(200)
    fired = 0
    for order in rows:
        if not order.get("businessId") or order.get("_ownershipQuarantined"):
            continue
        config = await coursing.get_config(business_id=order["businessId"])
        if not config.get("enabled") or not config.get("autoFireTiming"):
            continue
        due = coursing.due_auto_fires(order, config)
        if not due:
            continue
        from routes.kitchen import fire_course_internal
        for course in due:
            try:
                await fire_course_internal(order["id"], course, "auto",
                                            business_id=order.get("businessId"))
                fired += 1
            except Exception as e:
                logger.warning("[coursing] auto-fire failed for %s c%s: %s", order["id"], course, e)
    return fired


async def _loop() -> None:
    interval = _interval_seconds()
    logger.info("[coursing] timing scheduler starting — every %ss", interval)
    await asyncio.sleep(20)     # let the app finish booting first
    while True:
        try:
            fired = await _tick_once()
            if fired:
                logger.info("[coursing] auto-fired %s course(s)", fired)
        except Exception as e:
            logger.warning("[coursing] scheduler loop error: %s", e)
        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            logger.info("[coursing] scheduler cancelled — exiting cleanly")
            return


def start_scheduler() -> None:
    """Idempotent. Call once from startup."""
    global _task
    if _task and not _task.done():
        return
    if os.environ.get("COURSING_TICK_ENABLED", "true").lower() != "true":
        logger.info("[coursing] timing scheduler disabled by COURSING_TICK_ENABLED=false")
        return
    _task = asyncio.create_task(_loop(), name="coursing-scheduler")


def stop_scheduler() -> None:
    if _task and not _task.done():
        _task.cancel()


def is_running() -> bool:
    return bool(_task and not _task.done())
