"""Retail Phase 3: moving stock between locations without disturbing the
flat `stock` field the rest of the app (checkout, purchase orders,
stockout prediction) already reads.
"""
from conftest import req


def _create_product(client, headers, **overrides):
    payload = {
        "name": "Transferable Widget", "category": "Retail", "categoryId": None,
        "price": 15.0, "cost": 5.0, "stock": 0, "sku": "XFER-WIDGET",
        "image": "", "gstRate": 10.0, "stockByLocation": {"Main": 20, "Warehouse": 0},
    }
    payload.update(overrides)
    r = req(client, "POST", "/api/products", json=payload, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def test_creating_a_transfer_moves_stock_out_of_the_source_immediately(client, owner_headers):
    p = _create_product(client, owner_headers)
    r = req(client, "POST", "/api/stock-transfers", json={
        "productId": p["id"], "fromLocation": "Main", "toLocation": "Warehouse", "quantity": 5,
    }, headers=owner_headers)
    assert r.status_code == 200, r.text
    transfer = r.json()
    assert transfer["status"] == "in_transit"

    updated = req(client, "GET", "/api/products", params={"search": "XFER-WIDGET"}, headers=owner_headers).json()[0]
    assert updated["stockByLocation"]["Main"] == 15  # 20 - 5
    assert updated["stockByLocation"].get("Warehouse", 0) == 0  # not landed yet


def test_receiving_a_transfer_credits_the_destination(client, owner_headers):
    p = _create_product(client, owner_headers, sku="XFER-WIDGET-2")
    transfer = req(client, "POST", "/api/stock-transfers", json={
        "productId": p["id"], "fromLocation": "Main", "toLocation": "Warehouse", "quantity": 8,
    }, headers=owner_headers).json()

    r = req(client, "POST", f"/api/stock-transfers/{transfer['id']}/receive", headers=owner_headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "received"

    updated = req(client, "GET", "/api/products", params={"search": "XFER-WIDGET-2"}, headers=owner_headers).json()[0]
    assert updated["stockByLocation"]["Main"] == 12  # 20 - 8
    assert updated["stockByLocation"]["Warehouse"] == 8

    # Can't receive the same transfer twice.
    r2 = req(client, "POST", f"/api/stock-transfers/{transfer['id']}/receive", headers=owner_headers)
    assert r2.status_code == 400


def test_cannot_transfer_more_than_is_available_at_the_source(client, owner_headers):
    p = _create_product(client, owner_headers, sku="XFER-WIDGET-3", stockByLocation={"Main": 3, "Warehouse": 0})
    r = req(client, "POST", "/api/stock-transfers", json={
        "productId": p["id"], "fromLocation": "Main", "toLocation": "Warehouse", "quantity": 10,
    }, headers=owner_headers)
    assert r.status_code == 400


def test_cancelling_an_in_transit_transfer_returns_stock_to_the_source(client, owner_headers):
    p = _create_product(client, owner_headers, sku="XFER-WIDGET-4")
    transfer = req(client, "POST", "/api/stock-transfers", json={
        "productId": p["id"], "fromLocation": "Main", "toLocation": "Warehouse", "quantity": 6,
    }, headers=owner_headers).json()

    r = req(client, "POST", f"/api/stock-transfers/{transfer['id']}/cancel", headers=owner_headers)
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"

    updated = req(client, "GET", "/api/products", params={"search": "XFER-WIDGET-4"}, headers=owner_headers).json()[0]
    assert updated["stockByLocation"]["Main"] == 20  # restored


def test_listing_transfers_can_filter_by_status(client, owner_headers):
    p = _create_product(client, owner_headers, sku="XFER-WIDGET-5")
    t1 = req(client, "POST", "/api/stock-transfers", json={
        "productId": p["id"], "fromLocation": "Main", "toLocation": "Warehouse", "quantity": 2,
    }, headers=owner_headers).json()
    req(client, "POST", f"/api/stock-transfers/{t1['id']}/receive", headers=owner_headers)

    t2 = req(client, "POST", "/api/stock-transfers", json={
        "productId": p["id"], "fromLocation": "Main", "toLocation": "Warehouse", "quantity": 1,
    }, headers=owner_headers).json()

    in_transit = req(client, "GET", "/api/stock-transfers", params={"status": "in_transit"}, headers=owner_headers).json()
    ids = [t["id"] for t in in_transit]
    assert t2["id"] in ids
    assert t1["id"] not in ids



def test_dangling_transfer_never_credits_foreign_product(client, owner_headers):
    import uuid
    from database import db

    for action in ("receive", "cancel"):
        product = _create_product(client, owner_headers, sku=f"TENANT-XFER-{uuid.uuid4()}")
        transfer = req(client, "POST", "/api/stock-transfers", headers=owner_headers, json={
            "productId": product["id"], "fromLocation": "Main", "toLocation": "Warehouse", "quantity": 5,
        })
        assert transfer.status_code == 200, transfer.text
        own = client.portal.call(db.products.find_one, {"id": product["id"]})
        # Keep the unique id index intact. A deleted source followed by a
        # restored foreign product is enough to expose the id-only write.
        client.portal.call(db.products.delete_one, {"_id": own["_id"]})
        foreign = {**own, "businessId": f"foreign-{uuid.uuid4()}", "stockByLocation": {"Main": 100, "Warehouse": 100}}
        foreign.pop("_id")
        client.portal.call(db.products.insert_one, foreign)
        try:
            result = req(client, "POST", f"/api/stock-transfers/{transfer.json()['id']}/{action}", headers=owner_headers)
            assert result.status_code == 404, result.text
            after = client.portal.call(db.products.find_one, {"id": product["id"], "businessId": foreign["businessId"]})
            assert after["stockByLocation"] == {"Main": 100, "Warehouse": 100}
            untouched = client.portal.call(db.stock_transfers.find_one, {"id": transfer.json()["id"]})
            assert untouched["status"] == "in_transit"
        finally:
            client.portal.call(db.products.delete_many, {"id": product["id"]})
