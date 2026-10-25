"""Print fleet: one station job fans out once per device, never per tablet.

No real network/device traffic is used. A lost ack remains uncertain.
"""
from conftest import req
import asyncio

def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)

def api(client, headers, method, route, **data):
    return req(client, method, '/api/printer-fleet' + route, headers=headers, **data)

def clear():
    from database import db
    for name in ("printer_fleet_devices", "printer_fleet_deliveries"):
        run(getattr(db, name).delete_many({"businessId": "default"}))
    run(db.print_jobs.delete_many({"orderId": "FLEET-ORDER"}))

def device(client, headers, ident, gateway):
    r = api(client, headers, "PUT", "/devices/" + ident, json={
        "gatewayId": gateway, "station": "Kitchen Printer", "name": ident,
        "transport": "wifi", "enabled": True, "width": 48,
    })
    assert r.status_code == 200, r.text
    return r.json()

def test_native_fleet_fans_out_two_targets_without_backend_duplicate(client, owner_headers, monkeypatch):
    from services import escpos, print_routing
    sent = []
    async def fake_send(*args, **kwargs):
        sent.append(args)
        return {"ok": True}
    monkeypatch.setattr(escpos, "send", fake_send)
    clear()
    try:
        device(client, owner_headers, "dev_one_0001", "gateway_one_0001")
        device(client, owner_headers, "dev_two_0002", "gateway_one_0001")
        order = run(print_routing.route_and_queue(
            [{"productName": "Pizza", "category": "Mains", "quantity": 1}],
            order_id="FLEET-ORDER", business_id="default"))
        assert len(order) == 1
        assert not sent, "backend may not also print when local fleet is registered"
        from database import db
        rows = run(db.printer_fleet_deliveries.find(
            {"businessId": "default", "jobId": order[0]["id"]}, {"_id": 0}
        ).to_list(10))
        assert len(rows) == 2
        r = api(client, owner_headers, "POST", "/claim", json={"gatewayId": "gateway_one_0001", "maxJobs": 12})
        assert r.status_code == 200, r.text
        deliveries = r.json()["deliveries"]
        assert {d["deviceId"] for d in deliveries} == {"dev_one_0001", "dev_two_0002"}
        assert all(d["payload"] for d in deliveries)
        again = api(client, owner_headers, "POST", "/claim", json={"gatewayId": "gateway_one_0001"})
        assert again.json()["deliveries"] == [], "second terminal must not claim twice"
        for d in deliveries:
            done = api(client, owner_headers, "POST", "/complete", json={
                "id": d["id"], "token": d["token"], "gatewayId": "gateway_one_0001", "status": "submitted",
            })
            assert done.status_code == 200, done.text
            assert api(client, owner_headers, "POST", "/complete", json={
                "id": d["id"], "token": d["token"], "gatewayId": "gateway_one_0001", "status": "submitted",
            }).status_code == 409
        assert api(client, owner_headers, "POST", "/claim", json={"gatewayId": "gateway_one_0001"}).json()["deliveries"] == []
    finally:
        clear()

def test_disabled_gateway_and_uncertain_reprint_require_operator(client, owner_headers):
    clear()
    try:
        device(client, owner_headers, "dev_one_0001", "gateway_one_0001")
        assert api(client, owner_headers, "POST", "/claim", json={"gatewayId": "unapproved_gateway"}).status_code == 403
        from services import print_routing
        run(print_routing.route_and_queue([{"productName": "Burger", "category": "Mains", "quantity": 1}],
                                          order_id="FLEET-ORDER", business_id="default"))
        d = api(client, owner_headers, "POST", "/claim", json={"gatewayId": "gateway_one_0001"}).json()["deliveries"][0]
        ack = api(client, owner_headers, "POST", "/complete", json={
            "id": d["id"], "token": d["token"], "gatewayId": "gateway_one_0001",
            "status": "uncertain", "error": "Bluetooth disconnected during write",
        })
        assert ack.status_code == 200
        assert api(client, owner_headers, "POST", "/claim", json={"gatewayId": "gateway_one_0001"}).json()["deliveries"] == []
        retried = api(client, owner_headers, "POST", "/retry/" + d["id"])
        assert retried.status_code == 200
        claimed = api(client, owner_headers, "POST", "/claim", json={"gatewayId": "gateway_one_0001"}).json()["deliveries"]
        assert len(claimed) == 1
        assert claimed[0]["token"] != d["token"]
        assert api(client, owner_headers, "POST", "/devices/dev_one_0001/disable").status_code == 200
        assert api(client, owner_headers, "POST", "/claim", json={"gatewayId": "gateway_one_0001"}).status_code == 403
    finally:
        clear()

def test_anonymous_fleet_endpoints_denied(anon):
    assert anon.get("/api/printer-fleet/devices").status_code in (401, 403)
    assert anon.post("/api/printer-fleet/claim", json={"gatewayId": "gateway_one_0001"}).status_code in (401, 403)
