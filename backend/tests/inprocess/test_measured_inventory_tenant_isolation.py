"""routes/measured_inventory.py had zero tests before this file, and zero
tenant scoping: stock_units/sell_variants/open_containers/wastage_events
carry no direct filtering, keyed only by productId (or transitively by
stockUnitId). Any authenticated staff member of any business could read
and write any other business's pour costs, margins, and stock-unit
definitions. This covers the basic write/read flow still works, plus the
cross-tenant leak is closed.
"""
import asyncio

from database import db
from tests.inprocess.conftest import req


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _login_as(client, owner_headers, *, email, business_id):
    """A second business's owner — same pattern used elsewhere in this
    suite for cross-tenant tests, except this also has to create the
    second business itself since register() defaults new accounts to the
    caller's own businessId."""
    client.post("/api/auth/register", headers=owner_headers, json={
        "name": "Measured Inventory Other Tenant Owner", "email": email, "password": "MITenantTest2026!",
    })
    _run(db.auth_users.update_one({"email": email}, {"$set": {"role": "owner", "businessId": business_id}}))
    r = client.post("/api/auth/login", json={"email": email, "password": "MITenantTest2026!"})
    assert r.status_code == 200, f"login failed: {r.text[:200]}"
    client.cookies.clear()
    body = r.json()
    return {"Authorization": f"Bearer {body['token']}"}


def test_full_measured_stock_flow_still_works(client, owner_headers):
    product = req(client, "POST", "/api/products", headers=owner_headers, json={
        "name": "MI Flow Wine", "price": 12.0, "cost": 4.0, "category": "Beverage",
        "stock": 0, "sku": "MI-FLOW-1"})
    assert product.status_code == 200, product.text[:200]
    product_id = product.json()["id"]
    try:
        su = req(client, "POST", "/api/measured-inventory/stock-units", headers=owner_headers, json={
            "productId": product_id, "uom": "ml", "totalMeasure": 750, "costPerUnit": 15.0,
            "label": "750ml bottle"})
        assert su.status_code == 200, su.text[:200]
        su_id = su.json()["id"]

        sv = req(client, "POST", "/api/measured-inventory/sell-variants", headers=owner_headers, json={
            "productId": product_id, "stockUnitId": su_id, "deductAmount": 150, "uom": "ml", "label": "Glass"})
        assert sv.status_code == 200, sv.text[:200]

        opened = req(client, "POST", f"/api/measured-inventory/stock-units/{su_id}/open", headers=owner_headers)
        assert opened.status_code == 200, opened.text[:200]

        summary = req(client, "GET", f"/api/measured-inventory/product/{product_id}/summary", headers=owner_headers)
        assert summary.status_code == 200, summary.text[:200]
        assert len(summary.json()["stockUnits"]) == 1
        assert len(summary.json()["sellVariants"]) == 1
        assert len(summary.json()["openContainers"]) == 1

        margin = req(client, "GET", f"/api/measured-inventory/beverage-margin/{product_id}", headers=owner_headers)
        assert margin.status_code == 200, margin.text[:200]
        assert margin.json()["measured"] is True

        wastage = req(client, "POST", "/api/measured-inventory/wastage", headers=owner_headers, json={
            "stockUnitId": su_id, "amount": 50, "uom": "ml", "reason": "spillage"})
        assert wastage.status_code == 200, wastage.text[:200]

        listed = req(client, "GET", "/api/measured-inventory/wastage", headers=owner_headers,
                     params={"stockUnitId": su_id})
        assert listed.status_code == 200
        assert len(listed.json()) == 1
    finally:
        _run(db.products.delete_one({"id": product_id}))
        _run(db.stock_units.delete_many({"productId": product_id}))
        _run(db.sell_variants.delete_many({"productId": product_id}))


def test_a_different_businesss_measured_stock_data_is_not_visible(client, owner_headers):
    other = _login_as(client, owner_headers, email="mi.other.tenant@nua.com", business_id="mi-other-tenant-biz")

    # The other business creates its own product + stock unit.
    other_product = req(client, "POST", "/api/products", headers=other, json={
        "name": "Other Tenant Whisky", "price": 20.0, "cost": 8.0, "category": "Beverage",
        "stock": 0, "sku": "MI-OTHER-1"})
    assert other_product.status_code == 200, other_product.text[:200]
    other_product_id = other_product.json()["id"]
    try:
        other_su = req(client, "POST", "/api/measured-inventory/stock-units", headers=other, json={
            "productId": other_product_id, "uom": "ml", "totalMeasure": 700, "costPerUnit": 30.0})
        assert other_su.status_code == 200, other_su.text[:200]
        other_su_id = other_su.json()["id"]

        req(client, "POST", "/api/measured-inventory/sell-variants", headers=other, json={
            "productId": other_product_id, "stockUnitId": other_su_id, "deductAmount": 30, "uom": "ml"})
        req(client, "POST", f"/api/measured-inventory/stock-units/{other_su_id}/open", headers=other)
        req(client, "POST", "/api/measured-inventory/wastage", headers=other, json={
            "stockUnitId": other_su_id, "amount": 10, "uom": "ml", "reason": "spillage"})

        # Business A (owner_headers) must not see any of it, anywhere.
        stock_units = req(client, "GET", "/api/measured-inventory/stock-units", headers=owner_headers).json()
        assert other_su_id not in {s["id"] for s in stock_units}

        sell_variants = req(client, "GET", "/api/measured-inventory/sell-variants", headers=owner_headers).json()
        assert other_product_id not in {s["productId"] for s in sell_variants}

        open_containers = req(client, "GET", "/api/measured-inventory/open-containers/all", headers=owner_headers).json()
        assert other_su_id not in {c["stockUnitId"] for c in open_containers}

        wastage = req(client, "GET", "/api/measured-inventory/wastage", headers=owner_headers).json()
        assert other_su_id not in {w.get("stockUnitId") for w in wastage}

        margin_all = req(client, "GET", "/api/measured-inventory/beverage-margin", headers=owner_headers).json()
        assert other_product_id not in {m["productId"] for m in margin_all}

        # Direct-by-id lookups must 404, not leak.
        summary = req(client, "GET", f"/api/measured-inventory/product/{other_product_id}/summary", headers=owner_headers)
        assert summary.status_code == 404, summary.text[:200]

        margin = req(client, "GET", f"/api/measured-inventory/beverage-margin/{other_product_id}", headers=owner_headers)
        assert margin.status_code == 404, margin.text[:200]

        # And a cross-tenant write attempt (e.g. attaching a stock unit to
        # someone else's product id) must be refused, not silently allowed.
        cross_write = req(client, "POST", "/api/measured-inventory/stock-units", headers=owner_headers, json={
            "productId": other_product_id, "uom": "ml", "totalMeasure": 100, "costPerUnit": 5.0})
        assert cross_write.status_code == 404, cross_write.text[:200]
    finally:
        _run(db.products.delete_one({"id": other_product_id}))
        _run(db.stock_units.delete_many({"productId": other_product_id}))
        _run(db.sell_variants.delete_many({"productId": other_product_id}))
