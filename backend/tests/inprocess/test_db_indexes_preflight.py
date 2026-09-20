"""Final pre-merge assurance pass: rollout safety for services/db_indexes.py.

Three scenarios a real deployment can be in when this runs on startup:
fresh DB (no collections yet), an existing single-business DB (only legacy
untagged singleton documents, pre-dating businessId), and a partially-
migrated/corrupted DB (duplicate documents that would violate one of the
new unique indexes). The third one must not be able to take the other
indexes down with it — a single try/except around the whole function used
to mean one duplicate-key failure silently skipped every index after it.
"""
import asyncio

from database import db
from services.db_indexes import ensure_indexes, preflight_duplicate_report

COLLECTIONS_TOUCHED = [
    "transactions", "kitchen_orders", "customers", "products", "expenses",
    "reservations", "payment_session_claims", "settings", "loyalty_config",
    "ash_tool_config", "business_settings", "table_course_settings", "agent_autonomy",
]


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _cleanup():
    # drop(), not delete_many({}) — these tests each assert on which
    # indexes exist, and mongomock (like real Mongo) keeps indexes around
    # across a delete_many. Dropping the collection outright gives every
    # test a genuinely fresh collection, same as a fresh database.
    for name in COLLECTIONS_TOUCHED:
        _run(db[name].drop())


def test_fresh_database_creates_every_index_with_no_duplicates_reported():
    """No collections exist yet — the common case (a brand new venue, or
    this being the first deployment ever). Every create_index call is a
    plain no-op-if-exists creation, and the preflight check should find
    nothing to report."""
    _cleanup()
    try:
        findings = _run(preflight_duplicate_report())
        assert findings == [], f"a fresh database must never report duplicates: {findings}"

        _run(ensure_indexes())

        settings_idx = _run(db.settings.index_information())
        assert any(
            set(spec) == {("key", 1), ("businessId", 1)} and info.get("unique")
            for spec, info in ((tuple(i["key"]), i) for i in settings_idx.values())
        ), f"settings unique compound index missing on a fresh DB: {settings_idx}"

        txn_idx = _run(db.transactions.index_information())
        assert "clientOpId_1" in txn_idx and txn_idx["clientOpId_1"].get("unique"), txn_idx
    finally:
        _cleanup()


def test_existing_single_business_database_with_only_legacy_documents_migrates_cleanly():
    """An existing, pre-tenant-scoping deployment: one untagged (no
    businessId) document per settings key, exactly as tenant_settings.py's
    "falls back to the legacy document" design expects. This is NOT a
    duplicate — MongoDB's unique index treats the missing businessId as a
    single null value per key, and there is only one such document per
    key here — so the index must still be created successfully, and the
    legacy documents must still be readable afterwards (no data loss)."""
    _cleanup()
    try:
        _run(db.settings.insert_one({"key": "print_routing", "value": {"legacy": True}}))
        _run(db.loyalty_config.insert_one({"id": "default", "pointsExpiryDays": 365}))

        findings = _run(preflight_duplicate_report())
        assert findings == [], f"one legacy document per key must not be flagged as a duplicate: {findings}"

        _run(ensure_indexes())

        settings_idx = _run(db.settings.index_information())
        assert any(
            set(tuple(i["key"])) == {("key", 1), ("businessId", 1)} and i.get("unique")
            for i in settings_idx.values()
        ), "unique index must still be created when there's exactly one legacy doc per key"

        # No data loss: the legacy document is still there, untouched.
        still_there = _run(db.settings.find_one({"key": "print_routing"}, {"_id": 0}))
        assert still_there == {"key": "print_routing", "value": {"legacy": True}}
    finally:
        _cleanup()


def test_partially_migrated_database_with_duplicates_is_reported_and_does_not_block_other_indexes():
    """The bad case this whole mechanism exists for: something (a bug
    predating this migration, a manual DB edit, a bad restore) left two
    documents matching the same unique-index key. Index creation for that
    one collection must fail loudly and specifically — not crash the
    process, and not silently skip every index that would have been
    created after it in the function."""
    _cleanup()
    try:
        _run(db.settings.insert_many([
            {"key": "print_routing", "value": {"a": 1}},
            {"key": "print_routing", "value": {"a": 2}},  # duplicate: same key, still no businessId
        ]))

        findings = _run(preflight_duplicate_report())
        assert len(findings) == 1
        assert findings[0]["collection"] == "settings"
        assert findings[0]["match"] == {"key": "print_routing"}
        assert findings[0]["count"] == 2
        assert len(findings[0]["examples"]) == 2, "should name the actual offending document ids"

        _run(ensure_indexes())  # must not raise

        # The settings unique index could not be created...
        settings_idx = _run(db.settings.index_information())
        assert not any(
            set(tuple(i["key"])) == {("key", 1), ("businessId", 1)} and i.get("unique")
            for i in settings_idx.values()
        ), "the unique index must NOT exist while duplicates are present"

        # ...but every other index in the same ensure_indexes() call still
        # got created — one collection's duplicate-key failure must not
        # take out the rest of the function.
        txn_idx = _run(db.transactions.index_information())
        assert "clientOpId_1" in txn_idx
        loyalty_idx = _run(db.loyalty_config.index_information())
        assert any(
            set(tuple(i["key"])) == {("id", 1), ("businessId", 1)} and i.get("unique")
            for i in loyalty_idx.values()
        ), "a duplicate in settings must not prevent loyalty_config's own unique index from being created"

        # Both duplicate documents are still there — nothing was silently
        # deleted or merged; remediation is a deliberate, manual step.
        both = _run(db.settings.find({"key": "print_routing"}, {"_id": 0}).to_list(10))
        assert len(both) == 2
    finally:
        _cleanup()
