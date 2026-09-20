"""Indexes for the collections every shift actually hits.

Before this, the whole backend had four indexes: one unique index on login
email, and three TTL indexes added alongside the coursing and 2FA work. Every
other query — the transaction history, the customer list, the kitchen board,
the product catalogue — was a full collection scan. That's invisible on a demo
database with a few hundred rows and it stays invisible right up until a real
venue has a year of trading behind it, at which point the P&L takes seconds
and the floor tablets start to lag mid-service.

This is additive only: creating an index that already exists is a no-op, so
this can run on every startup without special-casing "first run" vs
"upgrading an existing venue". mongomock (used by the test suite) accepts the
same calls, so nothing here is production-only code that never gets exercised.
"""
import logging
from typing import Any, Dict, List

from database import db

log = logging.getLogger(__name__)


async def _create_index_safely(collection, keys, **kwargs) -> None:
    """One index at a time, its own try/except, so a single failure (a
    duplicate-key conflict on a unique index, a transient hiccup) can't take
    out every index after it in the same startup pass the way one shared
    try/except around the whole function would. A `unique=True` index that
    can't be created because production data already violates uniqueness is
    exactly the case that most needs its own diagnostic, not a generic
    "index creation failed" line that swallows which one and why.
    """
    label = keys if isinstance(keys, str) else str(keys)
    try:
        await collection.create_index(keys, **kwargs)
    except Exception as e:
        if kwargs.get("unique"):
            log.error(
                "UNIQUE INDEX NOT CREATED: %s.%s (%s) — %s. This almost always means duplicate "
                "records already exist for this key in production. Remediation: run the matching "
                "duplicate-detection query in services/db_indexes.py's preflight_duplicate_report(), "
                "manually resolve/merge the duplicates it lists, then restart — index creation is "
                "retried on every startup, so nothing else needs to change once the data is clean. "
                "Until then this collection runs WITHOUT the uniqueness guarantee this index exists "
                "to enforce.",
                getattr(collection, "name", collection), label, kwargs, e,
            )
        else:
            log.warning("Index creation failed (non-fatal, non-unique): %s.%s — %s",
                        getattr(collection, "name", collection), label, e)


async def preflight_duplicate_report() -> list:
    """Run BEFORE attempting any unique index below, so a duplicate-key
    failure is reported with the actual offending records (up to 5 examples
    per group) instead of just a driver exception. Safe to call on a fresh,
    empty, or partially-migrated database — an aggregation over zero or a
    few thousand documents is cheap, and finding nothing is the expected,
    common case.

    Returns a list of {"collection", "match", "count", "examples"} dicts —
    empty means clean. Also logged at ERROR so it shows up in normal
    deployment logs without the caller needing to do anything with the
    return value.
    """
    checks = [
        ("transactions", {"clientOpId": {"$exists": True, "$ne": None}}, ["clientOpId"]),
        ("payment_session_claims", {"claimKey": {"$exists": True, "$ne": None}}, ["claimKey"]),
        # Tenant-setting scoped singletons (services/tenant_settings.py) —
        # each should have at most one document per (match key, businessId).
        ("settings", {}, ["key", "businessId"]),
        ("loyalty_config", {}, ["id", "businessId"]),
        ("ash_tool_config", {}, ["toolName", "businessId"]),
        ("business_settings", {}, ["key", "businessId"]),
        ("table_course_settings", {}, ["scope", "businessId"]),
        ("agent_autonomy", {}, ["id", "businessId"]),
        ("businesses", {"inboundVoiceNumber": {"$exists": True, "$ne": None}}, ["inboundVoiceNumber"]),
    ]
    findings = []
    for coll_name, pre_filter, group_fields in checks:
        try:
            collection = db[coll_name]
            group_id = {f: f"${f}" for f in group_fields}
            pipeline: List[Dict[str, Any]] = [
                {"$match": pre_filter} if pre_filter else {"$match": {}},
                {"$group": {"_id": group_id, "count": {"$sum": 1}, "docIds": {"$push": "$_id"}}},
                {"$match": {"count": {"$gt": 1}}},
                {"$limit": 20},
            ]
            dupes = await collection.aggregate(pipeline).to_list(20)
            for d in dupes:
                finding = {
                    "collection": coll_name, "match": d["_id"], "count": d["count"],
                    "examples": [str(x) for x in (d.get("docIds") or [])[:5]],
                }
                findings.append(finding)
                log.error(
                    "DUPLICATE RECORDS FOUND: db.%s has %s documents matching %s — a unique index "
                    "on %s cannot be created until these are merged/deleted. Example _ids: %s. "
                    "Run: db.%s.find(%s) to inspect them.",
                    coll_name, d["count"], d["_id"], group_fields, finding["examples"],
                    coll_name, d["_id"],
                )
        except Exception as e:
            # A collection that doesn't exist yet (fresh DB) or an
            # aggregation this particular mongo version doesn't like is not
            # itself a problem worth failing startup over — the actual
            # create_index call below will surface a real duplicate-key
            # error if one exists, this is just an earlier, friendlier
            # warning when it can be produced.
            log.info("preflight duplicate check skipped for %s: %s", coll_name, e)
    return findings


async def ensure_indexes() -> None:
    await preflight_duplicate_report()

    # Transactions: the busiest collection in the system. timestamp backs
    # every dashboard's date filter; customerId backs the profile/wallet
    # lookups; tableNumber backs the running-tab-per-table screens.
    await _create_index_safely(db.transactions, "timestamp")
    await _create_index_safely(db.transactions, "customerId")
    await _create_index_safely(db.transactions, "tableNumber")
    # sparse: most transactions have no clientOpId at all (only the
    # offline queue's replayed sales set one) — sparse excludes those
    # from the uniqueness constraint entirely rather than treating a
    # missing field as a colliding null. This is what actually enforces
    # the offline-replay dedup in routes/transactions.py's
    # create_transaction — the index, not application logic, is the
    # atomic guard (a race between two concurrent inserts of the same
    # clientOpId is decided by MongoDB rejecting the second one, not by
    # a Python-side check that could itself race).
    await _create_index_safely(db.transactions, "clientOpId", unique=True, sparse=True)

    # Kitchen board: filtered by status constantly (KDS polling/SSE), and
    # sorted by createdAt within a status.
    await _create_index_safely(db.kitchen_orders, [("status", 1), ("createdAt", 1)])
    await _create_index_safely(db.kitchen_orders, "tableNumber")
    await _create_index_safely(db.kitchen_orders, "transactionId")

    # Customers: search is a case-insensitive regex over these three
    # fields (routes/customers.py), and lookups by id happen everywhere
    # wallets, vouchers and loyalty touch a customer.
    await _create_index_safely(db.customers, "email")
    await _create_index_safely(db.customers, "phone")
    await _create_index_safely(db.customers, "id", unique=True)

    # Products: category is the single most common filter (POS category
    # bar, storefront, kiosk); id is looked up constantly for pricing.
    await _create_index_safely(db.products, "category")
    await _create_index_safely(db.products, "id", unique=True)

    # Expenses and suppliers feed the accounting reports, filtered by
    # date range and category.
    await _create_index_safely(db.expenses, "date")
    await _create_index_safely(db.expenses, "category")

    # Reservations: looked up by date for the pre-shift dashboard and
    # by table for the floor plan.
    await _create_index_safely(db.reservations, "date")
    await _create_index_safely(db.reservations, "tableNumber")

    # Checkout-session idempotency claims (services/payment_idempotency.py)
    # — sparse-unique on claimKey is the real atomic guard against two
    # concurrent requests both creating a Stripe/Coinbase session for the
    # same cart/order; see that module's own docstring. expiresAt is
    # storage hygiene only (the module's own staleness check is what
    # governs whether a claim is actually reused).
    await _create_index_safely(db.payment_session_claims, "claimKey", unique=True, sparse=True)
    await _create_index_safely(db.payment_session_claims, "expiresAt", expireAfterSeconds=0)

    # Tenant-setting scoped singletons (services/tenant_settings.py's
    # get_scoped_singleton/set_scoped_singleton) — each is a per-business
    # upsert keyed on its own match fields plus businessId. update_one's
    # upsert is atomic per MongoDB's own semantics even without a backing
    # index, but every other exactly-once guarantee in this codebase
    # (payment claims above, offline-replay dedup) treats the unique index
    # as the real guard rather than trusting application-level atomicity
    # alone — same reasoning applies here. businessId is legitimately
    # absent on legacy pre-migration documents (tenant_settings.py's own
    # "falls back to the untagged document" design), and there is at most
    # one such untagged document per match-key by construction (these were
    # true global singletons before businessId existed at all), so a plain
    # unique index — not sparse — is correct: MongoDB treats a missing
    # field as null in a unique index, and null collides with null exactly
    # the way it should here (one legacy document per key, not per key+doc).
    await _create_index_safely(db.settings, [("key", 1), ("businessId", 1)], unique=True)
    await _create_index_safely(db.loyalty_config, [("id", 1), ("businessId", 1)], unique=True)
    await _create_index_safely(db.ash_tool_config, [("toolName", 1), ("businessId", 1)], unique=True)
    await _create_index_safely(db.business_settings, [("key", 1), ("businessId", 1)], unique=True)
    await _create_index_safely(db.table_course_settings, [("scope", 1), ("businessId", 1)], unique=True)
    await _create_index_safely(db.agent_autonomy, [("id", 1), ("businessId", 1)], unique=True)

    # Inbound-voice number → business mapping (routes/voice_inbound.py) —
    # sparse (most businesses never set one) and unique, so two businesses
    # can never both claim the same Twilio number even if the write-side
    # check in inbound_config racing itself somehow let one through. This
    # is the preventive half; _resolve_business_by_dialled_number's own
    # "more than one match → refuse" check is the defensive half for a
    # deployment where duplicates already existed before this index did.
    await _create_index_safely(db.businesses, "inboundVoiceNumber", unique=True, sparse=True)
