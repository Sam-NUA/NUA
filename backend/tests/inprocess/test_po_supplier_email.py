"""POST /purchase-orders/{id}/send used to just flip status to "sent" —
nothing was ever actually communicated to the supplier, so a PO marked
"sent" was a false signal a human still had to remember to call or email
it in themselves. This is the actual last mile between "smart inventory"
and "inventory that restocks itself": a real email attempt on send, with
the real outcome recorded on the PO rather than implied by a status flip.

db.purchase_orders holds two different document shapes depending on which
endpoint created them — analytics.py's strict POST stamps a real
supplierId, phase_ef's own auto-generate only ever had a raw supplier NAME
string — so this covers both, plus the case where no supplier can be
resolved at all.
"""
import uuid

from conftest import req


def test_sending_a_po_with_a_real_supplier_id_attempts_a_real_email(client, owner_headers):
    supplier = req(client, "POST", "/api/suppliers", headers=owner_headers, json={
        "name": f"Test Supplier {uuid.uuid4()}", "contactPerson": "Sam", "email": "supplier@example.com",
        "phone": "0400000000", "address": "1 Test St", "paymentTerms": "Net 30"})
    assert supplier.status_code == 200, supplier.text[:200]
    supplier_id = supplier.json()["id"]

    po = req(client, "POST", "/api/purchase-orders", headers=owner_headers, json={
        "supplierId": supplier_id,
        "items": [{"productId": "p1", "productName": "Test Widget", "quantity": 10, "price": 5}],
    })
    assert po.status_code == 200, po.text[:200]
    po_id = po.json()["id"]

    sent = req(client, "POST", f"/api/purchase-orders/{po_id}/send", headers=owner_headers)
    assert sent.status_code == 200, sent.text[:200]
    body = sent.json()
    assert body["status"] == "sent"
    assert "emailResult" in body, "send must record a real outcome, not just flip status"
    assert body["emailResult"]["channel"] == "email"
    # No SendGrid configured in the test environment — the point is that a
    # real attempt happened and the real (not-configured) reason is recorded.
    assert body["emailResult"]["delivered"] is False
    assert body["emailResult"]["reason"] == "not_configured"


def test_sending_a_po_with_only_a_supplier_name_string_still_resolves(client, owner_headers):
    """phase_ef's own auto-generated POs never had a supplierId, only a raw
    name string — send must still find the real supplier by name."""
    supplier_name = f"Name Match Supplier {uuid.uuid4()}"
    req(client, "POST", "/api/suppliers", headers=owner_headers, json={
        "name": supplier_name, "contactPerson": "Alex", "email": "namematch@example.com",
        "phone": "0400000001", "address": "2 Test St", "paymentTerms": "COD"})

    from database import db
    import asyncio
    po_id = f"PO-{uuid.uuid4().hex[:8].upper()}"
    asyncio.get_event_loop().run_until_complete(db.purchase_orders.insert_one({"businessId": "default",
        "id": po_id, "supplier": supplier_name,
        "items": [{"productId": "p2", "productName": "Auto Widget", "orderQty": 20, "unitCost": 3}],
        "totalCost": 60, "status": "draft",
    }))

    sent = req(client, "POST", f"/api/purchase-orders/{po_id}/send", headers=owner_headers)
    assert sent.status_code == 200, sent.text[:200]
    body = sent.json()
    assert body["emailResult"]["reason"] == "not_configured", \
        "a name-string PO must resolve the same real supplier record, not fall through to 'no supplier on file'"


def test_sending_a_po_with_no_resolvable_supplier_is_honest_about_it(client, owner_headers):
    from database import db
    import asyncio
    po_id = f"PO-{uuid.uuid4().hex[:8].upper()}"
    asyncio.get_event_loop().run_until_complete(db.purchase_orders.insert_one({"businessId": "default",
        "id": po_id, "supplier": f"Nonexistent Supplier {uuid.uuid4()}",
        "items": [], "totalCost": 0, "status": "draft",
    }))

    sent = req(client, "POST", f"/api/purchase-orders/{po_id}/send", headers=owner_headers)
    assert sent.status_code == 200, sent.text[:200]
    body = sent.json()
    # Status still flips (existing behavior, unchanged) — but the response
    # must not claim an email went out when none could.
    assert body["status"] == "sent"
    assert body["emailResult"]["delivered"] is False
    assert body["emailResult"]["reason"] == "no_supplier_email_on_file"


def test_other_actions_do_not_carry_an_email_result(client, owner_headers):
    from database import db
    import asyncio
    po_id = f"PO-{uuid.uuid4().hex[:8].upper()}"
    asyncio.get_event_loop().run_until_complete(db.purchase_orders.insert_one({"businessId": "default",
        "id": po_id, "supplier": "Irrelevant", "items": [], "totalCost": 0, "status": "draft",
    }))

    approved = req(client, "POST", f"/api/purchase-orders/{po_id}/approve", headers=owner_headers)
    assert approved.status_code == 200, approved.text[:200]
    assert "emailResult" not in approved.json()


def test_sending_an_unknown_po_is_a_clean_404(client, owner_headers):
    r = req(client, "POST", f"/api/purchase-orders/PO-{uuid.uuid4()}/send", headers=owner_headers)
    assert r.status_code == 404
