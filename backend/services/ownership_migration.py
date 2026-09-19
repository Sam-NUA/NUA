"""Dry-run-first, idempotent legacy ownership migration.

Tenant-ownership release-closure pass, task #68. `tenant_owns_strict()`
(middleware/actor_context.py) already refuses any read/write against an
untagged (businessId missing/None) document that a mutation-path check
has been converted to guard — that refusal is the actual security
boundary and needed no migration to exist. This module is the separate,
one-time cleanup: give every untagged legacy document a real disposition
(assigned to its true owner, or explicitly quarantined) instead of
leaving it permanently unreachable through the normal app.

Design constraints, from the standing directive:
- Dry-run by default. Nothing is written unless the caller explicitly
  passes dry_run=False.
- Idempotent. Running it twice (dry-run or real) must produce the same
  end state, not double-process or re-flag already-triaged documents.
- Assign ownership ONLY from reliable evidence — never "the first
  business that asks," never a guess.
- Never auto-assign to an arbitrarily-chosen business, never delete an
  ambiguous record. Unresolvable documents are quarantined (marked, not
  destroyed, not silently left as-is either) for the separate,
  authorised resolution workflow (routes/ownership_migration.py) to
  handle.
"""
from __future__ import annotations
from typing import Optional, Dict, Any, List, Tuple
from database import db
import logging
from utils.ids import now_utc, to_iso

QUARANTINE_FLAG = "_ownershipQuarantined"
QUARANTINE_AT = "_ownershipQuarantinedAt"
QUARANTINE_REASON = "_ownershipQuarantineReason"
MIGRATED_AT = "_ownershipMigratedAt"
MIGRATED_EVIDENCE = "_ownershipMigrationEvidence"

# Explicit inventory of tenant-owned legacy data eligible for support review.
MIGRATABLE_COLLECTIONS = (
    "categories", "modifiers", "discounts", "payment_links",
    "bills", "invoices", "deposits", "budgets", "bank_transactions",
    "awards",
    "rules", "temperature_devices", "stock_transfers", "approvals",
    "customer_segments", "campaigns", "appointments", "services",
    "loyalty_rewards", "ab_tests", "booking_experiences", "club_offers",
    "table_combinations", "dock_notifications", "super_weekly_runs",
    "booking_inbox", "customers", "reservations", "products", "transactions",
    "purchase_orders", "kitchen_orders", "floor_plans", "feedback", "suppliers",
    "expenses", "stock_units", "sell_variants", "online_orders", "waitlist",
    "settings", "loyalty_config", "agent_autonomy", "eftpos_terminals",
    "eftpos_transactions", "eftpos_test_log", "vouchers", "wallet_ledger",
    "loyalty_ledger", "members", "refunds", "promotions",
)


async def _resolve_ownership(doc: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    # Current deployment size is not historical ownership evidence. A sole
    # remaining business may have inherited rows from a deleted tenant.
    customer_id = doc.get("customerId")
    author = doc.get("createdBy")
    candidates = []
    if customer_id:
        customers = await db.customers.find(
            {"id": customer_id, "_ownershipQuarantined": {"$ne": True}},
            {"businessId": 1}).to_list(2)
        if len(customers) != 1 or not customers[0].get("businessId"):
            return None
        candidates.append((customers[0]["businessId"], f"customerId={customer_id}"))
    if author and author != "system":
        users = await db.auth_users.find(
            {"$or": [{"id": author}, {"email": author}]}, {"businessId": 1}).to_list(2)
        if len(users) != 1 or not users[0].get("businessId"):
            return None
        candidates.append((users[0]["businessId"], f"createdBy={author}"))
    # A legacy relationship could itself have been forged by the old unscoped
    # endpoints. Require corroborating author and customer evidence, otherwise
    # leave resolution to support with an explicit recorded justification.
    if len(candidates) < 2 or len({c[0] for c in candidates}) != 1:
        return None
    business_id = candidates[0][0]
    if not await db.businesses.find_one({"id": business_id}):
        return None
    return business_id, "; ".join(c[1] for c in candidates)


async def migrate_collection(collection_name: str, *, dry_run: bool = True,
                             batch_size: int = 500, after_id: Optional[str] = None) -> Dict[str, Any]:
    """Process a bounded page using Mongo's immutable identity and compare-and-set.

    nextCursor resumes scans (including dry runs) without revisiting quarantined
    rows. An apply run can also restart safely without a cursor.
    """
    from bson import ObjectId
    if collection_name not in MIGRATABLE_COLLECTIONS:
        raise ValueError(f"{collection_name!r} is not in MIGRATABLE_COLLECTIONS")
    if not 1 <= batch_size <= 1000:
        raise ValueError("batch_size must be between 1 and 1000")
    query: Dict[str, Any] = {"businessId": None, QUARANTINE_FLAG: {"$ne": True}}
    if after_id:
        if not ObjectId.is_valid(after_id):
            raise ValueError("Invalid migration cursor")
        query["_id"] = {"$gt": ObjectId(after_id)}
    coll = getattr(db, collection_name)
    rows = await coll.find(query).sort("_id", 1).to_list(batch_size + 1)
    more = len(rows) > batch_size
    rows = rows[:batch_size]
    report: Dict[str, Any] = {
        "collection": collection_name, "dryRun": dry_run, "scanned": len(rows),
        "resolved": [], "quarantined": [], "conflicts": [],
        "alreadyQuarantined": await coll.count_documents({QUARANTINE_FLAG: True}),
        "nextCursor": str(rows[-1]["_id"]) if more else None,
    }
    for doc in rows:
        identity = {"id": doc.get("id"), "documentKey": str(doc["_id"])}
        match = await _resolve_ownership(doc)
        now = to_iso(now_utc())
        changes: Dict[str, Any]
        if match:
            business_id, evidence = match
            disposition = {**identity, "businessId": business_id, "evidence": evidence}
            changes = {"businessId": business_id, MIGRATED_AT: now, MIGRATED_EVIDENCE: evidence}
            bucket = "resolved"
        else:
            reason = "no corroborated ownership evidence; support review required"
            disposition = {**identity, "reason": reason}
            changes = {QUARANTINE_FLAG: True, QUARANTINE_AT: now, QUARANTINE_REASON: reason}
            bucket = "quarantined"
        if not dry_run:
            condition = {"_id": doc["_id"], "businessId": None, QUARANTINE_FLAG: {"$ne": True},
                         "customerId": doc.get("customerId"), "createdBy": doc.get("createdBy")}
            result = await coll.update_one(condition, {"$set": changes})
            if not result.matched_count:
                report["conflicts"].append(identity)
                continue
        report[bucket].append(disposition)
    return report


async def migrate_all(*, dry_run: bool = True) -> List[Dict[str, Any]]:
    reports = []
    for collection in MIGRATABLE_COLLECTIONS:
        cursor = None
        while True:
            page = await migrate_collection(collection, dry_run=dry_run, after_id=cursor)
            reports.append(page)
            cursor = page["nextCursor"]
            if not cursor:
                break
    return reports


async def list_quarantined(collection_name: str, *, after_id: Optional[str] = None) -> List[Dict[str, Any]]:
    if collection_name not in MIGRATABLE_COLLECTIONS:
        raise ValueError(f"{collection_name!r} is not in MIGRATABLE_COLLECTIONS")
    coll = getattr(db, collection_name)
    from bson import ObjectId
    query: Dict[str, Any] = {QUARANTINE_FLAG: True}
    if after_id:
        if not ObjectId.is_valid(after_id):
            raise ValueError("Invalid quarantine cursor")
        query["_id"] = {"$gt": ObjectId(after_id)}
    rows = await coll.find(query).sort("_id", 1).to_list(1000)
    return [{**{k: v for k, v in row.items() if k != "_id"}, "documentKey": str(row["_id"])} for row in rows]


async def resolve_quarantined(collection_name: str, doc_id: str, business_id: str, *, actor: str, evidence: str) -> Dict[str, Any]:
    """The authorised resolution workflow: a human explicitly assigns a
    quarantined document to a real business after reviewing it —
    routes/ownership_migration.py gates this behind the same
    owner + X-Support-Override pattern routes/licensing.py's ABN-change
    override already uses. Never called automatically."""
    if collection_name not in MIGRATABLE_COLLECTIONS:
        raise ValueError(f"{collection_name!r} is not in MIGRATABLE_COLLECTIONS")
    coll = getattr(db, collection_name)
    if not evidence or len(evidence.strip()) < 10:
        raise ValueError("A substantive ownership evidence note is required")
    from bson import ObjectId
    if not ObjectId.is_valid(doc_id):
        raise ValueError("Use documentKey from the quarantine listing")
    existing = await coll.find_one({"_id": ObjectId(doc_id)})
    if not existing:
        raise LookupError("document not found")
    if not existing.get(QUARANTINE_FLAG):
        raise ValueError("document is not quarantined")
    business = await db.businesses.find_one({"id": business_id}, {"_id": 0, "id": 1})
    if not business:
        raise ValueError("businessId does not match a real business")
    now = to_iso(now_utc())
    result = await coll.update_one(
        {"_id": existing["_id"], "businessId": None, QUARANTINE_FLAG: True},
        {
            "$set": {
                "businessId": business_id,
                MIGRATED_AT: now,
                MIGRATED_EVIDENCE: f"manually resolved by {actor}: {evidence}",
            },
            "$unset": {QUARANTINE_FLAG: "", QUARANTINE_AT: "", QUARANTINE_REASON: ""},
        },
    )
    if not result.matched_count:
        raise ValueError("Document ownership changed; rescan before resolving")
    from services.audit_service import log_event
    audit_logged = True
    try:
        await log_event(
            entity_type=collection_name, entity_id=doc_id, action="updated",
            after={"businessId": business_id},
            memo=f"Ownership migration: quarantined document manually resolved to business {business_id} by {actor}",
            severity="notice", tags=["ownership_migration"],
        )
    except Exception:
        audit_logged = False
        logging.getLogger(__name__).exception("Ownership resolved, but secondary audit sink failed")
    return {"id": doc_id, "businessId": business_id, "resolvedBy": actor, "resolvedAt": now, "auditLogged": audit_logged}
