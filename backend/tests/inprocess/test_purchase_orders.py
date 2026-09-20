"""Purchase orders: category snapshot on generation, owner-only editing
before a PO goes out, and the category-grouped PDF export. Also covers the
`_pdf_from_lines` pagination fix in routes/finalize.py (it used to
silently truncate anything past the first page).
"""
import asyncio

from conftest import req


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _seed_low_stock_product(product_id, name, category, supplier="Test Supplier", stock=1, reorder_level=10, cost=5.0):
    from database import db
    return _run(db.products.insert_one({"businessId": "default",
        "id": product_id, "name": name, "category": category, "supplier": supplier,
        "stock": stock, "reorderLevel": reorder_level, "cost": cost, "price": cost * 2,
        "active": True, "sku": product_id,
    }))


def _cleanup_product(product_id):
    from database import db
    _run(db.products.delete_one({"id": product_id}))


def _cleanup_po(po_id):
    from database import db
    _run(db.purchase_orders.delete_one({"id": po_id}))


def _manager_headers(client, owner_headers, email="po.mgr@nua.com"):
    req(client, "POST", "/api/auth/staff/add", headers=owner_headers,
        json={"name": "PO Manager", "email": email, "password": "MgrPass123!", "role": "manager"})
    tok = req(client, "POST", "/api/auth/login", json={"email": email, "password": "MgrPass123!"}).json()
    client.cookies.clear()
    return {"Authorization": f"Bearer {tok['token']}"}


# ------------------------------------------------------------------ generate

def test_generate_po_snapshots_category_per_item(client, owner_headers):
    _seed_low_stock_product("PROD-PO-CAT-1", "Test Widget", "Hardware", supplier="Acme Supplies")
    try:
        r = req(client, "POST", "/api/purchase-orders/generate", headers=owner_headers)
        assert r.status_code == 200, r.text
        pos = [po for po in r.json()["purchaseOrders"] if po["supplier"] == "Acme Supplies"]
        assert pos, "expected a PO for Acme Supplies"
        item = next(i for i in pos[0]["items"] if i["productId"] == "PROD-PO-CAT-1")
        assert item["category"] == "Hardware"
    finally:
        _cleanup_product("PROD-PO-CAT-1")
        from database import db
        _run(db.purchase_orders.delete_many({"supplier": "Acme Supplies"}))


# ---------------------------------------------------------------------- edit

def test_edit_po_recomputes_total_server_side(client, owner_headers):
    from database import db
    po = {"businessId": "default",
        "id": "PO-EDIT-TEST-1", "supplier": "Acme Supplies", "status": "draft",
        "items": [{"productId": "P1", "productName": "Widget", "category": "Hardware",
                    "currentStock": 1, "orderQty": 5, "unitCost": 2.0}],
        "totalCost": 10.0, "createdAt": "2026-01-01T00:00:00Z", "createdBy": "u1",
    }
    _run(db.purchase_orders.insert_one(dict(po)))
    try:
        r = req(client, "PATCH", "/api/purchase-orders/PO-EDIT-TEST-1", headers=owner_headers, json={
            "items": [{"productId": "P1", "productName": "Widget", "category": "Hardware",
                        "currentStock": 1, "orderQty": 10, "unitCost": 3.0}],
            # A client-supplied total should be ignored — server recomputes.
            "totalCost": 1.0,
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["totalCost"] == 30.0
        assert body["items"][0]["orderQty"] == 10
        assert "editedAt" in body and "editedBy" in body
    finally:
        _cleanup_po("PO-EDIT-TEST-1")


def test_edit_po_rejects_non_positive_quantity(client, owner_headers):
    from database import db
    _run(db.purchase_orders.insert_one({"businessId": "default",
        "id": "PO-EDIT-TEST-2", "supplier": "Acme", "status": "draft",
        "items": [{"productId": "P1", "productName": "Widget", "category": "Hardware",
                    "currentStock": 1, "orderQty": 5, "unitCost": 2.0}],
        "totalCost": 10.0, "createdAt": "2026-01-01T00:00:00Z", "createdBy": "u1",
    }))
    try:
        r = req(client, "PATCH", "/api/purchase-orders/PO-EDIT-TEST-2", headers=owner_headers, json={
            "items": [{"productId": "P1", "productName": "Widget", "category": "Hardware",
                        "currentStock": 1, "orderQty": 0, "unitCost": 2.0}],
        })
        assert r.status_code == 400
    finally:
        _cleanup_po("PO-EDIT-TEST-2")


def test_edit_po_rejected_for_a_manager(client, owner_headers):
    from database import db
    _run(db.purchase_orders.insert_one({"businessId": "default",
        "id": "PO-EDIT-TEST-3", "supplier": "Acme", "status": "draft",
        "items": [{"productId": "P1", "productName": "Widget", "category": "Hardware",
                    "currentStock": 1, "orderQty": 5, "unitCost": 2.0}],
        "totalCost": 10.0, "createdAt": "2026-01-01T00:00:00Z", "createdBy": "u1",
    }))
    try:
        mh = _manager_headers(client, owner_headers)
        r = req(client, "PATCH", "/api/purchase-orders/PO-EDIT-TEST-3", headers=mh, json={
            "items": [{"productId": "P1", "productName": "Widget", "category": "Hardware",
                        "currentStock": 1, "orderQty": 9, "unitCost": 2.0}],
        })
        assert r.status_code == 403
    finally:
        _cleanup_po("PO-EDIT-TEST-3")


def test_edit_po_locked_once_sent(client, owner_headers):
    from database import db
    _run(db.purchase_orders.insert_one({"businessId": "default",
        "id": "PO-EDIT-TEST-4", "supplier": "Acme", "status": "sent",
        "items": [{"productId": "P1", "productName": "Widget", "category": "Hardware",
                    "currentStock": 1, "orderQty": 5, "unitCost": 2.0}],
        "totalCost": 10.0, "createdAt": "2026-01-01T00:00:00Z", "createdBy": "u1",
    }))
    try:
        r = req(client, "PATCH", "/api/purchase-orders/PO-EDIT-TEST-4", headers=owner_headers, json={
            "items": [{"productId": "P1", "productName": "Widget", "category": "Hardware",
                        "currentStock": 1, "orderQty": 9, "unitCost": 2.0}],
        })
        assert r.status_code == 409
    finally:
        _cleanup_po("PO-EDIT-TEST-4")


def test_edit_po_requires_auth(anon):
    r = req(anon, "PATCH", "/api/purchase-orders/PO-NOPE", json={"items": []})
    assert r.status_code == 401


# ----------------------------------------------------------------------- pdf

def test_po_pdf_is_grouped_by_category_and_totalled(client, owner_headers):
    from database import db
    _run(db.purchase_orders.insert_one({"businessId": "default",
        "id": "PO-PDF-TEST-1", "supplier": "Acme Supplies", "status": "draft",
        "items": [
            {"productId": "P1", "productName": "Steel Bolt", "category": "Hardware",
             "currentStock": 1, "orderQty": 10, "unitCost": 0.50},
            {"productId": "P2", "productName": "Orange Juice", "category": "Beverages",
             "currentStock": 2, "orderQty": 4, "unitCost": 3.00},
        ],
        "totalCost": 17.0, "createdAt": "2026-01-01T00:00:00Z", "createdBy": "u1",
    }))
    try:
        r = req(client, "GET", "/api/purchase-orders/PO-PDF-TEST-1/pdf", headers=owner_headers)
        assert r.status_code == 200, r.text
        assert r.headers["content-type"] == "application/pdf"
        text = r.content.decode("latin-1", errors="ignore")
        assert text.startswith("%PDF")
        assert "Hardware" in text
        assert "Beverages" in text
        assert "Steel Bolt" in text
        assert "Orange Juice" in text
    finally:
        _cleanup_po("PO-PDF-TEST-1")


def test_po_pdf_requires_auth(anon):
    r = req(anon, "GET", "/api/purchase-orders/PO-NOPE/pdf")
    assert r.status_code == 401


def test_po_pdf_404s_for_an_unknown_po(client, owner_headers):
    r = req(client, "GET", "/api/purchase-orders/PO-DOES-NOT-EXIST/pdf", headers=owner_headers)
    assert r.status_code == 404


# --------------------------------------------------------- pagination (unit)

def test_pdf_from_lines_paginates_instead_of_truncating():
    from routes.finalize import _pdf_from_lines
    many_lines = [f"Item number {i} — a fairly ordinary looking inventory line" for i in range(120)]
    pdf = _pdf_from_lines("Big report", many_lines)
    text = pdf.decode("latin-1", errors="ignore")
    assert "truncated" not in text
    assert "Item number 0 " in text
    assert "Item number 119 " in text
    # More than one page was actually emitted.
    assert "/Count 1" not in text
    import re
    m = re.search(r"/Count (\d+)", text)
    assert m and int(m.group(1)) > 1


def test_pdf_from_lines_still_works_for_a_short_single_page_report():
    from routes.finalize import _pdf_from_lines
    pdf = _pdf_from_lines("Short report", ["one line", "another line"])
    text = pdf.decode("latin-1", errors="ignore")
    assert text.startswith("%PDF")
    assert "/Count 1" in text
    assert "one line" in text


def test_low_stock_pdf_endpoint_still_works_after_the_pagination_change(client, owner_headers):
    r = req(client, "GET", "/api/inventory/low-stock/pdf", headers=owner_headers)
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")
