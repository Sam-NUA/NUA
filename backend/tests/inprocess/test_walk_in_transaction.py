"""Takeaway names must survive the real sale and its idempotent retry."""
import uuid

from tests.inprocess.conftest import req


def test_walk_in_name_survives_sale_and_retry(client, owner_headers):
    op_id = f"walkin-{uuid.uuid4()}"
    payload = {
        "items": [{"productId": "walk-in-test", "productName": "Coffee", "quantity": 1, "price": 5}],
        "paymentMethod": "Cash", "location": "Main", "cashier": "QA",
        "orderType": "takeaway", "walkInName": "Sam & Pooja", "clientOpId": op_id,
    }
    response = req(client, "POST", "/api/transactions", headers=owner_headers, json=payload)
    assert response.status_code == 200, response.text
    first = response.json()
    assert first["walkInName"] == payload["walkInName"]
    assert first["clientOpId"] == op_id
    retry = req(client, "POST", "/api/transactions", headers=owner_headers, json=payload)
    assert retry.status_code == 200, retry.text
    assert retry.json()["id"] == first["id"]
    detail = req(client, "GET", f"/api/transactions/{first['id']}", headers=owner_headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["walkInName"] == payload["walkInName"]
