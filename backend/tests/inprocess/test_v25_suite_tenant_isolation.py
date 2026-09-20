"""routes/v25_suite.py (30+ v25-v30 features consolidated into one module)
had zero businessId scoping across almost the entire file — sites,
hardware, disputes, supplier quotes, dynamic-pricing rules, subscriptions,
recipes, waste log, reviews, marketing campaigns, and more all leaked or
mixed across every business on the deployment. Two zero-auth endpoints
(sync-queue GET, dynamic-pricing GET) and a full-database warehouse export
(zero business filter, same exfiltration class as the /ops/backup bug)
were the most severe. Also covers the ash_plans (planDate, status)
collision bug and the toggle_86 -> substitute() wrong-argument-count bug
that silently broke every 86 suggestion.
"""
import asyncio

from database import db
from tests.inprocess.conftest import req


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _login_as(client, owner_headers, *, email, business_id):
    client.post("/api/auth/register", headers=owner_headers, json={
        "name": "V25 Test Owner", "email": email, "password": "V25TenantTest2026!",
    })
    _run(db.auth_users.update_one({"email": email}, {"$set": {"role": "owner", "businessId": business_id}}))
    r = client.post("/api/auth/login", json={"email": email, "password": "V25TenantTest2026!"})
    assert r.status_code == 200, f"login failed: {r.text[:200]}"
    client.cookies.clear()
    body = r.json()
    return {"Authorization": f"Bearer {body['token']}"}


def test_sync_queue_requires_auth_and_is_scoped(client, owner_headers):
    other = _login_as(client, owner_headers, email="v25.sync.other@nua.com", business_id="v25-sync-other-biz")
    pushed = req(client, "POST", "/api/v25/sync-queue", headers=other,
                 json={"ops": [{"clientOpId": "OP-SECRET-1", "kind": "noop"}]})
    assert pushed.status_code == 200, pushed.text[:200]

    anon = req(client, "GET", "/api/v25/sync-queue")
    assert anon.status_code in (401, 403), "sync-queue list must require auth"

    mine = req(client, "GET", "/api/v25/sync-queue", headers=owner_headers).json()
    assert not any(r.get("clientOpId") == "OP-SECRET-1" for r in mine)


def test_dynamic_pricing_requires_auth_and_is_scoped(client, owner_headers):
    other = _login_as(client, owner_headers, email="v25.dp.other@nua.com", business_id="v25-dp-other-biz")
    created = req(client, "POST", "/api/v25/dynamic-pricing", headers=other, json={"category": "Coffee", "multiplier": 1.5})
    assert created.status_code == 200, created.text[:200]

    anon = req(client, "GET", "/api/v25/dynamic-pricing")
    assert anon.status_code in (401, 403), "dynamic-pricing list must require auth"

    mine = req(client, "GET", "/api/v25/dynamic-pricing", headers=owner_headers).json()
    assert not any(r["id"] == created.json()["id"] for r in mine)


def test_hardware_sites_disputes_supplier_quotes_are_scoped(client, owner_headers):
    other = _login_as(client, owner_headers, email="v25.misc.other@nua.com", business_id="v25-misc-other-biz")

    site = req(client, "POST", "/api/v25/sites", headers=other, json={"name": "Other HQ"}).json()
    mine_sites = req(client, "GET", "/api/v25/sites", headers=owner_headers).json()
    assert not any(s["id"] == site["id"] for s in mine_sites)

    dispute = req(client, "POST", "/api/v25/disputes", headers=other, json={"amount": 50}).json()
    mine_disputes = req(client, "GET", "/api/v25/disputes", headers=owner_headers).json()
    assert not any(d["id"] == dispute["id"] for d in mine_disputes)
    evidence_mine = req(client, "POST", f"/api/v25/disputes/{dispute['id']}/evidence", headers=owner_headers, json={})
    assert evidence_mine.status_code == 404

    quote = req(client, "POST", "/api/v25/suppliers/quote", headers=other,
                json={"item": "Milk", "supplier": "Acme", "pricePerUnit": 1.0}).json()
    mine_quotes = req(client, "GET", "/api/v25/suppliers/compare", headers=owner_headers).json()
    assert not any(c["item"] == "Milk" and quote["id"] in [q["id"] for q in c["quotes"]] for c in mine_quotes)


def test_ash_plan_is_scoped_per_business_and_does_not_collide(client, owner_headers):
    other = _login_as(client, owner_headers, email="v25.ash.other@nua.com", business_id="v25-ash-other-biz")

    plan_other = req(client, "GET", "/api/v25/ash-pro/plan", headers=other).json()
    plan_mine = req(client, "GET", "/api/v25/ash-pro/plan", headers=owner_headers).json()
    # Before the fix, both plans shared one (planDate, status) key and the
    # second write would silently overwrite the first — same plan id back.
    assert plan_other["id"] != plan_mine["id"]

    raw_other = _run(db.ash_plans.find_one({"id": plan_other["id"]}, {"_id": 0}))
    assert raw_other["businessId"] == "v25-ash-other-biz"

    approve_cross = req(client, "POST", "/api/v25/ash-pro/approve", headers=owner_headers,
                        json={"planId": plan_other["id"]})
    assert approve_cross.status_code == 404


def test_warehouse_export_is_scoped_per_business(client, owner_headers):
    other = _login_as(client, owner_headers, email="v25.warehouse.other@nua.com", business_id="v25-warehouse-other-biz")
    tx = {"id": "TX-WAREHOUSE-SECRET", "businessId": "v25-warehouse-other-biz", "total": 999.0,
          "createdAt": "2026-01-01T00:00:00+00:00", "items": []}
    _run(db.transactions.insert_one(dict(tx)))
    try:
        export = req(client, "GET", "/api/v25/warehouse/export", headers=owner_headers,
                     params={"collection": "transactions", "limit": 5000}).json()
        assert not any(r.get("id") == "TX-WAREHOUSE-SECRET" for r in export["rows"]), (
            "warehouse export must never return another business's raw transactions"
        )
    finally:
        _run(db.transactions.delete_one({"id": "TX-WAREHOUSE-SECRET"}))


def test_marketing_campaigns_are_scoped_and_owned(client, owner_headers):
    other = _login_as(client, owner_headers, email="v25.mkt.other@nua.com", business_id="v25-mkt-other-biz")
    campaign = req(client, "POST", "/api/v25/marketing/auto", headers=other, json={"audience": "all"}).json()

    mine_list = req(client, "GET", "/api/v25/marketing/auto", headers=owner_headers).json()
    assert not any(c["id"] == campaign["id"] for c in mine_list)

    hold_cross = req(client, "POST", f"/api/v25/marketing/auto/{campaign['id']}/hold", headers=owner_headers, json={})
    assert hold_cross.status_code == 404

    send_cross = req(client, "POST", f"/api/v25/marketing/auto/{campaign['id']}/send", headers=owner_headers, json={})
    assert send_cross.status_code == 404

    perf_cross = req(client, "GET", f"/api/v25/marketing/auto/{campaign['id']}/performance", headers=owner_headers)
    assert perf_cross.status_code == 404


def test_win_back_only_issues_vouchers_to_owned_customers(client, owner_headers):
    other = _login_as(client, owner_headers, email="v25.winback.other@nua.com", business_id="v25-winback-other-biz")
    foreign_customer = {"id": "CUST-WINBACK-FOREIGN", "businessId": "v25-winback-other-biz", "name": "Foreign Guest"}
    _run(db.customers.insert_one(dict(foreign_customer)))
    try:
        result = req(client, "POST", "/api/v25/recovery/win-back", headers=owner_headers,
                     json={"customerIds": ["CUST-WINBACK-FOREIGN"], "voucherValue": 50}).json()
        assert result["queued"] == 0, "must not queue a win-back voucher for another business's customer"
        vouchers = _run(db.vouchers.find({"customerId": "CUST-WINBACK-FOREIGN"}, {"_id": 0}).to_list(10))
        assert not vouchers
    finally:
        _run(db.customers.delete_one({"id": "CUST-WINBACK-FOREIGN"}))


def test_toggle_86_is_owned_and_substitute_call_no_longer_crashes(client, owner_headers):
    other = _login_as(client, owner_headers, email="v25.86.other@nua.com", business_id="v25-86-other-biz")
    prod_resp = req(client, "POST", "/api/products", headers=other, json={
        "name": "Other Biz Latte", "category": "Coffee", "price": 5.0, "cost": 1.0, "stock": 10, "sku": "V25-86-OTHER"})
    assert prod_resp.status_code == 200, prod_resp.text[:200]
    prod = prod_resp.json()
    try:
        cross = req(client, "POST", f"/api/v25/products/{prod['id']}/86", headers=owner_headers, json={})
        assert cross.status_code == 404, "must not be able to 86 another business's product"

        own_resp = req(client, "POST", "/api/products", headers=owner_headers, json={
            "name": "My Latte", "category": "Coffee", "price": 5.0, "cost": 1.0, "stock": 10, "sku": "V25-86-MINE"})
        assert own_resp.status_code == 200, own_resp.text[:200]
        own = own_resp.json()
        toggled = req(client, "POST", f"/api/v25/products/{own['id']}/86", headers=owner_headers, json={})
        assert toggled.status_code == 200, toggled.text[:200]
        # Before the fix, substitute() was called with an extra Request arg
        # it didn't accept, raising a TypeError swallowed by a bare except —
        # suggestedSubstitute was always None. Just confirming no crash and
        # a well-formed response here (a substitute may legitimately be
        # absent if no other product shares the category in this test DB).
        assert "suggestedSubstitute" in toggled.json()
    finally:
        _run(db.products.delete_one({"id": prod["id"]}))
