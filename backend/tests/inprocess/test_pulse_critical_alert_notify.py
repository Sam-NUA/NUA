"""Critical Pulse alerts (stockouts) fan out through the in-app notification
bell, deduped per day so a dashboard polled every ~60s doesn't spam it."""
from conftest import req


def test_critical_alert_notifies_owner_once_per_day(client, owner_headers):
    # Force a stockout: an active product with stock <= 0.
    prod = req(client, "POST", "/api/products", headers=owner_headers, json={
        "name": "ZZZ Stockout Test Item", "category": "Test", "price": 5.0,
        "cost": 2.0, "stock": 0, "sku": "ZZZ-STOCKOUT",
    }).json()
    assert prod["stock"] <= 0

    r1 = req(client, "GET", "/api/analytics/today-pulse", headers=owner_headers)
    assert r1.status_code == 200
    assert any(a["kind"] == "stockout" for a in r1.json()["alerts"])

    notifs = req(client, "GET", "/api/notifications", headers=owner_headers).json()
    stockout_notifs = [n for n in notifs if "out of stock" in n.get("body", "")]
    assert len(stockout_notifs) >= 1

    # Poll again — must not double-notify for the same day.
    req(client, "GET", "/api/analytics/today-pulse", headers=owner_headers)
    notifs2 = req(client, "GET", "/api/notifications", headers=owner_headers).json()
    stockout_notifs2 = [n for n in notifs2 if "out of stock" in n.get("body", "")]
    assert len(stockout_notifs2) == len(stockout_notifs)


def test_stockout_alert_counts_beyond_preview_limit(client, owner_headers):
    from database import db
    import uuid
    marker = str(uuid.uuid4())
    owner = client.portal.call(db.auth_users.find_one, {"email": "owner@nua.com"})
    rows = [{"id": f"{marker}-{i}", "name": f"Layout count {i}", "stock": 0,
             "active": True, "businessId": owner["businessId"], "layoutCountTest": marker} for i in range(55)]
    client.portal.call(db.products.insert_many, rows)
    try:
        result = req(client, "GET", "/api/analytics/today-pulse", headers=owner_headers)
        assert result.status_code == 200
        alert = next(a for a in result.json()["alerts"] if a["kind"] == "stockout")
        assert int(alert["message"].split()[0]) >= 55
        assert len(result.json()["exceptions"]["stockouts"]) <= 10
    finally:
        client.portal.call(db.products.delete_many, {"layoutCountTest": marker})
