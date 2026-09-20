"""routes/coursing.py is the real POS-to-kitchen path (send-to-kitchen
turns a POS cart into a kitchen order), but the KitchenOrder it built
never had businessId stamped despite the model carrying the field and
routes/kitchen.py's own creation path stamping it — so every order
created through the actual production flow was tenant-unscoped from the
moment it was created. On top of that, the open-orders list, add-round,
end-of-service/close-service, auto-fire, and the SSE ticket stream all
read/wrote db.kitchen_orders with no tenant filter at all — two
businesses both seating "Table 5" could pay off, close, or move each
other's tickets, and one business's "close out the night" action would
cancel every other business's open tickets on the deployment too.
"""
import asyncio

from database import db
from tests.inprocess.conftest import req


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _login_as(client, owner_headers, *, email, business_id):
    client.post("/api/auth/register", headers=owner_headers, json={
        "name": "Coursing Test Owner", "email": email, "password": "CoursingTenantTest2026!",
    })
    _run(db.auth_users.update_one({"email": email}, {"$set": {"role": "owner", "businessId": business_id}}))
    r = client.post("/api/auth/login", json={"email": email, "password": "CoursingTenantTest2026!"})
    assert r.status_code == 200, f"login failed: {r.text[:200]}"
    client.cookies.clear()
    body = r.json()
    return {"Authorization": f"Bearer {body['token']}"}


def _send_to_kitchen(client, headers, *, table_number, notes="test"):
    r = req(client, "POST", "/api/coursing/send-to-kitchen", headers=headers, json={
        "items": [{"productId": "no-such-product", "productName": "Test Dish", "quantity": 1,
                   "price": 10, "course": 1}],
        "orderType": "dine_in", "tableNumber": table_number, "notes": notes,
    })
    assert r.status_code == 200, r.text[:300]
    return r.json()


def test_send_to_kitchen_stamps_business_id_and_does_not_collide_across_tenants(client, owner_headers):
    other = _login_as(client, owner_headers, email="coursing.collide.other@nua.com", business_id="coursing-collide-other-biz")
    shared_table = "COURSING-COLLIDE-TABLE-99"

    mine = _send_to_kitchen(client, owner_headers, table_number=shared_table, notes="mine")
    theirs = _send_to_kitchen(client, other, table_number=shared_table, notes="theirs")
    try:
        assert mine["id"] != theirs["id"], "two businesses seating the same table number must get separate tickets"
        assert mine.get("businessId") == "default"
        assert theirs.get("businessId") == "coursing-collide-other-biz"

        my_open = req(client, "GET", f"/api/coursing/orders/open?tableNumber={shared_table}", headers=owner_headers).json()
        assert [o["id"] for o in my_open] == [mine["id"]]

        their_open = req(client, "GET", f"/api/coursing/orders/open?tableNumber={shared_table}", headers=other).json()
        assert [o["id"] for o in their_open] == [theirs["id"]]

        # A second round on "the same table" from my business must attach to
        # MY ticket, not silently merge into the other business's one.
        again = _send_to_kitchen(client, owner_headers, table_number=shared_table, notes="round 2")
        assert again["id"] == mine["id"], "a repeat order at the same table number must reuse this business's own ticket"
    finally:
        _run(db.kitchen_orders.delete_many({"tableNumber": shared_table}))


def test_add_round_is_not_reachable_across_tenants(client, owner_headers):
    other = _login_as(client, owner_headers, email="coursing.addround.other@nua.com", business_id="coursing-addround-other-biz")
    ticket = _send_to_kitchen(client, other, table_number="COURSING-ADDROUND-TABLE")
    try:
        blocked = req(client, "POST", f"/api/coursing/orders/{ticket['id']}/add-round", headers=owner_headers,
                       json={"items": [{"productId": "x", "productName": "Sneaky Item", "quantity": 1, "price": 5}]})
        assert blocked.status_code == 404
    finally:
        _run(db.kitchen_orders.delete_one({"id": ticket["id"]}))


def test_settling_a_table_does_not_close_a_different_businesss_same_numbered_ticket(client, owner_headers):
    other = _login_as(client, owner_headers, email="coursing.settle.other@nua.com", business_id="coursing-settle-other-biz")
    shared_table = "COURSING-SETTLE-TABLE-42"

    mine = _send_to_kitchen(client, owner_headers, table_number=shared_table)
    theirs = _send_to_kitchen(client, other, table_number=shared_table)
    try:
        settled = req(client, "POST", "/api/coursing/settle", headers=owner_headers,
                       json={"tableNumber": shared_table, "releaseTable": False})
        assert settled.status_code == 200, settled.text[:200]
        assert mine["id"] in settled.json()["closedOrders"]
        assert theirs["id"] not in settled.json()["closedOrders"], (
            "settling this business's table must not close another business's ticket at the same table number"
        )

        their_ticket_after = _run(db.kitchen_orders.find_one({"id": theirs["id"]}, {"_id": 0}))
        assert their_ticket_after["status"] not in ("served", "cancelled")
    finally:
        _run(db.kitchen_orders.delete_many({"tableNumber": shared_table}))


def test_void_from_ticket_is_not_reachable_across_tenants(client, owner_headers):
    other = _login_as(client, owner_headers, email="coursing.void.other@nua.com", business_id="coursing-void-other-biz")
    ticket = _send_to_kitchen(client, other, table_number="COURSING-VOID-TABLE")
    try:
        blocked = req(client, "POST", f"/api/coursing/orders/{ticket['id']}/void", headers=owner_headers,
                       json={"items": [{"productName": "Test Dish", "quantity": 1}]})
        assert blocked.status_code == 404

        untouched = _run(db.kitchen_orders.find_one({"id": ticket["id"]}, {"_id": 0}))
        assert len(untouched["items"]) == 1, "a cross-tenant void attempt must not remove items from another business's ticket"
    finally:
        _run(db.kitchen_orders.delete_one({"id": ticket["id"]}))


def test_open_kitchen_orders_list_is_scoped_per_business(client, owner_headers):
    other = _login_as(client, owner_headers, email="coursing.list.other@nua.com", business_id="coursing-list-other-biz")
    theirs = _send_to_kitchen(client, other, table_number="COURSING-LIST-TABLE")
    try:
        mine = req(client, "GET", "/api/coursing/orders/open", headers=owner_headers).json()
        assert not any(o["id"] == theirs["id"] for o in mine)
    finally:
        _run(db.kitchen_orders.delete_one({"id": theirs["id"]}))
