"""routes/menu_features.py's bulk price-adjust tool read/wrote db.products
with zero businessId scoping: an owner adjusting "all Wine prices +5%" (or,
worse, every product with no category filter at all) silently repriced
every OTHER business's matching products too, not just their own. The
what-if simulator had the same gap — a caller could point it at an
arbitrary productId belonging to another business and see its price/cost/
margin, and its historical-average fallback blended in every business's
transaction history.
"""
import asyncio

from database import db
from tests.inprocess.conftest import req


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _login_as(client, owner_headers, *, email, business_id):
    client.post("/api/auth/register", headers=owner_headers, json={
        "name": "Menu Features Test Owner", "email": email, "password": "MenuFeaturesTenantTest2026!",
    })
    _run(db.auth_users.update_one({"email": email}, {"$set": {"role": "owner", "businessId": business_id}}))
    r = client.post("/api/auth/login", json={"email": email, "password": "MenuFeaturesTenantTest2026!"})
    assert r.status_code == 200, f"login failed: {r.text[:200]}"
    client.cookies.clear()
    body = r.json()
    return {"Authorization": f"Bearer {body['token']}"}


def test_bulk_price_adjust_does_not_reprice_another_businesss_products(client, owner_headers):
    other = _login_as(client, owner_headers, email="menufeat.price.other@nua.com", business_id="menufeat-price-other-biz")

    victim_id = "MENUFEAT-VICTIM-PRODUCT"
    _run(db.products.insert_one({
        "id": victim_id, "name": "Victim Wine", "category": "Wine", "price": 20.0, "cost": 8.0,
        "businessId": "menufeat-price-other-biz",
    }))
    try:
        # As MY business (owner_headers/"default"), adjust "all Wine" prices —
        # must not touch the other business's Wine product.
        adjusted = req(client, "POST", "/api/menu/price-adjust", headers=owner_headers,
                        json={"category": "Wine", "type": "percentage", "amount": 50, "direction": "increase"})
        assert adjusted.status_code == 200, adjusted.text[:200]
        assert not any(u["id"] == victim_id for u in adjusted.json()["items"])

        # Also try with NO category filter at all (the broadest case).
        adjusted_all = req(client, "POST", "/api/menu/price-adjust", headers=owner_headers,
                            json={"type": "percentage", "amount": 10, "direction": "increase"})
        assert adjusted_all.status_code == 200, adjusted_all.text[:200]
        assert not any(u["id"] == victim_id for u in adjusted_all.json()["items"])

        untouched = _run(db.products.find_one({"id": victim_id}, {"_id": 0}))
        assert untouched["price"] == 20.0, "another business's product price must be untouched by a bulk adjust"
    finally:
        _run(db.products.delete_one({"id": victim_id}))


def test_what_if_advanced_cannot_read_another_businesss_product_economics(client, owner_headers):
    other = _login_as(client, owner_headers, email="menufeat.whatif.other@nua.com", business_id="menufeat-whatif-other-biz")

    victim_id = "MENUFEAT-WHATIF-VICTIM"
    _run(db.products.insert_one({
        "id": victim_id, "name": "Secret Margin Product", "category": "Food", "price": 999.0, "cost": 1.0,
        "businessId": "menufeat-whatif-other-biz",
    }))
    try:
        result = req(client, "POST", "/api/analytics/what-if-advanced", headers=owner_headers,
                      json={"changes": [{"productId": victim_id, "newPrice": 5, "projectedQty": 10}]})
        assert result.status_code == 200, result.text[:200]
        assert result.json()["items"] == [], "a productId belonging to another business must resolve to nothing"
    finally:
        _run(db.products.delete_one({"id": victim_id}))
