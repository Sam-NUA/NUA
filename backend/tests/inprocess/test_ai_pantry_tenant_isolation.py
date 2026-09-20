"""routes/ai_pantry.py had zero businessId scoping across pantry-list
history, uploaded-invoice OCR results, and the product-insights dashboard
tile — plus a more severe finding: parse-invoice matched a supplier
invoice's line items against *every* business's product catalogue, and
apply-invoice then wrote the resulting price/cost update straight to
`db.products` with no ownership check at all, so a business could reprice
another business's products via the invoice-OCR flow.
"""
import asyncio

from database import db
from tests.inprocess.conftest import req


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _login_as(client, owner_headers, *, email, business_id):
    client.post("/api/auth/register", headers=owner_headers, json={
        "name": "AI Pantry Test Owner", "email": email, "password": "AiPantryTenantTest2026!",
    })
    _run(db.auth_users.update_one({"email": email}, {"$set": {"role": "owner", "businessId": business_id}}))
    r = client.post("/api/auth/login", json={"email": email, "password": "AiPantryTenantTest2026!"})
    assert r.status_code == 200, f"login failed: {r.text[:200]}"
    client.cookies.clear()
    body = r.json()
    return {"Authorization": f"Bearer {body['token']}"}


def test_pantry_history_and_invoices_are_isolated_per_business(client, owner_headers):
    other = _login_as(client, owner_headers, email="pantry.other@nua.com", business_id="pantry-other-biz")

    _run(db.pantry_lists.insert_one({
        "id": "PANTRY-OTHERBIZ", "generatedAt": "2026-01-01T00:00:00", "generatedBy": "x",
        "data": {}, "menuItemCount": 0, "transactionCount": 0, "upcomingCovers": 0,
        "businessId": "pantry-other-biz",
    }))
    _run(db.invoices.insert_one({
        "id": "INV-OTHERBIZ", "uploadedAt": "2026-01-01T00:00:00", "uploadedBy": "x",
        "parsed": {"supplier": "Other Biz Supplier"}, "matches": [], "applied": False,
        "businessId": "pantry-other-biz",
    }))
    try:
        my_history = req(client, "GET", "/api/ai-pantry/history", headers=owner_headers).json()
        assert not any(p["id"] == "PANTRY-OTHERBIZ" for p in my_history)

        my_invoices = req(client, "GET", "/api/ai-pantry/invoices", headers=owner_headers).json()
        assert not any(i["id"] == "INV-OTHERBIZ" for i in my_invoices)

        apply_mine = req(client, "POST", "/api/ai-pantry/apply-invoice/INV-OTHERBIZ", headers=owner_headers,
                          json={"selections": []})
        assert apply_mine.status_code == 404

        their_invoices = req(client, "GET", "/api/ai-pantry/invoices", headers=other).json()
        assert any(i["id"] == "INV-OTHERBIZ" for i in their_invoices)
    finally:
        _run(db.pantry_lists.delete_one({"id": "PANTRY-OTHERBIZ"}))
        _run(db.invoices.delete_one({"id": "INV-OTHERBIZ"}))


def test_apply_invoice_cannot_reprice_a_different_businesss_product(client, owner_headers):
    """Even a legitimately-owned invoice can reference another business's
    productId (e.g. a pre-fix invoice created before parse-invoice scoped
    its product matching, or a crafted request) — apply-invoice must not
    let that update go through. The per-product ownership recheck is the
    actual backstop here, independent of whether the invoice itself is
    owned by the caller's business."""
    other = _login_as(client, owner_headers, email="pantry.reprice.other@nua.com", business_id="pantry-reprice-other-biz")

    victim_product_id = "PANTRY-VICTIM-PRODUCT"
    _run(db.products.insert_one({
        "id": victim_product_id, "name": "Victim Product", "price": 10.0, "cost": 4.0,
        "businessId": "default",
    }))
    _run(db.invoices.insert_one({
        "id": "INV-CROSSTENANT-ATTACK", "uploadedAt": "2026-01-01T00:00:00", "uploadedBy": "x",
        "parsed": {"supplier": "Attacker Supplier"},
        "matches": [{"matchedProductId": victim_product_id, "matchedProductName": "Victim Product",
                     "currentCost": 4.0, "newCost": 999.0, "currentPrice": 10.0, "suggestedPrice": 500.0}],
        "applied": False, "businessId": "pantry-reprice-other-biz",
    }))
    try:
        result = req(client, "POST", "/api/ai-pantry/apply-invoice/INV-CROSSTENANT-ATTACK", headers=other,
                      json={"selections": [{"matchedProductId": victim_product_id, "applyCost": True, "applyPrice": True}]})
        assert result.status_code == 200, result.text[:200]
        assert result.json()["updated"] == 0, "the per-product ownership recheck must skip a product this business doesn't own"

        product_after = _run(db.products.find_one({"id": victim_product_id}, {"_id": 0}))
        assert product_after["price"] == 10.0 and product_after["cost"] == 4.0, (
            "a cross-tenant invoice must never be able to change another business's product price/cost"
        )
    finally:
        _run(db.products.delete_one({"id": victim_product_id}))
        _run(db.invoices.delete_one({"id": "INV-CROSSTENANT-ATTACK"}))


def test_product_insights_only_reflects_this_businesss_own_products(client, owner_headers):
    other = _login_as(client, owner_headers, email="pantry.insights.other@nua.com", business_id="pantry-insights-other-biz")

    _run(db.products.insert_one({
        "id": "PANTRY-INSIGHTS-OTHERBIZ-PRODUCT", "name": "Other Biz Secret Product",
        "price": 999, "cost": 1, "businessId": "pantry-insights-other-biz",
    }))
    try:
        mine = req(client, "GET", "/api/products/insights", headers=owner_headers).json()
        assert not any(r["productId"] == "PANTRY-INSIGHTS-OTHERBIZ-PRODUCT" for r in mine)

        theirs = req(client, "GET", "/api/products/insights", headers=other).json()
        assert any(r["productId"] == "PANTRY-INSIGHTS-OTHERBIZ-PRODUCT" for r in theirs)
    finally:
        _run(db.products.delete_one({"id": "PANTRY-INSIGHTS-OTHERBIZ-PRODUCT"}))
