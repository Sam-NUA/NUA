"""What the owner sees when something breaks at 7pm on a Saturday.

There was no error tracking, no structured logs, and no way to ask "is the
backend actually healthy" beyond curling the root endpoint and hoping for a
200. A crash inside a route handler produced a bare traceback in whatever
terminal happened to be watching stdout — invisible the moment nobody was
tailing the log at that exact second, and useless to a non-technical owner
even if they were.

Three pieces:
  * A request-log middleware — one JSON line per request with a request id,
    actor, latency and status, so "what happened around 7:14pm" is a log
    grep instead of a guess.
  * Error capture — unhandled exceptions are caught once, logged with the
    full traceback, and recorded to a capped, TTL'd collection instead of
    just stdout. The client gets a generic message and a request id to quote;
    the actual cause lives in `db.error_log` where an owner-facing screen (or
    a support engineer) can read it back.
  * A deep health check — the existing root endpoint says "the process is
    up"; it doesn't say whether Mongo is reachable or the background
    schedulers are still running. `check_health()` answers that.
"""
import json
import logging
import os
import time
import traceback
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from database import db

log = logging.getLogger("nua.request")

ERROR_RETENTION_DAYS = 30


def _actor_from_request(request) -> Optional[dict]:
    """Best-effort identity for a log line — never raises, never blocks.

    This is a label for a log entry, not an auth decision (RequireAuthMiddleware
    already made that decision before the route ran), so a garbled or expired
    token just means the log line says "actor: none" rather than failing the
    request.
    """
    token = None
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
    if not token:
        token = request.cookies.get("access_token")
    if not token:
        return None
    try:
        import jwt
        payload = jwt.decode(token, os.environ["JWT_SECRET"], algorithms=["HS256"])
        return {"userId": payload.get("sub"), "role": payload.get("role"),
                "businessId": payload.get("businessId")}
    except Exception:
        return None


async def record_error(request_id: str, request, exc: Exception) -> None:
    """Best-effort persistence of an unhandled exception.

    Deliberately swallows its own failures — a database that's down is
    usually *why* something threw in the first place, and the one thing an
    error-reporting path must never do is raise a second exception on top of
    the first.
    """
    try:
        actor = _actor_from_request(request)
        now = datetime.now(timezone.utc)
        await db.error_log.insert_one({
            "requestId": request_id,
            "method": request.method,
            "path": request.scope["path"],  # not request.url.path — see server.py's RequireAuthMiddleware comment on why
            "actor": actor,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc()[-4000:],  # bounded — a runaway
                                                           # recursive error shouldn't
                                                           # write megabytes per row
            "at": now,
            "expiresAt": now + timedelta(days=ERROR_RETENTION_DAYS),
            "businessId": (actor or {}).get("businessId"),
        })
    except Exception:
        log.exception("failed to record error %s (secondary failure, not the original)", request_id)


CLIENT_ERROR_RETENTION_DAYS = 30


async def record_client_error(payload: dict, actor: Optional[dict]) -> None:
    """A JS error that happened in someone's browser — a render crash, a
    rejected promise nobody caught — used to just vanish the moment that tab
    closed. The owner had no way to know the POS had been throwing a white
    screen for a shift unless a staff member happened to mention it.

    Deliberately loose validation and small bounds: this is a diagnostic
    signal from an untrusted browser, not a typed API contract, so it takes
    whatever shape the reporter sends and trims it down rather than
    rejecting anything that doesn't match exactly.
    """
    try:
        now = datetime.now(timezone.utc)
        await db.client_error_log.insert_one({
            "message": str(payload.get("message") or "")[:500],
            "stack": str(payload.get("stack") or "")[:4000],
            "url": str(payload.get("url") or "")[:500],
            "userAgent": str(payload.get("userAgent") or "")[:300],
            "actor": actor,
            "at": now,
            "expiresAt": now + timedelta(days=CLIENT_ERROR_RETENTION_DAYS),
            "businessId": (actor or {}).get("businessId"),
        })
    except Exception:
        log.exception("failed to record client error (non-fatal)")


async def ensure_indexes() -> None:
    try:
        await db.error_log.create_index("expiresAt", expireAfterSeconds=0)
        await db.error_log.create_index("at")
        await db.client_error_log.create_index("expiresAt", expireAfterSeconds=0)
        await db.client_error_log.create_index("at")
    except Exception as e:
        log.info("observability indexes not created: %s", e)


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """Structured request logging plus a single place to catch the unhandled.

    Added as the outermost middleware (last `add_middleware` call) so it sees
    everything — including the 401s the auth gate produces and the 429s the
    rate limiter produces, not just what reaches a route handler.
    """

    async def dispatch(self, request, call_next):
        request_id = uuid.uuid4().hex[:16]
        start = time.monotonic()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception as exc:
            await record_error(request_id, request, exc)
            log.error("unhandled exception [%s] %s %s: %s",
                     request_id, request.method, request.scope["path"], exc, exc_info=True)
            response = JSONResponse(
                status_code=500,
                content={"detail": "Something went wrong on our end.", "requestId": request_id},
            )
        duration_ms = round((time.monotonic() - start) * 1000, 1)
        response.headers["X-Request-Id"] = request_id
        actor = _actor_from_request(request)
        log.info(json.dumps({
            "requestId": request_id,
            "method": request.method,
            "path": request.scope["path"],
            "status": status_code,
            "durationMs": duration_ms,
            "actor": actor.get("userId") if actor else None,
            "role": actor.get("role") if actor else None,
        }))
        return response


async def check_health() -> dict:
    """A health check that answers "is this actually working", not just
    "did the process start". Used by /api/health — deliberately public
    (load balancers and uptime monitors don't carry a login), and deliberately
    thin on detail (no stack traces, no internal hostnames) since it's the
    one endpoint on the public allow-list that runs unauthenticated code.
    """
    checks = {}

    t0 = time.monotonic()
    try:
        await db.command("ping")
        checks["database"] = {"ok": True, "latencyMs": round((time.monotonic() - t0) * 1000, 1)}
    except Exception as e:
        checks["database"] = {"ok": False, "error": str(e)[:200]}

    try:
        from services.nua_scheduler import is_running as ash_running
        checks["ashScheduler"] = {"ok": ash_running()}
    except Exception:
        checks["ashScheduler"] = {"ok": None}   # not an error — just unknown in this build

    try:
        from services.coursing_scheduler import is_running as coursing_running
        checks["coursingScheduler"] = {"ok": coursing_running()}
    except Exception:
        checks["coursingScheduler"] = {"ok": None}

    healthy = all(c.get("ok") is not False for c in checks.values())
    return {"status": "ok" if healthy else "degraded", "checks": checks,
           "time": datetime.now(timezone.utc).isoformat()}
