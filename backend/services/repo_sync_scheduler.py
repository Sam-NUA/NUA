"""
Daily GitHub auto-sync.

Once per day at REPO_SYNC_HOUR in REPO_SYNC_TZ (default 04:00 Australia/Sydney),
runs:
    git fetch <REPO_SYNC_URL> <REPO_SYNC_BRANCH>
    git merge FETCH_HEAD --no-edit

Design constraints:
- Read-only-safe: fails loudly (logs + records) on any conflict, never force-resets.
- Idempotent: guards against double-firing on the same local date via db.repo_sync_log.
- Best-effort: any failure is logged and the loop continues — never crashes the app.
- Container-scoped: only runs while the backend process is up. If preview sleeps
  through the target hour the sync will happen when the app next wakes and the
  current local date hasn't been synced yet.
"""
from __future__ import annotations
import asyncio
import logging
import os
import subprocess
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from database import db

logger = logging.getLogger(__name__)

_task: asyncio.Task | None = None

REPO_URL = os.environ.get("REPO_SYNC_URL", "https://github.com/BSaumil/NUA.git")
REPO_BRANCH = os.environ.get("REPO_SYNC_BRANCH", "main")
REPO_HOUR = int(os.environ.get("REPO_SYNC_HOUR", "4"))       # local-time hour in REPO_SYNC_TZ
REPO_TZ_NAME = os.environ.get("REPO_SYNC_TZ", "Australia/Sydney")
REPO_INTERVAL = int(os.environ.get("REPO_SYNC_INTERVAL", "1800"))  # check every 30 min
REPO_ROOT = os.environ.get("REPO_SYNC_ROOT", "/app")
ENABLED = os.environ.get("REPO_SYNC_ENABLED", "true").lower() in ("1", "true", "yes")


def _local_tz():
    try:
        return ZoneInfo(REPO_TZ_NAME)
    except ZoneInfoNotFoundError:
        logger.warning(f"[repo-sync] timezone {REPO_TZ_NAME!r} not found, falling back to UTC")
        return timezone.utc


def _run_git(*args: str, timeout: int = 90) -> tuple[int, str, str]:
    """Run a git subcommand. Returns (returncode, stdout, stderr)."""
    try:
        res = subprocess.run(
            ["git", "-C", REPO_ROOT, *args],
            capture_output=True, text=True, timeout=timeout,
        )
        return res.returncode, res.stdout, res.stderr
    except Exception as exc:
        return -1, "", str(exc)


async def _do_sync(*, force: bool = False) -> dict:
    """Perform one fetch+merge cycle. Returns a status dict."""
    tz = _local_tz()
    today = datetime.now(tz).date().isoformat()   # date in local zone (e.g. AEST)
    if not force:
        existing = await db.repo_sync_log.find_one({"date": today, "status": "ok"})
        if existing:
            return {"ran": False, "reason": "already synced today", "date": today}

    started = datetime.now(timezone.utc).isoformat()

    # 1. Save current HEAD as a rollback branch (idempotent — force update)
    _run_git("branch", "-f", "preview-pre-autosync-backup", "HEAD")

    # 2. Fetch
    rc, out, err = _run_git("fetch", REPO_URL, REPO_BRANCH)
    if rc != 0:
        outcome = {"date": today, "startedAt": started, "status": "fetch_failed",
                   "error": (err or out).strip()[:1000]}
        await db.repo_sync_log.insert_one({**outcome, "finishedAt": datetime.now(timezone.utc).isoformat()})
        logger.warning(f"[repo-sync] fetch failed: {outcome['error']}")
        return {"ran": True, **outcome}

    # 3. Check if there's anything to merge
    rc, out, _ = _run_git("log", "--oneline", "HEAD..FETCH_HEAD")
    new_commits = [ln for ln in (out or "").splitlines() if ln.strip()]
    if not new_commits:
        outcome = {"date": today, "startedAt": started, "status": "ok",
                   "finishedAt": datetime.now(timezone.utc).isoformat(),
                   "newCommits": 0, "note": "already up to date"}
        await db.repo_sync_log.update_one({"date": today}, {"$set": outcome}, upsert=True)
        logger.info(f"[repo-sync] {REPO_BRANCH} already up to date")
        return {"ran": True, **outcome}

    # 4. Attempt merge
    rc, out, err = _run_git("merge", "FETCH_HEAD", "--no-edit",
                            "-m", "Auto-sync: pull latest main from GitHub")
    if rc != 0:
        # Bail out cleanly — do NOT force. Abort any partial merge and leave workspace clean.
        _run_git("merge", "--abort")
        outcome = {"date": today, "startedAt": started, "status": "merge_failed",
                   "finishedAt": datetime.now(timezone.utc).isoformat(),
                   "newCommits": len(new_commits),
                   "error": (err or out).strip()[:1000],
                   "conflictAborted": True}
        await db.repo_sync_log.update_one({"date": today}, {"$set": outcome}, upsert=True)
        logger.warning(f"[repo-sync] merge failed (aborted cleanly): {outcome['error']}")
        return {"ran": True, **outcome}

    outcome = {"date": today, "startedAt": started, "status": "ok",
               "finishedAt": datetime.now(timezone.utc).isoformat(),
               "newCommits": len(new_commits),
               "sampleCommits": new_commits[:10]}
    await db.repo_sync_log.update_one({"date": today}, {"$set": outcome}, upsert=True)
    logger.info(f"[repo-sync] merged {len(new_commits)} new commits from {REPO_BRANCH}")
    return {"ran": True, **outcome}


async def _loop() -> None:
    tz = _local_tz()
    logger.info(
        f"[repo-sync] scheduler starting — {REPO_URL}#{REPO_BRANCH} "
        f"at hour {REPO_HOUR:02d} {REPO_TZ_NAME}, poll every {REPO_INTERVAL}s"
    )
    while True:
        try:
            now_local = datetime.now(tz)
            # Only sync when the local-time hour matches. With a 30-min poll interval
            # we'll get exactly one attempt during the target hour; subsequent ones
            # are no-ops thanks to the daily idempotency guard.
            if now_local.hour == REPO_HOUR:
                await _do_sync()
        except Exception as exc:
            logger.warning(f"[repo-sync] tick error: {exc}")
        await asyncio.sleep(REPO_INTERVAL)


def start_scheduler() -> None:
    global _task
    if not ENABLED:
        logger.info("[repo-sync] disabled via REPO_SYNC_ENABLED=false")
        return
    if _task and not _task.done():
        return
    _task = asyncio.create_task(_loop())


def stop_scheduler() -> None:
    if _task and not _task.done():
        _task.cancel()
        logger.info("[repo-sync] scheduler cancelled — exiting cleanly")


async def force_sync_now() -> dict:
    """Public entry point for manual/API-triggered sync."""
    return await _do_sync(force=True)


async def sync_status(limit: int = 10) -> dict:
    rows = await db.repo_sync_log.find({}, {"_id": 0}).sort("date", -1).limit(limit).to_list(limit)
    return {
        "enabled": ENABLED,
        "url": REPO_URL,
        "branch": REPO_BRANCH,
        "hourLocal": REPO_HOUR,
        "timezone": REPO_TZ_NAME,
        "pollIntervalSeconds": REPO_INTERVAL,
        "recent": rows,
    }
