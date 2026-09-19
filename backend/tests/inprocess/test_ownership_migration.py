"""services/ownership_migration.py + routes/ownership_migration.py —
tenant-ownership release-closure pass, task #68: a dry-run-first,
idempotent legacy migration that assigns ownership only from reliable
evidence, quarantines what it can't resolve, and exposes a separate,
support-override-gated workflow to resolve a quarantined document by
hand. Never auto-assigns to the first business, never deletes a
document, never exposes quarantined data across a normal tenant-scoped
endpoint (that boundary is tenant_owns_strict's job, unchanged by this
migration — see middleware/actor_context.py).
"""
import asyncio

from database import db
from tests.inprocess.conftest import req
from services import ownership_migration as migration


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


SUPPORT_HEADER = {"X-Support-Override": "test-only-support-override-key"}


def _make_business(client, owner_headers, *, biz_id, email):
    _run(db.businesses.insert_one({
        "id": biz_id, "slug": biz_id, "name": f"Biz {biz_id}", "status": "active",
    }))
    client.post("/api/auth/register", headers=owner_headers, json={
        "name": "Migration Test Owner", "email": email, "password": "MigrationTest2026!",
    })
    _run(db.auth_users.update_one({"email": email}, {"$set": {"role": "owner", "businessId": biz_id}}))
    r = client.post("/api/auth/login", json={"email": email, "password": "MigrationTest2026!"})
    assert r.status_code == 200, f"login failed: {r.text[:200]}"
    client.cookies.clear()
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _cleanup_business(biz_id):
    _run(db.businesses.delete_many({"id": biz_id}))
    _run(db.auth_users.delete_many({"businessId": biz_id}))


def test_migrate_collection_rejects_a_collection_not_on_the_allowlist():
    import pytest
    with pytest.raises(ValueError):
        _run(migration.migrate_collection("auth_users", dry_run=True))


def test_dry_run_reports_a_resolution_but_writes_nothing(client, owner_headers):
    customer_id = "MIG-CUST-1"
    doc_id = "MIG-APPT-1"
    _run(db.customers.insert_one({"id": customer_id, "businessId": "default", "name": "X", "email": "migcust1@nua.com", "phone": "1"}))
    _run(db.appointments.insert_one({
        "id": doc_id, "customerId": customer_id, "createdBy": "owner@nua.com", "customerName": "X", "serviceId": "s1",
        "date": "2027-01-01", "time": "10:00", "status": "confirmed", "businessId": None,
    }))
    try:
        report = _run(migration.migrate_collection("appointments", dry_run=True))
        matches = [r for r in report["resolved"] if r["id"] == doc_id]
        assert len(matches) == 1, report
        assert matches[0]["businessId"] == "default"

        still_untagged = _run(db.appointments.find_one({"id": doc_id}, {"_id": 0}))
        assert still_untagged["businessId"] is None, "a dry run must never write"
        assert migration.MIGRATED_AT not in still_untagged
    finally:
        _run(db.appointments.delete_many({"id": doc_id}))
        _run(db.customers.delete_many({"id": customer_id}))


def test_real_run_resolves_via_a_linked_customers_businessId(client, owner_headers):
    customer_id = "MIG-CUST-2"
    doc_id = "MIG-APPT-2"
    _run(db.customers.insert_one({"id": customer_id, "businessId": "default", "name": "Y", "email": "migcust2@nua.com", "phone": "2"}))
    _run(db.appointments.insert_one({
        "id": doc_id, "customerId": customer_id, "createdBy": "owner@nua.com", "customerName": "Y", "serviceId": "s1",
        "date": "2027-01-01", "time": "11:00", "status": "confirmed", "businessId": None,
    }))
    try:
        report = _run(migration.migrate_collection("appointments", dry_run=False))
        matches = [r for r in report["resolved"] if r["id"] == doc_id]
        assert len(matches) == 1, report

        migrated = _run(db.appointments.find_one({"id": doc_id}, {"_id": 0}))
        assert migrated["businessId"] == "default"
        assert migrated[migration.MIGRATED_AT]
        assert customer_id in migrated[migration.MIGRATED_EVIDENCE]
    finally:
        _run(db.appointments.delete_many({"id": doc_id}))
        _run(db.customers.delete_many({"id": customer_id}))


def test_real_run_quarantines_an_unresolvable_document_never_deletes_it(client, owner_headers):
    other = _make_business(client, owner_headers, biz_id="mig-ambig-biz", email="mig-ambig-owner@nua.com")
    doc_id = "MIG-APPT-3"
    _run(db.appointments.insert_one({
        "id": doc_id, "customerName": "No Link Guest", "serviceId": "s1",
        "date": "2027-01-01", "time": "12:00", "status": "confirmed", "businessId": None,
    }))
    try:
        report = _run(migration.migrate_collection("appointments", dry_run=False))
        matches = [q for q in report["quarantined"] if q["id"] == doc_id]
        assert len(matches) == 1, report

        row = _run(db.appointments.find_one({"id": doc_id}, {"_id": 0}))
        assert row is not None, "quarantine must never delete the document"
        assert row["businessId"] is None, "quarantine must never guess/assign an owner"
        assert row[migration.QUARANTINE_FLAG] is True
    finally:
        _run(db.appointments.delete_many({"id": doc_id}))
        _cleanup_business("mig-ambig-biz")


def test_migration_is_idempotent_across_repeated_real_runs(client, owner_headers):
    other = _make_business(client, owner_headers, biz_id="mig-idem-biz", email="mig-idem-owner@nua.com")
    doc_id = "MIG-APPT-4"
    _run(db.appointments.insert_one({
        "id": doc_id, "customerName": "Idempotency Guest", "serviceId": "s1",
        "date": "2027-01-01", "time": "13:00", "status": "confirmed", "businessId": None,
    }))
    try:
        first = _run(migration.migrate_collection("appointments", dry_run=False))
        assert any(q["id"] == doc_id for q in first["quarantined"])

        second = _run(migration.migrate_collection("appointments", dry_run=False))
        assert not any(q["id"] == doc_id for q in second["quarantined"]), (
            "a second run must not re-flag an already-quarantined document as newly quarantined"
        )
        assert second["alreadyQuarantined"] >= 1

        row = _run(db.appointments.find_one({"id": doc_id}, {"_id": 0}))
        assert row[migration.QUARANTINE_FLAG] is True
        first_quarantined_at = row[migration.QUARANTINE_AT]

        third = _run(migration.migrate_collection("appointments", dry_run=False))
        row_after = _run(db.appointments.find_one({"id": doc_id}, {"_id": 0}))
        assert row_after[migration.QUARANTINE_AT] == first_quarantined_at, (
            "idempotent means unchanged on repeat — the quarantine timestamp must not be rewritten"
        )
    finally:
        _run(db.appointments.delete_many({"id": doc_id}))
        _cleanup_business("mig-idem-biz")


def test_resolve_quarantined_requires_matching_support_override_header(client, owner_headers):
    doc_id = "MIG-APPT-5"
    _run(db.appointments.insert_one({
        "id": doc_id, "customerName": "Needs Resolution", "serviceId": "s1",
        "date": "2027-01-01", "time": "14:00", "status": "confirmed", "businessId": None,
        migration.QUARANTINE_FLAG: True,
    }))
    try:
        no_header = req(client, "POST", f"/api/admin/ownership-migration/quarantined/appointments/{doc_id}/resolve",
                         headers=owner_headers, json={"businessId": "default", "evidence": "Reviewed original signed booking export"})
        assert no_header.status_code == 403, no_header.text[:200]

        wrong_header = req(client, "POST", f"/api/admin/ownership-migration/quarantined/appointments/{doc_id}/resolve",
                            headers={**owner_headers, "X-Support-Override": "wrong-key"},
                            json={"businessId": "default", "evidence": "Reviewed original signed booking export"})
        assert wrong_header.status_code == 403, wrong_header.text[:200]

        row = _run(db.appointments.find_one({"id": doc_id}, {"_id": 0}))
        assert row["businessId"] is None, "a rejected resolve attempt must never assign ownership"
    finally:
        _run(db.appointments.delete_many({"id": doc_id}))


def test_resolve_quarantined_with_valid_override_assigns_and_clears_quarantine(client, owner_headers):
    doc_id = "MIG-APPT-6"
    _run(db.appointments.insert_one({
        "id": doc_id, "customerName": "Support Resolved Guest", "serviceId": "s1",
        "date": "2027-01-01", "time": "15:00", "status": "confirmed", "businessId": None,
        migration.QUARANTINE_FLAG: True, migration.QUARANTINE_AT: "2026-01-01T00:00:00Z",
        migration.QUARANTINE_REASON: "no reliable evidence of ownership found",
    }))
    try:
        document_key = str(_run(db.appointments.find_one({"id": doc_id}))["_id"])
        r = req(client, "POST", f"/api/admin/ownership-migration/quarantined/appointments/{document_key}/resolve",
                headers={**owner_headers, **SUPPORT_HEADER}, json={"businessId": "default", "evidence": "Reviewed original signed booking export"})
        assert r.status_code == 200, r.text[:200]

        row = _run(db.appointments.find_one({"id": doc_id}, {"_id": 0}))
        assert row["businessId"] == "default"
        assert migration.QUARANTINE_FLAG not in row
        assert migration.MIGRATED_AT in row

        audit = _run(db.audit_events.find_one(
            {"entityType": "appointments", "entityId": document_key, "action": "updated"}, {"_id": 0}))
        assert audit is not None, "a manual resolution must leave an audit trail"
    finally:
        _run(db.appointments.delete_many({"id": doc_id}))


def test_scan_and_run_endpoints_require_owner_auth(anon):
    scan = req(anon, "POST", "/api/admin/ownership-migration/scan/appointments")
    assert scan.status_code == 401
    run = req(anon, "POST", "/api/admin/ownership-migration/run/appointments")
    assert run.status_code == 401


def test_run_endpoint_requires_support_override_even_for_an_owner(client, owner_headers):
    r = req(client, "POST", "/api/admin/ownership-migration/run/appointments", headers=owner_headers)
    assert r.status_code == 403, r.text[:200]
