"""Regression coverage for the gaps found in the completion-verdict review."""
import asyncio
import uuid

import pytest

from database import db
from conftest import req
from services import ownership_migration as migration


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture
def records():
    prefix = "takeover-" + uuid.uuid4().hex
    yield prefix
    for collection in ("customers", "reservations", "feedback", "appointments", "businesses", "auth_users"):
        run(db[collection].delete_many({"id": {"$regex": "^" + prefix}}))


def customer(doc_id, business_id=None, **extra):
    return {"id": doc_id, "name": "Isolation guest", "email": "isolation@example.com",
            "phone": "0400000000", "businessId": business_id, "storeCredit": 50, **extra}


@pytest.mark.parametrize("ownership", [None, "other-business"])
def test_customer_reads_and_credit_reject_unknown_or_other_owner(client, owner_headers, records, ownership):
    run(db.customers.insert_one(customer(records, ownership)))
    for method, path, payload in (
        ("GET", f"/api/customers/{records}/profile", None),
        ("GET", f"/api/customers/{records}/wallet", None),
        ("POST", f"/api/customers/{records}/store-credit/redeem", {"amount": 10}),
        ("PUT", f"/api/customers/{records}", {"name": "Stolen"}),
    ):
        response = req(client, method, path, headers=owner_headers, json=payload)
        assert response.status_code == 404, response.text
    row = run(db.customers.find_one({"id": records}))
    assert row["storeCredit"] == 50 and row["name"] == "Isolation guest"


def test_quarantine_is_hidden_from_lists_and_direct_access(client, owner_headers, records):
    run(db.customers.insert_one(customer(records, "default", _ownershipQuarantined=True)))
    response = req(client, "GET", "/api/customers", headers=owner_headers)
    assert response.status_code == 200
    assert records not in {row["id"] for row in response.json()}
    response = req(client, "GET", f"/api/customers/{records}/profile", headers=owner_headers)
    assert response.status_code == 404


def test_profile_history_cannot_join_other_venue_by_email(client, owner_headers, records):
    run(db.customers.insert_one(customer(records, "default")))
    run(db.reservations.insert_many([
        {"id": records + "-own", "businessId": "default", "guestEmail": "isolation@example.com"},
        {"id": records + "-other", "businessId": "other-business", "guestEmail": "isolation@example.com"},
    ]))
    response = req(client, "GET", f"/api/customers/{records}/profile", headers=owner_headers)
    assert response.status_code == 200
    assert {r["id"] for r in response.json()["reservationHistory"]} == {records + "-own"}


def test_feedback_cannot_modify_other_venue_customer(client, owner_headers, records):
    run(db.customers.insert_one(customer(records, "other-business")))
    response = req(client, "POST", "/api/feedback", headers=owner_headers,
                   json={"customerId": records, "rating": 1})
    assert response.status_code == 404
    run(db.feedback.insert_one({"id": records, "businessId": "other-business", "rating": 1}))
    response = req(client, "PUT", f"/api/feedback/{records}/respond", headers=owner_headers)
    assert response.status_code == 404
    response = req(client, "GET", "/api/feedback", headers=owner_headers)
    assert records not in {r["id"] for r in response.json()}


def test_migration_preview_requires_support_even_for_owner(client, owner_headers):
    response = req(client, "POST", "/api/admin/ownership-migration/scan/customers", headers=owner_headers)
    assert response.status_code == 403


def test_migration_pages_skip_old_quarantine_and_preserve_records(records):
    run(db.appointments.insert_many([
        {"id": records + "-old", "businessId": None, "_ownershipQuarantined": True},
        *[{"id": records + f"-{i}", "businessId": None} for i in range(5)],
    ]))
    cursor = None
    seen = set()
    while True:
        page = run(migration.migrate_collection("appointments", dry_run=False, batch_size=2, after_id=cursor))
        seen.update(r["id"] for r in page["quarantined"] if r["id"].startswith(records))
        cursor = page["nextCursor"]
        if not cursor:
            break
    assert seen == {records + f"-{i}" for i in range(5)}
    assert run(db.appointments.count_documents({"id": {"$regex": "^" + records}})) == 6
    repeat = run(migration.migrate_collection("appointments", dry_run=False))
    assert not any(r["id"].startswith(records) for r in repeat["quarantined"])


def test_migration_does_not_overwrite_concurrent_ownership(monkeypatch, records):
    run(db.appointments.insert_one({"id": records, "businessId": None}))
    original = migration._resolve_ownership

    async def race(doc):
        if doc.get("id") == records:
            await db.appointments.update_one({"_id": doc["_id"]}, {"$set": {"businessId": "other-business"}})
            return "default", "stale evidence"
        return await original(doc)

    monkeypatch.setattr(migration, "_resolve_ownership", race)
    report = run(migration.migrate_collection("appointments", dry_run=False))
    assert records in {r["id"] for r in report["conflicts"]}
    assert run(db.appointments.find_one({"id": records}))["businessId"] == "other-business"


def test_linked_customer_alone_is_not_trusted_migration_evidence(records):
    run(db.customers.insert_one(customer(records, "default")))
    run(db.appointments.insert_one({"id": records, "customerId": records}))
    report = run(migration.migrate_collection("appointments", dry_run=False))
    assert records in {r["id"] for r in report["quarantined"]}


def test_registration_cannot_self_assign_membership(client, owner_headers, records):
    client.cookies.clear()
    payload = {"name": "Intruder", "email": records + "@example.com", "password": "TestPassword2026!",
               "businessId": "other-business"}
    response = req(client, "POST", "/api/auth/register", json=payload)
    assert response.status_code == 401
    response = req(client, "POST", "/api/auth/register", headers=owner_headers, json=payload)
    assert response.status_code == 403
    assert run(db.auth_users.find_one({"email": payload["email"]})) is None


def test_old_backfill_cannot_claim_unowned_data(client, owner_headers, records):
    run(db.customers.insert_one(customer(records)))
    response = req(client, "POST", "/api/business/backfill-tenant", headers=owner_headers)
    assert response.status_code == 410
    assert run(db.customers.find_one({"id": records}))["businessId"] is None


@pytest.mark.parametrize("ownership,quarantined", [(None, False), ("other-business", False), ("default", True)])
def test_purchase_order_and_kitchen_mutations_fail_closed(client, owner_headers, records, ownership, quarantined):
    for collection in ("purchase_orders", "kitchen_orders"):
        run(db[collection].insert_one({"id": records, "businessId": ownership,
                                      "_ownershipQuarantined": quarantined, "status": "draft", "items": []}))
    try:
        response = req(client, "POST", f"/api/purchase-orders/{records}/approve", headers=owner_headers)
        assert response.status_code == 404, response.text
        response = req(client, "POST", f"/api/coursing/orders/{records}/add-round", headers=owner_headers,
                       json={"items": [{"productId": "irrelevant", "quantity": 1, "price": 1}]})
        assert response.status_code == 404, response.text
        for collection in ("purchase_orders", "kitchen_orders"):
            row = run(db[collection].find_one({"id": records}))
            assert row["status"] == "draft" and row["items"] == []
    finally:
        for collection in ("purchase_orders", "kitchen_orders"):
            run(db[collection].delete_many({"id": records}))


def test_passport_excludes_unowned_and_quarantined_records(records):
    from services.loyalty_group import passport_view
    run(db.businesses.insert_one({"id": records, "name": "Our venue", "ownerId": records}))
    run(db.customers.insert_many([
        customer(records + "-own", records, points=10),
        customer(records + "-unknown", None, points=1000),
        customer(records + "-quarantine", records, points=2000, _ownershipQuarantined=True),
    ]))
    assert run(passport_view("0400000000", records))["groupPoints"] == 10
    assert run(passport_view("0400000000", None)) == {"found": False}


def test_public_rules_require_a_venue_and_use_its_own_settings(client, owner_headers, records):
    run(db.businesses.insert_one({"id": records, "name": "Other venue"}))
    run(db.settings.insert_one({"key": records, "businessId": records, "value": {}}))
    from services.tenant_settings import get_setting, set_setting
    before = run(get_setting("booking_rules", "default"))
    try:
        response = req(client, "POST", "/api/booking/rules", headers=owner_headers, json={"maxOnlinePartySize": 3})
        assert response.status_code == 200
        assert req(client, "GET", "/api/booking/rules?business=default").json()["maxOnlinePartySize"] == 3
        assert req(client, "GET", "/api/booking/rules").status_code == 400
        assert req(client, "GET", "/api/booking/rules?business=invalid-takeover-venue").status_code == 404
    finally:
        run(set_setting("booking_rules", before, "default"))
        run(db.settings.delete_many({"key": records}))


def test_guest_profile_is_bound_to_the_verified_venue(client, records):
    from services.guest_session import issue_guest_token
    phone = "04" + str(uuid.uuid4().int)[:8]
    run(db.customers.insert_many([
        customer(records + "-foreign", "other-business", name="Private foreign name", phone=phone),
        customer(records + "-own", "default", name="Own profile", phone=phone),
    ]))
    token = issue_guest_token(phone, "default")
    response = req(client, "GET", "/api/guest/session/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200 and response.json()["name"] == "Own profile"


def test_manual_resolution_uses_immutable_key_and_keeps_evidence_on_audit_failure(monkeypatch, records):
    from services import audit_service
    run(db.appointments.insert_one({"id": records, "_ownershipQuarantined": True}))
    row = run(db.appointments.find_one({"id": records}))

    async def unavailable(**kwargs):
        raise RuntimeError("audit store unavailable")

    monkeypatch.setattr(audit_service, "log_event", unavailable)
    result = run(migration.resolve_quarantined("appointments", str(row["_id"]), "default",
                 actor="support-review", evidence="Reviewed signed original venue import"))
    assert result["businessId"] == "default" and result["auditLogged"] is False
    saved = run(db.appointments.find_one({"_id": row["_id"]}))
    assert "signed original" in saved[migration.MIGRATED_EVIDENCE]
    assert not saved.get(migration.QUARANTINE_FLAG)
    with pytest.raises(ValueError):
        run(migration.resolve_quarantined("appointments", str(row["_id"]), "default",
            actor="support-review", evidence="Reviewed signed original venue import"))


def test_terminal_secrets_and_foreign_configuration_are_not_exposed(client, owner_headers, records):
    run(db.eftpos_terminals.insert_one({"id": records, "businessId": "other-business", "apiSecret": "private"}))
    try:
        response = req(client, "POST", f"/api/eftpos/terminals/{records}/test", headers=owner_headers)
        assert response.status_code == 404
        response = req(client, "DELETE", f"/api/eftpos/terminals/{records}", headers=owner_headers)
        assert response.status_code == 404
        assert run(db.eftpos_terminals.find_one({"id": records}))["apiSecret"] == "private"
    finally:
        run(db.eftpos_terminals.delete_one({"id": records}))


def test_insight_generation_reads_only_the_selected_business_and_restores_context(monkeypatch, records):
    from services import nua_intelligence
    from middleware.actor_context import _actor_ctx, get_actor_context
    run(db.products.insert_many([
        {"id": records + "-own", "businessId": records, "name": "Own low margin", "cost": 9, "price": 10},
        {"id": records + "-foreign", "businessId": "foreign", "name": "Private cost", "cost": 9, "price": 10},
        {"id": records + "-unknown", "name": "Unowned cost", "cost": 9, "price": 10},
    ]))
    monkeypatch.setattr(nua_intelligence, "GENERATORS", [("pricing", nua_intelligence.recommend_pricing)])
    token = _actor_ctx.set({"businessId": "caller-before-job"})
    try:
        result = run(nua_intelligence.run_all_insights(business_id=records))
        assert result["generated"] == 1
        rows = run(db.ash_insights.find({"businessId": records}).to_list(10))
        assert rows[0]["key"] == "low_margin_" + records + "-own"
        assert get_actor_context()["businessId"] == "caller-before-job"
    finally:
        _actor_ctx.reset(token)
        run(db.products.delete_many({"id": {"$regex": "^" + records}}))
        run(db.ash_insights.delete_many({"businessId": records}))
