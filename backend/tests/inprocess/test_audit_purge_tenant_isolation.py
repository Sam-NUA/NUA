"""DELETE /audit/purge/{entity_type}/{entity_id}?collection=... used to take
`collection` straight from the caller with NO validation and NO tenant
check at all — an owner of ANY business could permanently hard-delete any
document (auth_users, businesses, transactions, anything) in any OTHER
business, purely by knowing/guessing its id and naming any collection on
the deployment. Found during the Trust Release final readiness audit.
Fixed in routes/audit.py's gdpr_purge: `collection` is now restricted to
the same allowlist restore/history already use, and the document's own
businessId is checked against the caller's before anything is touched.
"""
import asyncio

from conftest import req


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_business(client, owner_headers, *, biz_id, email):
    from database import db
    _run(db.businesses.insert_one({
        "id": biz_id, "slug": biz_id, "name": f"Biz {biz_id}", "status": "active",
    }))
    client.post("/api/auth/register", headers=owner_headers, json={
        "name": "Audit Purge Test Owner", "email": email, "password": "AuditPurgeTest2026!",
    })
    _run(db.auth_users.update_one({"email": email}, {"$set": {"role": "owner", "businessId": biz_id}}))
    r = client.post("/api/auth/login", json={"email": email, "password": "AuditPurgeTest2026!"})
    assert r.status_code == 200, f"login failed: {r.text[:200]}"
    client.cookies.clear()
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _cleanup_business(biz_id):
    from database import db
    _run(db.businesses.delete_many({"id": biz_id}))
    _run(db.auth_users.delete_many({"businessId": biz_id}))


def test_purge_rejects_a_collection_outside_the_allowlist(client, owner_headers):
    tenant = dict(owner_headers, **{"X-Tenant-Id": "default"})
    r = req(client, "DELETE", "/api/audit/purge/customer/anything",
            headers=tenant, params={"collection": "auth_users"})
    assert r.status_code == 400, r.text
    assert "not supported" in r.json()["detail"].lower() or "purge isn't supported" in r.json()["detail"].lower()


def test_purge_cannot_delete_another_businesss_document(client, owner_headers):
    biz_b = "audit-purge-biz-b"
    try:
        biz_b_headers = _make_business(client, owner_headers, biz_id=biz_b, email="auditpurge-b-owner@nua.com")

        created = req(client, "POST", "/api/customers", headers=biz_b_headers, json={
            "name": "Purge Target Customer", "email": "purgetarget@nua.com", "phone": "0400111222"})
        assert created.status_code == 200, created.text[:200]
        customer_id = created.json()["id"]

        default_tenant = dict(owner_headers, **{"X-Tenant-Id": "default"})
        r = req(client, "DELETE", f"/api/audit/purge/customer/{customer_id}",
                headers=default_tenant, params={"collection": "customers"})
        assert r.status_code == 404, (
            f"an owner of a DIFFERENT business must not be able to purge this document, got {r.status_code}"
        )

        still_there = req(client, "GET", f"/api/customers/{customer_id}/profile", headers=biz_b_headers)
        assert still_there.status_code == 200, "the document must survive the rejected cross-tenant purge attempt"
    finally:
        _run(__import__("database").db.customers.delete_many({"name": "Purge Target Customer"}))
        _cleanup_business(biz_b)


def test_purge_refuses_a_document_with_no_businessId_even_for_an_owner(client, owner_headers):
    """gdpr_purge deliberately does NOT use tenant_owns()'s usual fail-open-
    to-untagged-legacy-data rule — a hard delete of a document whose real
    owner can't be confirmed is refused, not risked, even though this
    codebase's own history (the _stamp_new() bug documented in
    TENANT_ISOLATION_REMAINING_WORK.md) means an untagged businessId=None
    row is a real, plausible state on an old deployment. Found by a second
    independent readiness audit reviewing the first fix."""
    from database import db
    created = req(client, "POST", "/api/customers", headers=owner_headers, json={
        "name": "Untagged Purge Customer", "email": "untaggedpurge@nua.com", "phone": "0400555666"})
    assert created.status_code == 200, created.text[:200]
    customer_id = created.json()["id"]
    # $set to an explicit None, not $unset — the route's own existence
    # check (`if not existing or ...`) uses a {"businessId": 1} projection,
    # so a document where the field is genuinely ABSENT projects down to an
    # empty {} (falsy in Python), which would 404 on "not existing" alone
    # and never actually exercise the ownership check this test targets.
    # An explicit null survives the projection as {"businessId": None} — a
    # truthy dict — so the 404 this test asserts can only come from the
    # ownership check itself, not this unrelated projection quirk.
    _run(db.customers.update_one({"id": customer_id}, {"$set": {"businessId": None}}))

    tenant = dict(owner_headers, **{"X-Tenant-Id": "default"})
    r = req(client, "DELETE", f"/api/audit/purge/customer/{customer_id}",
            headers=tenant, params={"collection": "customers"})
    assert r.status_code == 404, (
        f"a document with no confirmable businessId must be refused for a hard delete, got {r.status_code}"
    )
    still_there = _run(db.customers.find_one({"id": customer_id}))
    assert still_there is not None


def test_purge_deletes_a_document_you_actually_own(client, owner_headers):
    tenant = dict(owner_headers, **{"X-Tenant-Id": "default"})
    created = req(client, "POST", "/api/customers", headers=tenant, json={
        "name": "Own Purge Customer", "email": "ownpurge@nua.com", "phone": "0400333444"})
    assert created.status_code == 200, created.text[:200]
    customer_id = created.json()["id"]

    r = req(client, "DELETE", f"/api/audit/purge/customer/{customer_id}",
            headers=tenant, params={"collection": "customers"})
    assert r.status_code == 200, r.text
    assert r.json()["purged"] is True

    gone = req(client, "GET", f"/api/customers/{customer_id}/profile", headers=tenant)
    assert gone.status_code == 404
