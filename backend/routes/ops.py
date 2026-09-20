"""What tells you the backend is actually okay, and what tells you why it isn't.

Two audiences: a deep health check for uptime monitors and load balancers
(anonymous, deliberately thin on detail), and a recent-errors list for the
owner, who has no other way to see that something has been failing quietly
since 3am.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from database import db
from deps import require_owner, require_owner_or_manager
from middleware.actor_context import tenant_scope_filter
from services.observability import check_health, record_client_error, _actor_from_request
from services import retention
from services import backup

router = APIRouter()


@router.get("/health")
@router.get("/healthz")
async def health():
    return await check_health()


@router.get("/ops/device-status")
async def device_status():
    """Aggregate, non-sensitive hardware-readiness signal for the login
    screen — deliberately public (no token yet at that point) and
    deliberately thin: counts and booleans only, never terminal IDs,
    IPs, or API keys (those stay behind GET /eftpos/terminals's auth)."""
    eftpos_active = await db.eftpos_terminals.count_documents({"status": "active"})
    eftpos_total = await db.eftpos_terminals.count_documents({})
    receipt_cfg = await db.settings.find_one({"key": "receipt_config"}, {"_id": 0})
    return {
        "cardReaderConnected": eftpos_active > 0,
        "cardReaderCount": eftpos_active,
        "receiptTemplateConfigured": receipt_cfg is not None,
    }


@router.post("/ops/client-errors")
async def report_client_error(payload: dict, request: Request):
    """A browser reports its own crash — window.onerror / unhandledrejection,
    wired up in src/lib/errorReporting.js. Public and unauthenticated by
    design: the guest ordering/tracking pages can crash too, and a reporting
    endpoint that requires a login can't hear about the login screen itself
    breaking. Never raises back to the reporter — losing an error report is
    a much smaller problem than a reporting call becoming a second error.
    """
    await record_client_error(payload or {}, _actor_from_request(request))
    return {"recorded": True}


@router.get("/ops/client-errors")
async def recent_client_errors(limit: int = 50, user: dict = Depends(require_owner_or_manager)):
    """The last N browser-side errors, newest first — same audience and
    shape as /ops/errors, just the client half of the picture."""
    limit = max(1, min(limit, 200))
    q = tenant_scope_filter(user.get("businessId"))
    rows = await db.client_error_log.find(q, {"_id": 0}).sort("at", -1).to_list(limit)
    for r in rows:
        at = r.get("at")
        r["at"] = at.isoformat() if hasattr(at, "isoformat") else at
        exp = r.get("expiresAt")
        r["expiresAt"] = exp.isoformat() if hasattr(exp, "isoformat") else exp
    return {"errors": rows, "count": len(rows)}


@router.get("/ops/errors")
async def recent_errors(limit: int = 50, user: dict = Depends(require_owner_or_manager)):
    """The last N unhandled exceptions, newest first.

    This is the thing that used to only exist in whatever terminal happened to
    be tailing stdout at the moment it happened — invisible to an owner with
    no shell access, and gone the moment that terminal closed.
    """
    limit = max(1, min(limit, 200))
    q = tenant_scope_filter(user.get("businessId"))
    rows = await db.error_log.find(q, {"_id": 0}).sort("at", -1).to_list(limit)
    for r in rows:
        at = r.get("at")
        r["at"] = at.isoformat() if hasattr(at, "isoformat") else at
        exp = r.get("expiresAt")
        r["expiresAt"] = exp.isoformat() if hasattr(exp, "isoformat") else exp
    return {"errors": rows, "count": len(rows)}


@router.get("/ops/retention")
async def retention_status(_: dict = Depends(require_owner_or_manager)):
    """What gets auto-deleted, how long it's kept, and why — deliberately
    limited to the ephemeral collections (kiosk carts, notifications, login
    lockouts). Financial and audit records are never on this list."""
    return {"policy": await retention.status()}


@router.post("/ops/retention/purge")
async def retention_purge(_: dict = Depends(require_owner_or_manager)):
    """Run the purge immediately rather than waiting for Mongo's own TTL
    sweep. Only ever removes what was already past its expiry."""
    return {"deleted": await retention.purge_now()}


# ============ BACKUP / RESTORE ============
# Owner-only, not owner-or-manager: this can produce a full export of every
# customer record and every transaction the venue has, and (on restore) can
# overwrite live data. That's a different risk tier from the read-only ops
# endpoints above.
@router.get("/ops/backup")
async def download_backup(user: dict = Depends(require_owner)):
    """A full backup archive, right now, as a download.

    Scoped to the caller's own business — without this, any owner could
    download every business's customers, transactions, and auth_users
    (password hashes included) on the whole deployment in one archive.
    """
    archive = await backup.create_backup(business_id=user.get("businessId"))
    filename = f"nua-backup-{__import__('datetime').datetime.now().strftime('%Y%m%d-%H%M%S')}.tar.gz"
    return Response(content=archive, media_type="application/gzip",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.post("/ops/backup/verify")
async def verify_uploaded_backup(data: dict, _: dict = Depends(require_owner)):
    """Check an archive against its own manifest — base64-encoded body,
    since this is meant for a small Settings-screen upload, not a bulk
    transfer endpoint."""
    import base64
    try:
        archive = base64.b64decode(data.get("archiveBase64", ""))
    except Exception:
        raise HTTPException(status_code=400, detail="Not valid base64")
    if not archive:
        raise HTTPException(status_code=400, detail="Empty archive")
    return backup.verify_backup(archive)


@router.post("/ops/backup/drill")
async def restore_drill(_: dict = Depends(require_owner)):
    """Prove a backup of the live data can actually be restored — end to
    end, against a disposable scratch database, never the live one. This is
    the thing an untested backup skips."""
    return await backup.run_restore_drill()


@router.get("/ops/backup/drill-status")
async def backup_drill_status(_: dict = Depends(require_owner)):
    """Last automatic daily drill result (services/backup_scheduler.py) —
    so 'is our backup still good' is something you look up, not assume."""
    from services import backup_scheduler
    return await backup_scheduler.drill_status()
