"""
Universal audit / history / restore endpoints.
"""
from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.responses import Response
from typing import Optional
from deps import get_user, require_owner_or_manager, require_owner
from services import audit_service, entity_service
from database import db
from middleware.actor_context import tenant_scope_filter
import csv
import io

router = APIRouter(prefix="/audit")

# entity_type (what audit events are tagged with, e.g. from stamped_update's
# entity_type= kwarg) -> the actual Mongo collection name. Restoring a
# version needs the real collection, and the two names diverge often enough
# (singular vs. plural, "category" -> "categories") that guessing it
# client-side would be a good way to silently restore into the wrong
# collection. Callers that already know the right collection can still pass
# ?collection= explicitly to override this.
ENTITY_TYPE_TO_COLLECTION = {
    "customer": "customers",
    "product": "products",
    "category": "categories",
    "stock_unit": "stock_units",
    "sell_variant": "sell_variants",
    "wastage_event": "wastage_events",
    "approval": "approvals",
    "open_container": "open_containers",
    "journal_entry": "journal_entries",
    "ash_plan": "ash_plans",
    "cash_drawer": "cash_drawers",
    "kitchen_order": "kitchen_orders",
    "stocktake_reconcile": "stocktake_reconciles",
    "transaction": "transactions",
    "loyalty_fraud_flag": "loyalty_fraud_flags",
}


@router.get("/events")
async def list_events(
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    action: Optional[str] = None,
    actor: Optional[str] = None,
    limit: int = 200,
    user: dict = Depends(get_user),
):
    return await audit_service.list_events(
        business_id=user.get("businessId") or "default",
        entity_type=entity_type, entity_id=entity_id,
        action=action, actor=actor, limit=limit,
    )


@router.get("/history/{entity_type}/{entity_id}")
async def history(entity_type: str, entity_id: str, user: dict = Depends(get_user)):
    return await entity_service.get_history(entity_type, entity_id, business_id=user.get("businessId") or "default")


@router.post("/restore/{entity_type}/{entity_id}/{version}")
async def restore(entity_type: str, entity_id: str, version: int,
                  collection: Optional[str] = Query(None),
                  _: dict = Depends(require_owner_or_manager)):
    coll_name = collection or ENTITY_TYPE_TO_COLLECTION.get(entity_type)
    if not coll_name:
        raise HTTPException(400, f"Unknown entity_type '{entity_type}' — pass ?collection= explicitly")
    r = await entity_service.restore_version(coll_name, entity_type, entity_id, version)
    if not r:
        raise HTTPException(404, "Version not found")
    return r


@router.delete("/purge/{entity_type}/{entity_id}")
async def gdpr_purge(entity_type: str, entity_id: str,
                     collection: str = Query(...),
                     user: dict = Depends(require_owner)):
    """Owner-only right-to-be-forgotten. Removes doc + history.

    `collection` used to be taken straight from the caller with no
    validation and no tenant check at all — an owner of ANY business could
    permanently delete any document (auth_users, businesses, transactions,
    anything) in any OTHER business by id, purely by knowing/guessing it.
    Now restricted to the same allowlist restore/history already use
    (this endpoint's own stated purpose — a GDPR purge of one of YOUR
    entities — was never "arbitrary document in an arbitrary collection"),
    and the document's own businessId is checked against the caller's
    before anything is touched.

    Deliberately an EXACT match, not tenant_owns()'s usual fail-open-to-
    untagged-legacy-data rule (which is right for a read — never hide data
    because the tenant signal is merely missing — but wrong for a
    permanent hard delete). A second independent audit flagged this: this
    codebase's own history includes a real bug where `_stamp_new()`
    silently left every product's businessId unset, so an untagged
    `businessId=None` row is a genuine, plausible state on an old
    deployment — and tenant_owns() treats "no businessId on either side"
    as a match, which would let ANY owner permanently delete such a row
    from ANY other business. A purge of a document whose business can't be
    confirmed is refused (404) rather than risked, even if that means an
    owner has to reach for the restore/history endpoints instead to
    reconcile truly-untagged legacy data."""
    if collection not in ENTITY_TYPE_TO_COLLECTION.values():
        raise HTTPException(status_code=400, detail=f"Purge isn't supported for collection '{collection}'")
    existing = await getattr(db, collection).find_one({"id": entity_id}, {"_id": 0, "businessId": 1})
    if not existing or existing.get("businessId") != user.get("businessId"):
        raise HTTPException(404, "Entity not found")
    ok = await entity_service.hard_delete(collection, entity_id, entity_type=entity_type)
    if not ok:
        raise HTTPException(404, "Entity not found")
    return {"purged": True}


@router.get("/summary")
async def summary(user: dict = Depends(get_user)):
    """Quick actor / action mix over the recent audit stream."""
    business_id = user.get("businessId") or "default"
    # tenant_scope_filter, not a plain equality match, so events written
    # before tenant stamping still count instead of vanishing from a
    # not-yet-backfilled business's summary.
    scope = tenant_scope_filter(business_id)
    match = {"$match": scope}
    pipeline_action = [match, {"$group": {"_id": "$action", "count": {"$sum": 1}}}, {"$sort": {"count": -1}}]
    pipeline_type = [match, {"$group": {"_id": "$entityType", "count": {"$sum": 1}}}, {"$sort": {"count": -1}}, {"$limit": 20}]
    pipeline_actor = [match, {"$group": {"_id": "$actor", "count": {"$sum": 1}}}, {"$sort": {"count": -1}}, {"$limit": 10}]
    return {
        "byAction": await db.audit_events.aggregate(pipeline_action).to_list(20),
        "byEntity": await db.audit_events.aggregate(pipeline_type).to_list(20),
        "byActor": await db.audit_events.aggregate(pipeline_actor).to_list(10),
        "total": await db.audit_events.count_documents(scope),
    }


# ═════════════════════════════════════════════════════════════════════════
# Compliance export — the approval queue, rule firings, and trust ladder
# already record every autonomous decision individually; this assembles
# them into one chronological, exportable trail for a date range instead
# of an operator having to piece it together from three different screens.
# ═════════════════════════════════════════════════════════════════════════
@router.get("/compliance-report")
async def compliance_report(start: Optional[str] = None, end: Optional[str] = None,
                            user: dict = Depends(require_owner)):
    from services import compliance_export
    return await compliance_export.build_report(
        business_id=user.get("businessId"), start_date=start, end_date=end)


@router.get("/compliance-export.csv")
async def compliance_export_csv(start: Optional[str] = None, end: Optional[str] = None,
                                user: dict = Depends(require_owner)):
    from services import compliance_export
    report = await compliance_export.build_report(
        business_id=user.get("businessId"), start_date=start, end_date=end)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["At", "Kind", "Source", "Summary", "Actor", "Decided By", "Status", "Reference"])
    for row in report["timeline"]:
        writer.writerow([row["at"], row["kind"], row["source"], row["summary"],
                         row.get("actor"), row.get("decidedBy"), row["status"], row.get("reference")])

    range_label = f"{start or 'all-time'}_to_{end or 'now'}".replace(" ", "_")
    range_label = range_label.encode("ascii", "ignore").decode("ascii") or "export"
    return Response(content=buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=compliance-{range_label}.csv"})
