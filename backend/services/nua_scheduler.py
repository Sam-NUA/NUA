"""
Ash background scheduler.

• Runs `run_all_insights()` every N seconds (env: `ASH_HOURLY_SECONDS`, default 3600).
• Once per day at `ASH_DAILY_DIGEST_HOUR` (default 8, local UTC hour), generates
  the weekly summary and dispatches a digest via the notification abstraction.
• Idempotent: guards against double-firing on the same day using
  `db.ash_digests` (upserted by ISO date).
• Never crashes the app — every error is logged and the loop continues.
"""
from __future__ import annotations
import asyncio
import logging
import os
from typing import Any, cast
from datetime import datetime, timezone
from database import db
from services import nua_intelligence
from middleware.actor_context import tenant_scope_filter, get_actor_context, _actor_ctx

logger = logging.getLogger(__name__)

_task: asyncio.Task | None = None


def _hourly_interval_seconds() -> int:
    try:
        return int(os.environ.get("ASH_HOURLY_SECONDS", "3600"))
    except Exception:
        return 3600


def _digest_hour() -> int:
    try:
        return int(os.environ.get("ASH_DAILY_DIGEST_HOUR", "8"))
    except Exception:
        return 8


async def _send_digest_notification(subject: str, body: str) -> None:
    """Best-effort dispatch. Uses utils.notifications if configured, else logs."""
    try:
        from utils.notifications import send_email
        owner = await cast(Any, db.auth_users).find_one({"role": "owner", "status": "active", **tenant_scope_filter()}, {"email": 1})
        recipient = (owner or {}).get("email")
        if not recipient:
            return
        await send_email(recipient, subject, body)
        logger.info(f"[ash] daily digest emailed to {recipient}")
    except Exception as e:
        logger.info(f"[ash] daily digest (mocked): {subject} — {body[:200]}…  ({e})")


async def _maybe_send_daily_digest(*, force: bool = False) -> None:
    now = datetime.now(timezone.utc)
    if not force and now.hour < _digest_hour():
        return
    today_key = now.date().isoformat()
    existing = await db.ash_digests.find_one({"date": today_key, **tenant_scope_filter()}, {"_id": 0})
    if existing and not force:
        return
    weekly = await nua_intelligence.generate_weekly_summary()
    if not weekly:
        return
    # Persist as insight so it appears on the dashboard too
    await db.ash_insights.update_one(
        {"category": weekly["category"], "key": weekly["key"], **tenant_scope_filter()},
        {"$set": weekly, "$setOnInsert": {"firstSeenAt": weekly["createdAt"]}},
        upsert=True,
    )
    # Pull the top 5 open high/warning insights to include in the digest body
    top = await db.ash_insights.find(
        {**tenant_scope_filter(), "resolvedAt": None, "severity": {"$in": ["high", "warning"]}},
        {"_id": 0},
    ).sort("createdAt", -1).limit(5).to_list(5)
    lines = [weekly["body"], ""]
    if top:
        lines.append("Open action items:")
        for t in top:
            lines.append(f"  • [{t['severity']}] {t['title']}")
    body = "\n".join(lines)
    await _send_digest_notification("Ash — Daily Digest", body)
    await db.ash_digests.insert_one({"businessId": get_actor_context().get("businessId"), "date": today_key, "sentAt": now.isoformat(), "summary": weekly, "topInsights": top})


async def _loop() -> None:
    interval = _hourly_interval_seconds()
    logger.info(f"[ash] scheduler starting — hourly interval {interval}s, digest hour {_digest_hour()}")
    # Small startup delay so we don't compete with app boot
    await asyncio.sleep(15)
    while True:
        try:
            businesses = await db.businesses.find({"status": {"$ne": "inactive"}}, {"id": 1}).to_list(10000)
        except Exception:
            logger.exception("[ash] cannot load businesses for scheduled work")
            businesses = []
        for business in businesses:
            if not business.get("id"):
                continue
            token = _actor_ctx.set({"businessId": business["id"], "email": "system"})
            try:
                try:
                    result = await nua_intelligence.run_all_insights(include_summary=False)
                    logger.info(f"[ash] hourly scan generated={result['generated']} categories={list(result['perCategory'].keys())}")
                    await _maybe_send_daily_digest()
                except Exception as e:
                    logger.warning(f"[ash] scheduler loop error: {e}")
                try:
                    from services import predictive_signals
                    pred = await predictive_signals.scan_and_emit_predicted_stockouts()
                    if pred["emitted"]:
                        logger.info(f"[ash] predictive scan emitted {pred['emitted']} stockout warning(s)")
                except Exception as e:
                    logger.warning(f"[ash] predictive scan error: {e}")
                try:
                    from services import ops_signals
                    ops = await ops_signals.scan_and_emit()
                    if ops["server"]["emitted"] or ops["client"]["emitted"]:
                        logger.info(f"[ash] ops scan: server_emitted={ops['server']['emitted']} client_emitted={ops['client']['emitted']}")
                except Exception as e:
                    logger.warning(f"[ash] ops scan error: {e}")
            finally:
                _actor_ctx.reset(token)
        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            logger.info("[ash] scheduler cancelled — exiting cleanly")
            return


def start_scheduler() -> None:
    """Idempotent. Call once from `startup` — creates the background task."""
    global _task
    if _task and not _task.done():
        return
    if os.environ.get("ASH_HOURLY_ENABLED", "true").lower() != "true":
        logger.info("[ash] scheduler disabled by ASH_HOURLY_ENABLED=false")
        return
    _task = asyncio.create_task(_loop(), name="ash-scheduler")


def stop_scheduler() -> None:
    if _task and not _task.done():
        _task.cancel()


def is_running() -> bool:
    return bool(_task and not _task.done())


async def digest_status() -> dict:
    """For the UI: last digest sent + next scheduled time."""
    latest = await cast(Any, db.ash_digests).find_one(tenant_scope_filter(), {"_id": 0}, sort=[("date", -1)])
    now = datetime.now(timezone.utc)
    return {
        "enabled": os.environ.get("ASH_HOURLY_ENABLED", "true").lower() == "true",
        "hourlyIntervalSeconds": _hourly_interval_seconds(),
        "digestHourUtc": _digest_hour(),
        "lastDigest": latest,
        "serverTimeUtc": now.isoformat(),
    }


async def force_digest_now() -> dict:
    """Manual trigger — regenerates + sends today's digest even if already sent or before digest hour."""
    today_key = datetime.now(timezone.utc).date().isoformat()
    await db.ash_digests.delete_one({"date": today_key, **tenant_scope_filter()})
    await _maybe_send_daily_digest(force=True)
    latest = await cast(Any, db.ash_digests).find_one({"date": today_key, **tenant_scope_filter()}, {"_id": 0})
    return latest or {"sent": False, "reason": "generator returned no summary"}
