"""Hardening for POST /table/split/{split_id}/staff-process-tab — the only
path a guest's partial-checkout intent (routes/bill_split.py's
partial_checkout) becomes an actual recorded payment (see that route's own
docstring on why it can no longer mark a tab paid on the guest's unverified
say-so alone).

Two gaps closed here, both found during the Trust Release release-closure
pass:

1. Not atomic — read-then-write raced the same way commerce_v29.py's
   voucher redemption used to: two concurrent collections of the same tab
   (two terminals, or a genuine client retry racing the original) could
   both read the same stale balance and each record their own payment
   against it, overcounting what was actually collected. Fixed with the
   same bounded compare-and-swap loop already used for voucher redemption.
2. No idempotency key — a staff device retrying a timed-out request, or a
   double-tap on "confirm cash received", had no way to be recognised as a
   resubmission rather than a second real payment.

Also verifies the endpoint now writes an audit_events entry — this
mutation records real money changing hands, so it belongs in the same
audit trail as every other financial write (services/audit_service.py),
not just a websocket broadcast nobody has to look at.
"""
import time
from concurrent.futures import ThreadPoolExecutor

import asyncio

from conftest import req


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _seed_table_and_tab(client, table_number, *, total_amount=100.0, business="default"):
    """Seed a table order, fetch its split, have a guest claim + state
    partial-checkout intent for the full total, and return (split_id, tab_id)."""
    from database import db
    order_id = f"KORD-TABHARD-{table_number}"
    _run(db.kitchen_orders.insert_one({
        "id": order_id, "tableNumber": str(table_number), "businessId": business,
        "items": [{"productId": "PROD-TABHARD", "productName": "Item", "category": "Mains", "quantity": 4}],
        "status": "new",
    }))
    _run(db.products.insert_one({"id": "PROD-TABHARD", "name": "Item", "price": 25.0, "category": "Mains"}))

    split = req(client, "GET", f"/api/table/{table_number}/split?business={business}").json()
    line_id = split["lines"][0]["id"]

    from services import guest_session
    token = guest_session.issue_guest_token(f"+61412{table_number}")
    guest_headers = {"Authorization": f"Bearer {token}"}
    req(client, "POST", f"/api/table/split/{split['id']}/claim", headers=guest_headers,
        json={"lineIds": [line_id]})
    tab = req(client, "POST", f"/api/table/split/{split['id']}/partial-checkout", headers=guest_headers,
              json={"amount": total_amount, "lineIds": [line_id], "totalAmount": total_amount}).json()
    return split["id"], tab["tabId"]


def _cleanup(table_number, split_id, tab_id):
    from database import db
    _run(db.kitchen_orders.delete_many({"tableNumber": str(table_number)}))
    _run(db.bill_splits.delete_many({"tableNumber": str(table_number)}))
    _run(db.products.delete_many({"id": "PROD-TABHARD"}))
    _run(db.split_tabs.delete_many({"splitId": split_id}))
    _run(db.audit_events.delete_many({"entityId": tab_id}))


def test_two_concurrent_collections_of_the_same_tab_never_overcount(client, owner_headers):
    split_id, tab_id = _seed_table_and_tab(client, "T-TABHARD-1", total_amount=100.0)
    try:
        def _collect():
            return req(client, "POST", f"/api/table/split/{split_id}/staff-process-tab",
                       headers=owner_headers, json={"tabId": tab_id, "amount": 60})

        with ThreadPoolExecutor(max_workers=2) as pool:
            f1 = pool.submit(_collect)
            f2 = pool.submit(_collect)
            r1, r2 = f1.result(), f2.result()

        assert r1.status_code == 200 and r2.status_code == 200, (r1.text[:200], r2.text[:200])

        from database import db
        final = _run(db.split_tabs.find_one({"id": tab_id}, {"_id": 0}))
        assert final["paidAmount"] == 100.0, (
            f"two concurrent $60 collections against a $100 tab must total exactly $100 "
            f"collected (capped at the true remaining balance), not {final['paidAmount']} "
            "— a stale-read race would double count or lose track of what was really collected"
        )
        assert final["remainingBalance"] == 0.0
        assert final["status"] == "paid"
        assert len(final["payments"]) == 2
        assert sum(p["amount"] for p in final["payments"]) == 100.0
    finally:
        _cleanup("T-TABHARD-1", split_id, tab_id)


def test_staff_process_tab_is_idempotent_on_a_repeated_key(client, owner_headers):
    split_id, tab_id = _seed_table_and_tab(client, "T-TABHARD-2", total_amount=50.0)
    try:
        key = f"idem-key-{time.time_ns()}"
        first = req(client, "POST", f"/api/table/split/{split_id}/staff-process-tab",
                    headers=owner_headers, json={"tabId": tab_id, "amount": 50, "idempotencyKey": key})
        assert first.status_code == 200, first.text[:200]
        assert not first.json().get("replayed")

        second = req(client, "POST", f"/api/table/split/{split_id}/staff-process-tab",
                     headers=owner_headers, json={"tabId": tab_id, "amount": 50, "idempotencyKey": key})
        assert second.status_code == 200, second.text[:200]
        assert second.json().get("replayed") is True, (
            "resubmitting the same idempotencyKey must be recognised as a replay, "
            "not recorded as a second real payment"
        )
        assert second.json()["paidAmount"] == first.json()["paidAmount"] == 50.0

        from database import db
        final = _run(db.split_tabs.find_one({"id": tab_id}, {"_id": 0}))
        assert final["paidAmount"] == 50.0, "a duplicated idempotency key must never double-apply the payment"
        assert len(final["payments"]) == 1

        audit_count = _run(db.audit_events.count_documents(
            {"entityType": "split_tab", "entityId": tab_id}))
        assert audit_count == 1, "a replayed (non-mutating) call must not write a second audit event"
    finally:
        _cleanup("T-TABHARD-2", split_id, tab_id)


def test_staff_process_tab_writes_an_audit_event(client, owner_headers):
    split_id, tab_id = _seed_table_and_tab(client, "T-TABHARD-3", total_amount=30.0)
    try:
        r = req(client, "POST", f"/api/table/split/{split_id}/staff-process-tab",
                headers=owner_headers, json={"tabId": tab_id, "amount": 30, "method": "cash"})
        assert r.status_code == 200, r.text[:200]

        from database import db
        event = _run(db.audit_events.find_one(
            {"entityType": "split_tab", "entityId": tab_id}, {"_id": 0}))
        assert event is not None, "collecting a real tab payment must leave an audit trail"
        assert event["action"] == "updated"
        assert event["businessId"] == "default"
    finally:
        _cleanup("T-TABHARD-3", split_id, tab_id)
