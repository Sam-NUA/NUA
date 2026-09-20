"""Four routes/customers.py endpoints used Depends(get_user) with NO tenant
check of their own — any staff member of ANY business could read or
mutate any OTHER business's customer PII and store credit, purely by
guessing/enumerating a customer_id: PUT /customers/{id}, GET
/customers/{id}/profile, GET /customers/{id}/wallet, and POST
/customers/{id}/store-credit/redeem. Found during the Trust Release final
readiness audit. Fixed by checking tenant_owns(existing businessId,
caller's businessId) before touching the document in every one of them.
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
        "name": "Customers Test Owner", "email": email, "password": "CustomersTest2026!",
    })
    _run(db.auth_users.update_one({"email": email}, {"$set": {"role": "owner", "businessId": biz_id}}))
    r = client.post("/api/auth/login", json={"email": email, "password": "CustomersTest2026!"})
    assert r.status_code == 200, f"login failed: {r.text[:200]}"
    client.cookies.clear()
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _cleanup_business(biz_id):
    from database import db
    _run(db.businesses.delete_many({"id": biz_id}))
    _run(db.auth_users.delete_many({"businessId": biz_id}))


def _create_customer(client, headers, *, name, email, phone="0400000000"):
    r = req(client, "POST", "/api/customers", headers=headers, json={
        "name": name, "email": email, "phone": phone})
    assert r.status_code == 200, r.text[:200]
    return r.json()["id"]


def test_update_customer_rejects_a_document_belonging_to_another_business(client, owner_headers):
    biz_b = "cust-tenant-biz-upd"
    try:
        biz_b_headers = _make_business(client, owner_headers, biz_id=biz_b, email="custtenant-upd-b@nua.com")
        customer_id = _create_customer(client, biz_b_headers, name="Update Target", email="updtarget@nua.com")

        default_tenant = dict(owner_headers, **{"X-Tenant-Id": "default"})
        r = req(client, "PUT", f"/api/customers/{customer_id}", headers=default_tenant,
                json={"name": "Hijacked Name"})
        assert r.status_code == 404, r.text

        still_original = req(client, "GET", f"/api/customers/{customer_id}/profile", headers=biz_b_headers)
        assert still_original.status_code == 200
        assert still_original.json()["name"] == "Update Target"
    finally:
        _cleanup_business(biz_b)


def test_get_customer_profile_404s_for_another_businesss_customer(client, owner_headers):
    biz_b = "cust-tenant-biz-prof"
    try:
        biz_b_headers = _make_business(client, owner_headers, biz_id=biz_b, email="custtenant-prof-b@nua.com")
        customer_id = _create_customer(client, biz_b_headers, name="Profile Target", email="proftarget@nua.com")

        default_tenant = dict(owner_headers, **{"X-Tenant-Id": "default"})
        r = req(client, "GET", f"/api/customers/{customer_id}/profile", headers=default_tenant)
        assert r.status_code == 404, r.text
    finally:
        _cleanup_business(biz_b)


def test_get_customer_wallet_404s_for_another_businesss_customer(client, owner_headers):
    biz_b = "cust-tenant-biz-wallet"
    try:
        biz_b_headers = _make_business(client, owner_headers, biz_id=biz_b, email="custtenant-wallet-b@nua.com")
        customer_id = _create_customer(client, biz_b_headers, name="Wallet Target", email="wallettarget@nua.com")

        default_tenant = dict(owner_headers, **{"X-Tenant-Id": "default"})
        r = req(client, "GET", f"/api/customers/{customer_id}/wallet", headers=default_tenant)
        assert r.status_code == 404, r.text
    finally:
        _cleanup_business(biz_b)


def test_redeem_store_credit_cannot_drain_another_businesss_customer(client, owner_headers):
    biz_b = "cust-tenant-biz-credit"
    try:
        biz_b_headers = _make_business(client, owner_headers, biz_id=biz_b, email="custtenant-credit-b@nua.com")
        customer_id = _create_customer(client, biz_b_headers, name="Credit Target", email="credittarget@nua.com")
        from database import db
        _run(db.customers.update_one({"id": customer_id}, {"$set": {"storeCredit": 100.0}}))

        default_tenant = dict(owner_headers, **{"X-Tenant-Id": "default"})
        r = req(client, "POST", f"/api/customers/{customer_id}/store-credit/redeem",
                headers=default_tenant, json={"amount": 50})
        assert r.status_code == 404, r.text

        unchanged = _run(db.customers.find_one({"id": customer_id}, {"_id": 0, "storeCredit": 1}))
        assert unchanged["storeCredit"] == 100.0, "store credit must be untouched by the rejected cross-tenant redeem"
    finally:
        _cleanup_business(biz_b)


def test_owner_can_still_update_and_redeem_their_own_customer(client, owner_headers):
    tenant = dict(owner_headers, **{"X-Tenant-Id": "default"})
    customer_id = _create_customer(client, tenant, name="Own Customer", email="owncust@nua.com")
    from database import db
    _run(db.customers.update_one({"id": customer_id}, {"$set": {"storeCredit": 20.0}}))

    r = req(client, "PUT", f"/api/customers/{customer_id}", headers=tenant, json={"name": "Own Customer Renamed"})
    assert r.status_code == 200, r.text

    r2 = req(client, "GET", f"/api/customers/{customer_id}/wallet", headers=tenant)
    assert r2.status_code == 200, r2.text

    r3 = req(client, "POST", f"/api/customers/{customer_id}/store-credit/redeem", headers=tenant, json={"amount": 5})
    assert r3.status_code == 200, r3.text
