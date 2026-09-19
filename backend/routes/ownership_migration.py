"""Admin-only endpoints for services/ownership_migration.py — see that
module's docstring for the full design. Every write here (the actual
migration run, and the manual quarantine-resolution) is gated behind the
same owner + X-Support-Override pattern routes/licensing.py's ABN-change
override already uses: a deliberately narrow, source-visible, no-default
gate, not a role check alone. Listing quarantined documents is similarly
owner-gated and scoped to the caller's own... except quarantined
documents have no confirmed businessId by definition, so "scoped to the
caller's business" isn't meaningful — instead this is deliberately
locked behind the same support-override key as the write actions, not
just Depends(require_owner) alone, so an ordinary business owner can
never browse another business's potentially-ambiguous legacy records
just by knowing this endpoint exists.
"""
import os
import secrets
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Request
from deps import require_owner
from services import ownership_migration as migration

router = APIRouter(prefix="/admin/ownership-migration")


def _require_support_override(request: Request) -> None:
    override_key = os.environ.get("SUPPORT_OVERRIDE_KEY")
    override = request.headers.get("X-Support-Override")
    if not override_key or not secrets.compare_digest(override or "", override_key):
        raise HTTPException(status_code=403, detail="Requires a valid X-Support-Override header")


@router.get("/collections")
async def list_migratable_collections(_: dict = Depends(require_owner)):
    return {"collections": list(migration.MIGRATABLE_COLLECTIONS)}


@router.post("/scan/{collection_name}")
async def scan_collection(collection_name: str, request: Request, after_id: Optional[str] = None, batch_size: int = 500, _: dict = Depends(require_owner)):
    """Always dry-run — a read-only preview of what a real run would do.
    Support authorization is required because evidence spans businesses."""
    _require_support_override(request)
    try:
        return await migration.migrate_collection(collection_name, dry_run=True, after_id=after_id, batch_size=batch_size)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/run/{collection_name}")
async def run_migration(collection_name: str, request: Request, after_id: Optional[str] = None, batch_size: int = 500, user: dict = Depends(require_owner)):
    """Actually writes: resolves what it can from reliable evidence,
    quarantines the rest. Requires the support-override header on top of
    owner auth — this can touch documents whose current owner is
    unconfirmed, which is exactly the class of action this codebase
    reserves for an explicit, logged override rather than routine staff
    access."""
    _require_support_override(request)
    try:
        report = await migration.migrate_collection(collection_name, dry_run=False, after_id=after_id, batch_size=batch_size)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    from services.audit_service import log_event
    report["auditLogged"] = True
    try:
        await log_event(
            entity_type="ownership_migration", entity_id=collection_name, action="executed",
            after={"resolved": len(report["resolved"]), "quarantined": len(report["quarantined"])},
            memo=f"Ownership migration run against {collection_name} by {user.get('email')}",
            severity="high", tags=["ownership_migration"],
        )
    except Exception:
        report["auditLogged"] = False
        logging.getLogger(__name__).exception("Ownership migration completed, but secondary audit sink failed")
    return report


@router.get("/quarantined/{collection_name}")
async def list_quarantined(collection_name: str, request: Request, after_id: Optional[str] = None, _: dict = Depends(require_owner)):
    _require_support_override(request)
    try:
        rows = await migration.list_quarantined(collection_name, after_id=after_id)
        return {"collection": collection_name, "documents": rows,
                "nextCursor": rows[-1]["documentKey"] if len(rows) == 1000 else None}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/quarantined/{collection_name}/{doc_id}/resolve")
async def resolve_quarantined(collection_name: str, doc_id: str, data: dict, request: Request,
                               user: dict = Depends(require_owner)):
    _require_support_override(request)
    business_id = data.get("businessId")
    if not business_id:
        raise HTTPException(status_code=400, detail="businessId required")
    try:
        actor = user.get("email") or user.get("id") or "unknown"
        return await migration.resolve_quarantined(
            collection_name, doc_id, business_id, actor=actor, evidence=data.get("evidence", ""))
    except LookupError:
        raise HTTPException(status_code=404, detail="Document not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
