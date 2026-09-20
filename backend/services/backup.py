"""Back up the venue's data, restore it, and prove the restore actually works.

An untested backup isn't a backup — it's a file nobody has opened since the
day it was written, and the first time anyone finds out whether it's usable
is the worst possible moment to learn it isn't. So this is built around one
idea: `run_restore_drill()` doesn't just create a backup, it restores that
backup into a disposable scratch database and checks the result matches,
end to end, on every call — not as a separate manual step someone has to
remember to run.

Format: one JSON array per collection, using `bson.json_util` so ObjectIds,
datetimes and everything else Mongo-specific round-trips exactly rather than
degrading to strings. Bundled into a single `.tar.gz` with a manifest
(collection names, document counts, a SHA-256 per file) so a backup can be
verified without touching a database at all — if the file on disk doesn't
match its own manifest, restoring it would be worse than not having it.

Deliberately conservative on the destructive path: `restore_into()` defaults
to upsert-by-id (merge), and only wipes a collection first when the caller
explicitly asks for it. A restore run against the wrong target should not be
able to silently erase what was already there.
"""
import hashlib
import io
import json
import logging
import tarfile
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from bson import json_util

from database import client, db as live_db
from middleware.actor_context import tenant_scope_filter

log = logging.getLogger(__name__)

# Collections worth backing up. Deliberately excludes the fully-ephemeral
# ones retention.py already expires on its own (kiosk_sessions, notifications,
# login_attempts, totp_used, trusted_devices, course_events) and error_log —
# restoring those from a week-old backup would be actively wrong, not merely
# useless, since a restored login lockout or a restored "already-used" TOTP
# code would reintroduce a stale security decision rather than a clean slate.
BACKUP_COLLECTIONS = [
    "auth_users", "products", "categories", "modifiers", "customers",
    "transactions", "refunds", "kitchen_orders", "reservations", "expenses",
    "suppliers", "bas_reports", "business_settings", "settings",
    "role_permissions", "vouchers", "loyalty_accounts", "staff_shifts",
    "audit_log", "coursing_config",
    # Tenant config collections added since the original list was written —
    # each one, if lost, means an owner has to manually reconstruct real
    # configuration (the venue's own record, booking rules, loyalty
    # program, table layout, cancellation policy) rather than restore it.
    # Deliberately excludes collections that are closer to live/ephemeral
    # session state than config — db.bill_splits/db.split_tabs/
    # db.split_groups (guest payment claims actively changing minute to
    # minute; restoring a stale snapshot could reopen an already-settled
    # bill), db.voice_calls (a call log, not configuration), and
    # db.booking_capacity_locks (a lock with a few seconds' TTL) — same
    # reasoning this module already applies to kiosk_sessions/notifications/
    # login_attempts/totp_used/trusted_devices/course_events above.
    "businesses", "cancellation_policies", "booking_blackouts",
    "floor_plans", "loyalty_config", "loyalty_tiers",
]


async def _collections_present(database) -> List[str]:
    existing = set(await database.list_collection_names())
    return [c for c in BACKUP_COLLECTIONS if c in existing]


async def create_backup(database=None, business_id: Optional[str] = None) -> bytes:
    """Dump every backed-up collection into one gzipped tar, in memory.

    Returns raw bytes so the caller decides what to do with them — stream as
    a download, write to disk, hand to an object-storage client. Nothing here
    assumes a particular filesystem, since where a backup should ultimately
    live (S3, a volume, wherever) is a deployment decision, not this
    function's.

    `business_id` scopes every collection to one business — without it,
    "Download Backup" (routes/ops.py's GET /ops/backup, owner-gated but
    with no tenant check of its own) dumped every business's customers,
    transactions, and auth_users (password hashes included) on the whole
    deployment into one archive any owner could download. Omitted (None)
    for the internal restore-drill use (run_restore_drill below), which
    deliberately verifies the *whole* database's backup/restore mechanics
    against a disposable scratch database — that's an infra self-check,
    not a data export, and never returns document content to a caller.
    A handful of the backed-up collections (staff_shifts among them) don't
    carry a businessId field at all yet — the same pre-existing schema gap
    documented elsewhere in TENANT_ISOLATION_REMAINING_WORK.md — so a
    scoped backup can still include those collections' full, unscoped
    contents; this closes the collections that do carry the field, not a
    100% guarantee across every collection in BACKUP_COLLECTIONS.
    """
    database = database if database is not None else live_db
    scope = tenant_scope_filter(business_id) if business_id else {}
    manifest = {"createdAt": datetime.now(timezone.utc).isoformat(),
               "database": database.name, "collections": {}}
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name in await _collections_present(database):
            # db.businesses is keyed and self-identified by "id", not
            # "businessId" (it IS the business) — tenant_scope_filter's
            # generic {"businessId": ...} match would always come back
            # empty for it, silently omitting the venue's own config
            # record from every scoped (per-tenant) backup.
            coll_scope = {"id": business_id} if (name == "businesses" and business_id) else scope
            docs = await database[name].find(coll_scope).to_list(None)
            payload = json_util.dumps(docs).encode("utf-8")
            manifest["collections"][name] = {
                "count": len(docs),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
            info = tarfile.TarInfo(name=f"{name}.json")
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))

        manifest_bytes = json.dumps(manifest, indent=2).encode("utf-8")
        info = tarfile.TarInfo(name="manifest.json")
        info.size = len(manifest_bytes)
        tar.addfile(info, io.BytesIO(manifest_bytes))

    return buf.getvalue()


def verify_backup(archive: bytes) -> dict:
    """Check the archive against its own manifest without touching a
    database — a corrupt or truncated backup should be catchable on the file
    alone, before anyone tries to restore from it under pressure.

    Deliberately catches everything: a flipped byte can corrupt the gzip
    stream itself and make tarfile/json raise from deep inside the standard
    library rather than failing the checksum comparison cleanly. Either way
    the answer is the same — this archive can't be trusted — so any failure
    to even read it is reported the same way as a checksum mismatch, not
    allowed to propagate as a raw exception.
    """
    try:
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
            names = set(tar.getnames())
            if "manifest.json" not in names:
                return {"ok": False, "problems": ["manifest.json missing"]}
            manifest = json.loads(tar.extractfile("manifest.json").read())
            problems = []
            for coll, meta in manifest.get("collections", {}).items():
                fname = f"{coll}.json"
                if fname not in names:
                    problems.append(f"{fname} listed in manifest but missing from archive")
                    continue
                payload = tar.extractfile(fname).read()
                actual_hash = hashlib.sha256(payload).hexdigest()
                if actual_hash != meta.get("sha256"):
                    problems.append(f"{fname} checksum mismatch — file may be corrupted or truncated")
                    continue  # a corrupted payload isn't safe to json_util.loads
                docs = json_util.loads(payload)
                if len(docs) != meta.get("count"):
                    problems.append(f"{fname} has {len(docs)} documents, manifest says {meta.get('count')}")
        return {"ok": not problems, "problems": problems, "manifest": manifest}
    except Exception as e:
        return {"ok": False, "problems": [f"archive unreadable: {type(e).__name__}: {e}"]}


async def restore_into(archive: bytes, database, *, wipe: bool = False) -> dict:
    """Restore an archive into `database`. Upserts by `id` unless `wipe=True`,
    in which case each collection is emptied first — the explicit, opt-in
    path for a genuine disaster-recovery restore rather than the default.

    Every collection in this app keys on its own string `id` field; Mongo's
    `_id` is incidental and gets auto-assigned differently in every
    environment. Restoring by `$set`-ing everything except `_id` (rather than
    `replace_one` on the whole document) means a document already present in
    the target — with a different, unrelated `_id` from whenever it was
    created there — gets its fields updated in place instead of the restore
    failing outright, which is what happens if `_id` is asked to change to
    match the backup's copy.
    """
    result = {}
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        manifest = json.loads(tar.extractfile("manifest.json").read())
        for coll in manifest.get("collections", {}):
            docs = json_util.loads(tar.extractfile(f"{coll}.json").read())
            if wipe:
                await database[coll].delete_many({})
            restored = 0
            for doc in docs:
                fields = {k: v for k, v in doc.items() if k != "_id"}
                # Most collections key on their own string "id", but a
                # handful of per-business singleton config documents
                # (cancellation_policies, business_settings, settings,
                # role_permissions, coursing_config) have no "id" field at
                # all — they're looked up by "businessId" or "key" alone.
                # Falling straight through to "_id" for those would upsert
                # by the BACKUP's original (unrelated) ObjectId on a merge
                # restore into a database that already has its own copy of
                # that config under a different _id, creating a duplicate
                # singleton instead of updating the existing one.
                if "id" in doc:
                    key = {"id": doc["id"]}
                elif "businessId" in doc:
                    key = {"businessId": doc["businessId"]}
                elif "key" in doc:
                    key = {"key": doc["key"]}
                else:
                    key = {"_id": doc["_id"]}
                await database[coll].update_one(key, {"$set": fields}, upsert=True)
                restored += 1
            result[coll] = restored
    return result


async def run_restore_drill() -> dict:
    """Back up the live database, restore that exact backup into a disposable
    scratch database, compare document counts, then drop the scratch database.

    This is the whole point: a backup nobody has ever restored is a claim,
    not a fact. Running the real restore path against a throwaway target
    (never the live database) on every call is what turns "we take backups"
    into something an owner can trust without taking it on faith.
    """
    drill_name = f"{live_db.name}_restore_drill_{uuid.uuid4().hex[:8]}"
    scratch = client[drill_name]
    report = {"startedAt": datetime.now(timezone.utc).isoformat(), "collections": {}}
    try:
        archive = await create_backup(live_db)
        verification = verify_backup(archive)
        report["archiveVerified"] = verification["ok"]
        report["archiveProblems"] = verification["problems"]
        if not verification["ok"]:
            report["ok"] = False
            return report

        await restore_into(archive, scratch, wipe=True)

        ok = True
        for coll in await _collections_present(live_db):
            live_count = await live_db[coll].count_documents({})
            restored_count = await scratch[coll].count_documents({})
            matches = live_count == restored_count
            ok = ok and matches
            report["collections"][coll] = {
                "liveCount": live_count, "restoredCount": restored_count, "matches": matches,
            }
        report["ok"] = ok
        return report
    finally:
        try:
            await client.drop_database(drill_name)
        except Exception as e:
            log.warning("failed to drop restore-drill scratch database %s: %s", drill_name, e)
