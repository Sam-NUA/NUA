"""
Observability -> rules engine bridge. error_log/client_error_log (see
observability.py) capture real server and browser errors but just sat
there until someone thought to go look — a system of record, not a system
of alerting. This checks both on the same hourly cadence as
predictive_signals.py and, when the error rate in a rolling window crosses
a threshold, emits it through the rules engine (ops.error_spike) so a
subscribed rule can notify, page, or auto-remediate instead of an owner
finding out from a staff member's complaint.
"""
from __future__ import annotations
from typing import Any, Dict, Optional
from datetime import datetime, timedelta, timezone
from database import db
from middleware.actor_context import tenant_scope_filter
from services import rules_engine
import os
import logging

logger = logging.getLogger(__name__)

LOOKBACK_MINUTES = int(os.environ.get("OPS_ERROR_LOOKBACK_MINUTES", "30"))
SERVER_ERROR_THRESHOLD = int(os.environ.get("OPS_SERVER_ERROR_THRESHOLD", "5"))
CLIENT_ERROR_THRESHOLD = int(os.environ.get("OPS_CLIENT_ERROR_THRESHOLD", "10"))
DEDUPE_HOURS = 2  # don't re-alert on the same still-ongoing spike every hour


async def _recently_emitted(source: str, business_id: Optional[str] = None) -> bool:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=DEDUPE_HOURS)).isoformat()
    row = await db.rule_events.find_one({
        "type": "ops.error_spike", "entityId": source, "ts": {"$gte": cutoff},
        **tenant_scope_filter(business_id),
    })
    return row is not None


async def check_server_errors(*, lookback_minutes: int = LOOKBACK_MINUTES,
                                threshold: int = SERVER_ERROR_THRESHOLD,
                                business_id: Optional[str] = None) -> Dict[str, Any]:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=lookback_minutes)
    rows = await db.error_log.find(
        {"at": {"$gte": cutoff}, **tenant_scope_filter(business_id)}, {"_id": 0, "path": 1, "error": 1},
    ).to_list(500)
    count = len(rows)
    result: Dict[str, Any] = {"triggered": count >= threshold, "count": count,
                               "threshold": threshold, "windowMinutes": lookback_minutes}
    if result["triggered"]:
        path_counts: Dict[str, int] = {}
        for r in rows:
            p = r.get("path") or "unknown"
            path_counts[p] = path_counts.get(p, 0) + 1
        top_path = max(path_counts, key=path_counts.get) if path_counts else None
        result["topPath"] = top_path
        # An error sample from the top path itself, not an arbitrary row in
        # the window — otherwise a spike on one endpoint could surface a
        # completely unrelated error message from something else entirely.
        result["sampleError"] = next(
            (r.get("error") for r in rows if (r.get("path") or "unknown") == top_path), None,
        )
    return result


async def check_client_errors(*, lookback_minutes: int = LOOKBACK_MINUTES,
                                threshold: int = CLIENT_ERROR_THRESHOLD,
                                business_id: Optional[str] = None) -> Dict[str, Any]:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=lookback_minutes)
    rows = await db.client_error_log.find(
        {"at": {"$gte": cutoff}, **tenant_scope_filter(business_id)}, {"_id": 0, "message": 1, "url": 1},
    ).to_list(500)
    count = len(rows)
    result: Dict[str, Any] = {"triggered": count >= threshold, "count": count,
                               "threshold": threshold, "windowMinutes": lookback_minutes}
    if result["triggered"]:
        result["sampleMessage"] = rows[0].get("message") if rows else None
    return result


async def scan_and_emit(business_id: Optional[str] = None) -> Dict[str, Any]:
    """Called from the hourly Ash scheduler loop, same as predictive_signals
    (business_id is None there — a known, documented gap shared with
    predictive_signals.py and nua_intelligence.py's own generators).
    routes/rules_engine.py's manual-trigger endpoint passes the caller's
    own businessId. Checks both sources; emits ops.error_spike for
    whichever crossed its threshold and isn't already inside its dedupe
    window."""
    server = await check_server_errors(business_id=business_id)
    server["emitted"] = False
    if server["triggered"] and not await _recently_emitted("server", business_id):
        await rules_engine.emit_event("ops.error_spike", {
            "source": "server", "count": server["count"], "threshold": server["threshold"],
            "windowMinutes": server["windowMinutes"], "topPath": server.get("topPath"),
            "sampleError": server.get("sampleError"),
        }, entity_id="server", business_id=business_id)
        server["emitted"] = True

    client = await check_client_errors(business_id=business_id)
    client["emitted"] = False
    if client["triggered"] and not await _recently_emitted("client", business_id):
        await rules_engine.emit_event("ops.error_spike", {
            "source": "client", "count": client["count"], "threshold": client["threshold"],
            "windowMinutes": client["windowMinutes"], "sampleMessage": client.get("sampleMessage"),
        }, entity_id="client", business_id=business_id)
        client["emitted"] = True

    return {"server": server, "client": client}
