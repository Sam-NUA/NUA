"""services/entity_service.py's _stamp_new used doc.setdefault("businessId",
ctx.get("businessId")) — but every BaseEntity-derived model (Product
included) declares businessId as a real field defaulting to None, so a
caller that builds a full model instance and passes model.dict() into
stamped_insert already has an explicit "businessId": None key in the dict.
setdefault is a no-op against an EXISTING key, even one whose value is
None, so the actor's real businessId was never applied.

routes/products.py's create_product is the confirmed, highest-impact
victim: every product ever created via POST /api/products got
businessId=None regardless of who created it, making every business's
entire product catalogue (cost, stock, pricing) universally visible to
every other business via tenant_scope_filter's "missing/null businessId =
visible to everyone" backward-compat default. services/menu_features.py's
bulk-import and services/alcohol_seeder.py's seeding also write "products"
via the same stamped_insert path and were equally affected.
"""
import asyncio

from database import db
from tests.inprocess.conftest import req


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _login_as(client, owner_headers, *, email, business_id):
    client.post("/api/auth/register", headers=owner_headers, json={
        "name": "Entity Stamp Test Owner", "email": email, "password": "EntityStampTest2026!",
    })
    _run(db.auth_users.update_one({"email": email}, {"$set": {"role": "owner", "businessId": business_id}}))
    r = client.post("/api/auth/login", json={"email": email, "password": "EntityStampTest2026!"})
    assert r.status_code == 200, f"login failed: {r.text[:200]}"
    client.cookies.clear()
    body = r.json()
    return {"Authorization": f"Bearer {body['token']}"}


def test_creating_a_product_stamps_the_creators_real_business_id(client, owner_headers):
    r = req(client, "POST", "/api/products", headers=owner_headers, json={
        "name": "Entity Stamp Widget", "price": 9.0, "cost": 3.0, "category": "Test",
        "stock": 1, "sku": "ENTITY-STAMP-1"})
    assert r.status_code == 200, r.text[:200]
    product_id = r.json()["id"]
    try:
        doc = _run(db.products.find_one({"id": product_id}, {"_id": 0, "businessId": 1}))
        assert doc["businessId"], (
            "a newly created product must be stamped with the creator's real "
            "businessId, not left as None — a None businessId is treated as "
            "'visible to every tenant' by tenant_scope_filter"
        )
        assert doc["businessId"] == "default"  # owner_headers' businessId
    finally:
        _run(db.products.delete_one({"id": product_id}))


def test_a_product_created_by_a_different_business_is_not_visible(client, owner_headers):
    other = _login_as(client, owner_headers, email="entity.stamp.other@nua.com", business_id="entity-stamp-other-biz")

    created = req(client, "POST", "/api/products", headers=other, json={
        "name": "Other Tenant Entity Stamp Widget", "price": 11.0, "cost": 4.0, "category": "Test",
        "stock": 1, "sku": "ENTITY-STAMP-OTHER-1"})
    assert created.status_code == 200, created.text[:200]
    product_id = created.json()["id"]
    try:
        listed = req(client, "GET", "/api/products", headers=owner_headers).json()
        assert product_id not in {p["id"] for p in listed}, (
            "a product created by a different business must not leak into this business's catalogue"
        )
    finally:
        _run(db.products.delete_one({"id": product_id}))
