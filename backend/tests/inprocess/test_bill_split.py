"""Guest-facing bill splitting.

Crypto is the fully-testable payment path in this sandbox (raw httpx,
mockable) — Stripe's checkout SDK isn't installed here at all (see
test_crypto_payments.py's module docstring), so the crypto path is what
proves the checkout -> finalize -> split-marked-paid pipeline end to end;
Stripe is only smoke-tested for its "not configured" honesty.
"""
import asyncio

import httpx
import pytest

from conftest import req


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


_RealAsyncClient = httpx.AsyncClient


def _mock_client_factory(handler):
    def factory(*args, **kwargs):
        return _RealAsyncClient(transport=httpx.MockTransport(handler), timeout=kwargs.get("timeout", 10))
    return factory


def _seed_table_order(table_number, order_id="KORD-SPLIT-1", items=None, business_id="default"):
    from database import db
    items = items or [
        {"productId": "PROD-BURGER", "productName": "Burger", "category": "Mains", "quantity": 2},
        {"productId": "PROD-FRIES", "productName": "Fries", "category": "Sides", "quantity": 1},
    ]
    _run(db.kitchen_orders.insert_one({
        "id": order_id, "tableNumber": str(table_number), "businessId": business_id,
        "items": items, "status": "new",
    }))
    _run(db.products.insert_one({"id": "PROD-BURGER", "name": "Burger", "price": 15.0, "category": "Mains"}))
    _run(db.products.insert_one({"id": "PROD-FRIES", "name": "Fries", "price": 6.0, "category": "Sides"}))
    return order_id


def _cleanup_table(table_number, order_ids=None):
    from database import db
    _run(db.kitchen_orders.delete_many({"tableNumber": str(table_number)}))
    _run(db.bill_splits.delete_many({"tableNumber": str(table_number)}))
    _run(db.products.delete_many({"id": {"$in": ["PROD-BURGER", "PROD-FRIES"]}}))


def _guest_token(phone="+61412345000"):
    from services import guest_session
    return guest_session.issue_guest_token(phone)


# ----------------------------------------------------------------- creation

def test_get_split_builds_one_line_per_unit(client):
    _seed_table_order("T-901")
    try:
        r = req(client, "GET", "/api/table/T-901/split?business=default")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["tableNumber"] == "T-901"
        assert body["status"] == "open"
        # 2x Burger -> 2 lines, 1x Fries -> 1 line
        names = sorted(l["productName"] for l in body["lines"])
        assert names == ["Burger", "Burger", "Fries"]
        prices = {l["productName"]: l["unitPrice"] for l in body["lines"]}
        assert prices["Burger"] == 15.0
        assert prices["Fries"] == 6.0
        assert all(l["status"] == "open" for l in body["lines"])
    finally:
        _cleanup_table("T-901")


def test_get_split_is_idempotent(client):
    _seed_table_order("T-902")
    try:
        r1 = req(client, "GET", "/api/table/T-902/split?business=default")
        r2 = req(client, "GET", "/api/table/T-902/split?business=default")
        assert r1.json()["id"] == r2.json()["id"]
    finally:
        _cleanup_table("T-902")


def test_get_split_404s_when_no_open_order(client):
    r = req(client, "GET", "/api/table/T-NO-ORDER/split?business=default")
    assert r.status_code == 404


def test_a_new_round_firing_appends_lines_without_disturbing_claims(client):
    _seed_table_order("T-903")
    try:
        split_id = req(client, "GET", "/api/table/T-903/split?business=default").json()["id"]
        token = _guest_token("+61412345001")
        # Claim one burger before the second round fires.
        lines = req(client, "GET", "/api/table/T-903/split?business=default").json()["lines"]
        burger_line = next(l for l in lines if l["productName"] == "Burger")
        req(client, "POST", f"/api/table/split/{split_id}/claim",
            headers={"Authorization": f"Bearer {token}"}, json={"lineIds": [burger_line["id"]]})

        # Kitchen fires another round with an extra item onto the SAME order.
        from database import db
        _run(db.kitchen_orders.update_one({"id": "KORD-SPLIT-1"}, {"$set": {"items": [
            {"productId": "PROD-BURGER", "productName": "Burger", "category": "Mains", "quantity": 2},
            {"productId": "PROD-FRIES", "productName": "Fries", "category": "Sides", "quantity": 1},
            {"productId": "PROD-FRIES", "productName": "Fries", "category": "Sides", "quantity": 1},
        ]}}))

        body = req(client, "GET", "/api/table/T-903/split?business=default").json()
        assert len(body["lines"]) == 4  # 2 burger + 2 fries now
        claimed = [l for l in body["lines"] if l["status"] == "claimed"]
        assert len(claimed) == 1  # the earlier claim survived the refresh
    finally:
        _cleanup_table("T-903")


# ------------------------------------------------------------------- mode

def test_mode_sticks_after_first_choice(client):
    _seed_table_order("T-904")
    try:
        req(client, "POST", "/api/table/T-904/split/mode?business=default", json={"mode": "equal", "equalCount": 3})
        body = req(client, "POST", "/api/table/T-904/split/mode?business=default", json={"mode": "items"}).json()
        assert body["mode"] == "equal"
    finally:
        _cleanup_table("T-904")


def test_equal_split_shares_sum_back_to_the_exact_total(client):
    _seed_table_order("T-905")
    try:
        body = req(client, "POST", "/api/table/T-905/split/mode?business=default", json={"mode": "equal", "equalCount": 3}).json()
        total_of_lines = round(sum(l["unitPrice"] for l in body["lines"]), 2)
        total_of_shares = round(sum(p["amount"] for p in body["equalParts"]), 2)
        assert total_of_shares == total_of_lines
        assert len(body["equalParts"]) == 3
    finally:
        _cleanup_table("T-905")


# ------------------------------------------------------------------ claim

def test_claim_requires_a_guest_session(client):
    _seed_table_order("T-906")
    try:
        split_id = req(client, "GET", "/api/table/T-906/split?business=default").json()["id"]
        r = req(client, "POST", f"/api/table/split/{split_id}/claim", json={"lineIds": ["L1"]})
        assert r.status_code == 401
    finally:
        _cleanup_table("T-906")


def test_two_guests_cannot_claim_the_same_line(client):
    _seed_table_order("T-907")
    try:
        split_id = req(client, "GET", "/api/table/T-907/split?business=default").json()["id"]
        line_id = req(client, "GET", "/api/table/T-907/split?business=default").json()["lines"][0]["id"]
        t1, t2 = _guest_token("+61412345002"), _guest_token("+61412345003")

        r1 = req(client, "POST", f"/api/table/split/{split_id}/claim",
                 headers={"Authorization": f"Bearer {t1}"}, json={"lineIds": [line_id]})
        assert r1.json()["claimed"] == [line_id]

        r2 = req(client, "POST", f"/api/table/split/{split_id}/claim",
                 headers={"Authorization": f"Bearer {t2}"}, json={"lineIds": [line_id]})
        assert r2.json()["claimed"] == []
        assert r2.json()["failed"] == [line_id]
    finally:
        _cleanup_table("T-907")


def test_release_returns_a_line_to_open(client):
    _seed_table_order("T-908")
    try:
        split_id = req(client, "GET", "/api/table/T-908/split?business=default").json()["id"]
        line_id = req(client, "GET", "/api/table/T-908/split?business=default").json()["lines"][0]["id"]
        token = _guest_token("+61412345004")
        req(client, "POST", f"/api/table/split/{split_id}/claim",
            headers={"Authorization": f"Bearer {token}"}, json={"lineIds": [line_id]})
        body = req(client, "POST", f"/api/table/split/{split_id}/release",
                   headers={"Authorization": f"Bearer {token}"}, json={"lineIds": [line_id]}).json()
        assert next(l for l in body["lines"] if l["id"] == line_id)["status"] == "open"
    finally:
        _cleanup_table("T-908")


def test_claim_equal_slot_is_race_safe(client):
    _seed_table_order("T-909")
    try:
        req(client, "POST", "/api/table/T-909/split/mode?business=default", json={"mode": "equal", "equalCount": 2})
        split_id = req(client, "GET", "/api/table/T-909/split?business=default").json()["id"]
        t1, t2 = _guest_token("+61412345005"), _guest_token("+61412345006")

        r1 = req(client, "POST", f"/api/table/split/{split_id}/claim-equal",
                 headers={"Authorization": f"Bearer {t1}"}, json={"index": 0})
        assert r1.status_code == 200

        r2 = req(client, "POST", f"/api/table/split/{split_id}/claim-equal",
                 headers={"Authorization": f"Bearer {t2}"}, json={"index": 0})
        assert r2.status_code == 409
    finally:
        _cleanup_table("T-909")


# ---------------------------------------------------------------- checkout

def test_checkout_requires_the_caller_to_have_claimed_the_line(client):
    _seed_table_order("T-910")
    try:
        split_id = req(client, "GET", "/api/table/T-910/split?business=default").json()["id"]
        line_id = req(client, "GET", "/api/table/T-910/split?business=default").json()["lines"][0]["id"]
        token = _guest_token("+61412345007")
        # Never claimed — straight to checkout.
        r = req(client, "POST", f"/api/table/split/{split_id}/checkout",
                headers={"Authorization": f"Bearer {token}"},
                json={"provider": "crypto", "lineIds": [line_id]})
        assert r.status_code == 403
    finally:
        _cleanup_table("T-910")


def test_stripe_checkout_reports_not_configured_honestly(client, monkeypatch):
    monkeypatch.delenv("STRIPE_API_KEY", raising=False)
    _seed_table_order("T-911")
    try:
        split_id = req(client, "GET", "/api/table/T-911/split?business=default").json()["id"]
        line_id = req(client, "GET", "/api/table/T-911/split?business=default").json()["lines"][0]["id"]
        token = _guest_token("+61412345008")
        req(client, "POST", f"/api/table/split/{split_id}/claim",
            headers={"Authorization": f"Bearer {token}"}, json={"lineIds": [line_id]})
        r = req(client, "POST", f"/api/table/split/{split_id}/checkout",
                headers={"Authorization": f"Bearer {token}"},
                json={"provider": "stripe", "lineIds": [line_id]})
        assert r.status_code == 500
        assert "not configured" in r.json()["detail"].lower()
    finally:
        _cleanup_table("T-911")
        from database import db
        _run(db.customers.delete_many({"phone": "+61412345008"}))


def test_crypto_checkout_creates_a_charge_tagged_with_split_metadata(client, monkeypatch):
    import services.coinbase_commerce as cc

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {
            "id": "charge-uuid-split", "code": "SPLITCODE1",
            "hosted_url": "https://commerce.coinbase.com/charges/SPLITCODE1",
            "timeline": [{"status": "NEW"}],
        }})
    monkeypatch.setenv("COINBASE_COMMERCE_API_KEY", "cc-test-key")
    monkeypatch.setattr(cc.httpx, "AsyncClient", _mock_client_factory(handler))

    _seed_table_order("T-912")
    try:
        split_id = req(client, "GET", "/api/table/T-912/split?business=default").json()["id"]
        line_id = req(client, "GET", "/api/table/T-912/split?business=default").json()["lines"][0]["id"]
        token = _guest_token("+61412345009")
        req(client, "POST", f"/api/table/split/{split_id}/claim",
            headers={"Authorization": f"Bearer {token}"}, json={"lineIds": [line_id]})

        r = req(client, "POST", f"/api/table/split/{split_id}/checkout",
                headers={"Authorization": f"Bearer {token}"},
                json={"provider": "crypto", "lineIds": [line_id]})
        assert r.status_code == 200, r.text
        assert r.json()["sessionId"] == "SPLITCODE1"

        from database import db
        payment = _run(db.payment_transactions.find_one({"sessionId": "SPLITCODE1"}, {"_id": 0}))
        assert payment["splitSessionId"] == split_id
        assert payment["splitLineIds"] == [line_id]
        assert payment["kind"] == "pos_sale"
    finally:
        _cleanup_table("T-912")
        from database import db
        _run(db.payment_transactions.delete_many({"sessionId": "SPLITCODE1"}))
        _run(db.customers.delete_many({"phone": "+61412345009"}))


def test_paying_finalizes_the_sale_and_marks_the_line_paid(client, monkeypatch):
    import services.coinbase_commerce as cc
    import routes.transactions

    def create_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {
            "id": "charge-uuid-split2", "code": "SPLITCODE2",
            "hosted_url": "https://commerce.coinbase.com/charges/SPLITCODE2",
            "timeline": [{"status": "NEW"}],
        }})
    monkeypatch.setenv("COINBASE_COMMERCE_API_KEY", "cc-test-key")
    monkeypatch.setattr(cc.httpx, "AsyncClient", _mock_client_factory(create_handler))

    finalize_calls = []
    async def fake_create_transaction(payload, user):
        finalize_calls.append((payload, user))
        class T:
            id = "TXN-SPLIT-1"
        return T()
    monkeypatch.setattr(routes.transactions, "create_transaction", fake_create_transaction)

    _seed_table_order("T-913")
    try:
        split_id = req(client, "GET", "/api/table/T-913/split?business=default").json()["id"]
        line_id = req(client, "GET", "/api/table/T-913/split?business=default").json()["lines"][0]["id"]
        token = _guest_token("+61412345010")
        req(client, "POST", f"/api/table/split/{split_id}/claim",
            headers={"Authorization": f"Bearer {token}"}, json={"lineIds": [line_id]})
        req(client, "POST", f"/api/table/split/{split_id}/checkout",
            headers={"Authorization": f"Bearer {token}"},
            json={"provider": "crypto", "lineIds": [line_id]})

        def poll_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": {
                "id": "charge-uuid-split2", "code": "SPLITCODE2",
                "timeline": [{"status": "NEW"}, {"status": "COMPLETED"}],
            }})
        monkeypatch.setattr(cc.httpx, "AsyncClient", _mock_client_factory(poll_handler))

        r = req(client, "GET", "/api/crypto/checkout/status/SPLITCODE2")
        assert r.status_code == 200
        assert r.json()["paymentStatus"] == "paid"
        # A guest returning from checkout needs this to route back to their
        # bill, not a staff-only "Back to POS" screen (PaymentSuccess.jsx).
        assert r.json()["splitSessionId"] == split_id
        assert len(finalize_calls) == 1

        status = req(client, "GET", f"/api/table/split/{split_id}/status").json()
        paid_line = next(l for l in status["lines"] if l["id"] == line_id)
        assert paid_line["status"] == "paid"
    finally:
        _cleanup_table("T-913")
        from database import db
        _run(db.payment_transactions.delete_many({"sessionId": "SPLITCODE2"}))
        _run(db.customers.delete_many({"phone": "+61412345010"}))


def test_split_settles_once_every_line_is_paid(client, monkeypatch):
    import routes.transactions
    from services import bill_split

    async def fake_create_transaction(payload, user):
        class T:
            id = "TXN-SPLIT-SETTLE"
        return T()
    monkeypatch.setattr(routes.transactions, "create_transaction", fake_create_transaction)

    _seed_table_order("T-914", items=[
        {"productId": "PROD-FRIES", "productName": "Fries", "category": "Sides", "quantity": 1},
    ])
    try:
        split = req(client, "GET", "/api/table/T-914/split?business=default").json()
        assert len(split["lines"]) == 1
        line_id = split["lines"][0]["id"]

        _run(bill_split.mark_lines_paid(split["id"], [line_id], None, "TXN-SPLIT-SETTLE"))
        status = req(client, "GET", f"/api/table/split/{split['id']}/status").json()
        assert status["status"] == "settled"
    finally:
        _cleanup_table("T-914")


def test_a_verified_phone_creates_a_real_customer_that_earns_points_on_checkout(client, monkeypatch):
    import services.coinbase_commerce as cc

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {
            "id": "charge-uuid-split3", "code": "SPLITCODE3",
            "hosted_url": "https://commerce.coinbase.com/charges/SPLITCODE3",
            "timeline": [{"status": "NEW"}],
        }})
    monkeypatch.setenv("COINBASE_COMMERCE_API_KEY", "cc-test-key")
    monkeypatch.setattr(cc.httpx, "AsyncClient", _mock_client_factory(handler))

    phone = "+61412399999"
    _seed_table_order("T-915")
    try:
        from database import db
        _run(db.customers.delete_many({"phone": phone}))

        split_id = req(client, "GET", "/api/table/T-915/split?business=default").json()["id"]
        line_id = req(client, "GET", "/api/table/T-915/split?business=default").json()["lines"][0]["id"]
        token = _guest_token(phone)
        req(client, "POST", f"/api/table/split/{split_id}/claim",
            headers={"Authorization": f"Bearer {token}"}, json={"lineIds": [line_id]})
        req(client, "POST", f"/api/table/split/{split_id}/checkout",
            headers={"Authorization": f"Bearer {token}"},
            json={"provider": "crypto", "lineIds": [line_id]})

        # A real, functional db.customers record — the same table
        # create_transaction reads/writes for loyalty — not a
        # disconnected identity-layer touchpoint.
        customer = _run(db.customers.find_one({"phone": phone}, {"_id": 0}))
        assert customer is not None
        assert customer["email"] is None
        assert customer["points"] == 0  # not paid yet — just created

        payment = _run(db.payment_transactions.find_one({"sessionId": "SPLITCODE3"}, {"_id": 0}))
        assert payment["salePayload"]["customerId"] == customer["id"]
    finally:
        _cleanup_table("T-915")
        from database import db
        _run(db.payment_transactions.delete_many({"sessionId": "SPLITCODE3"}))
        _run(db.customers.delete_many({"phone": phone}))


def test_a_returning_guests_second_split_payment_matches_their_existing_customer(client):
    from services.customer_match import find_or_create_customer_by_phone
    from database import db

    phone = "+61412388888"
    _run(db.customers.delete_many({"phone": phone}))
    try:
        first = _run(find_or_create_customer_by_phone(phone, business_id="default"))
        second = _run(find_or_create_customer_by_phone(phone, business_id="default"))
        assert first["id"] == second["id"]
        assert _run(db.customers.count_documents({"phone": phone})) == 1
    finally:
        _run(db.customers.delete_many({"phone": phone}))


# ---------------------------------------------------------------- custom split

def test_custom_split_amounts_must_add_up_to_the_bill(client):
    _seed_table_order("T-916")
    try:
        # Bill is 2x$15 burger + $6 fries = $36. These don't add up.
        r = req(client, "POST", "/api/table/T-916/split/mode?business=default",
                json={"mode": "custom", "customAmounts": [10, 10]})
        assert r.status_code == 400
        assert "add up" in r.json()["detail"].lower()
    finally:
        _cleanup_table("T-916")


def test_custom_split_amounts_create_uneven_claimable_shares(client):
    _seed_table_order("T-917")
    try:
        body = req(client, "POST", "/api/table/T-917/split/mode?business=default",
                    json={"mode": "custom", "customAmounts": [30, 6]}).json()
        assert body["mode"] == "custom"
        amounts = sorted(p["amount"] for p in body["equalParts"])
        assert amounts == [6.0, 30.0]
    finally:
        _cleanup_table("T-917")


def test_custom_split_percents_convert_to_dollars_and_absorb_rounding_drift(client):
    _seed_table_order("T-918")
    try:
        # $36 total split 33.33/33.33/33.34 by percent.
        body = req(client, "POST", "/api/table/T-918/split/mode?business=default",
                    json={"mode": "custom", "customPercents": [33.33, 33.33, 33.34]}).json()
        total = round(sum(p["amount"] for p in body["equalParts"]), 2)
        assert total == 36.0
    finally:
        _cleanup_table("T-918")


def test_custom_split_percents_must_add_up_to_100(client):
    _seed_table_order("T-919")
    try:
        r = req(client, "POST", "/api/table/T-919/split/mode?business=default",
                json={"mode": "custom", "customPercents": [50, 40]})
        assert r.status_code == 400
    finally:
        _cleanup_table("T-919")


def test_custom_share_is_claimable_and_payable_via_the_shared_slot_endpoints(client, monkeypatch):
    import services.coinbase_commerce as cc

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {
            "id": "charge-uuid-custom1", "code": "CUSTOMCODE1",
            "hosted_url": "https://commerce.coinbase.com/charges/CUSTOMCODE1",
            "timeline": [{"status": "NEW"}],
        }})
    monkeypatch.setenv("COINBASE_COMMERCE_API_KEY", "cc-test-key")
    monkeypatch.setattr(cc.httpx, "AsyncClient", _mock_client_factory(handler))

    _seed_table_order("T-920")
    try:
        split = req(client, "POST", "/api/table/T-920/split/mode?business=default",
                    json={"mode": "custom", "customAmounts": [30, 6]}).json()
        split_id = split["id"]
        slot_index = next(p["index"] for p in split["equalParts"] if p["amount"] == 6.0)
        token = _guest_token("+61412345020")

        claimed = req(client, "POST", f"/api/table/split/{split_id}/claim-equal",
                       headers={"Authorization": f"Bearer {token}"}, json={"index": slot_index})
        assert claimed.status_code == 200

        r = req(client, "POST", f"/api/table/split/{split_id}/checkout",
                headers={"Authorization": f"Bearer {token}"},
                json={"provider": "crypto", "slotIndex": slot_index})
        assert r.status_code == 200, r.text

        from database import db
        payment = _run(db.payment_transactions.find_one({"sessionId": "CUSTOMCODE1"}, {"_id": 0}))
        assert payment["splitSlotIndex"] == slot_index
        assert payment["amount"] == 6.0
    finally:
        _cleanup_table("T-920")
        from database import db
        _run(db.payment_transactions.delete_many({"sessionId": "CUSTOMCODE1"}))
        _run(db.customers.delete_many({"phone": "+61412345020"}))


# ---------------------------------------------------------------------- tip

def test_checkout_adds_a_tip_on_top_of_the_claimed_amount(client, monkeypatch):
    import services.coinbase_commerce as cc

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {
            "id": "charge-uuid-tip1", "code": "TIPCODE1",
            "hosted_url": "https://commerce.coinbase.com/charges/TIPCODE1",
            "timeline": [{"status": "NEW"}],
        }})
    monkeypatch.setenv("COINBASE_COMMERCE_API_KEY", "cc-test-key")
    monkeypatch.setattr(cc.httpx, "AsyncClient", _mock_client_factory(handler))

    _seed_table_order("T-921")
    try:
        split_id = req(client, "GET", "/api/table/T-921/split?business=default").json()["id"]
        line = req(client, "GET", "/api/table/T-921/split?business=default").json()["lines"][0]
        token = _guest_token("+61412345021")
        req(client, "POST", f"/api/table/split/{split_id}/claim",
            headers={"Authorization": f"Bearer {token}"}, json={"lineIds": [line["id"]]})

        r = req(client, "POST", f"/api/table/split/{split_id}/checkout",
                headers={"Authorization": f"Bearer {token}"},
                json={"provider": "crypto", "lineIds": [line["id"]], "tipAmount": 3.5})
        assert r.status_code == 200, r.text

        from database import db
        payment = _run(db.payment_transactions.find_one({"sessionId": "TIPCODE1"}, {"_id": 0}))
        assert payment["amount"] == round(line["unitPrice"] + 3.5, 2)
        assert payment["salePayload"]["tipAmount"] == 3.5
        tip_line = next(i for i in payment["salePayload"]["items"] if i["productId"] == "SPLIT-TIP")
        assert tip_line["price"] == 3.5
    finally:
        _cleanup_table("T-921")
        from database import db
        _run(db.payment_transactions.delete_many({"sessionId": "TIPCODE1"}))
        _run(db.customers.delete_many({"phone": "+61412345021"}))


def test_checkout_rejects_a_negative_tip(client):
    _seed_table_order("T-922")
    try:
        split_id = req(client, "GET", "/api/table/T-922/split?business=default").json()["id"]
        line_id = req(client, "GET", "/api/table/T-922/split?business=default").json()["lines"][0]["id"]
        token = _guest_token("+61412345022")
        req(client, "POST", f"/api/table/split/{split_id}/claim",
            headers={"Authorization": f"Bearer {token}"}, json={"lineIds": [line_id]})
        r = req(client, "POST", f"/api/table/split/{split_id}/checkout",
                headers={"Authorization": f"Bearer {token}"},
                json={"provider": "crypto", "lineIds": [line_id], "tipAmount": -5})
        assert r.status_code == 400
    finally:
        _cleanup_table("T-922")


# ------------------------------------------------------------------- receipt

def test_paying_sends_the_guest_a_receipt_for_just_their_own_share(client, monkeypatch):
    from services import bill_split, split_receipt

    receipts_sent = []
    async def fake_send_payment_receipt(split, line_ids, slot_index, transaction_id, guest_email=None):
        receipts_sent.append({"lineIds": line_ids, "slotIndex": slot_index, "email": guest_email})
        return {"sent": True}
    monkeypatch.setattr(split_receipt, "send_payment_receipt", fake_send_payment_receipt)

    _seed_table_order("T-923", items=[
        {"productId": "PROD-FRIES", "productName": "Fries", "category": "Sides", "quantity": 1},
    ])
    try:
        split = req(client, "GET", "/api/table/T-923/split?business=default").json()
        line_id = split["lines"][0]["id"]
        _run(bill_split.mark_lines_paid(split["id"], [line_id], None, "TXN-RECEIPT-1",
                                          guest_email="guest@example.com"))
        assert len(receipts_sent) == 1
        assert receipts_sent[0]["lineIds"] == [line_id]
        assert receipts_sent[0]["email"] == "guest@example.com"
    finally:
        _cleanup_table("T-923")


def test_receipt_failure_never_blocks_marking_the_line_paid(client, monkeypatch):
    from services import bill_split, split_receipt

    async def broken_receipt(*a, **kw):
        raise RuntimeError("SMS provider exploded")
    monkeypatch.setattr(split_receipt, "send_payment_receipt", broken_receipt)

    _seed_table_order("T-924", items=[
        {"productId": "PROD-FRIES", "productName": "Fries", "category": "Sides", "quantity": 1},
    ])
    try:
        split = req(client, "GET", "/api/table/T-924/split?business=default").json()
        line_id = split["lines"][0]["id"]
        _run(bill_split.mark_lines_paid(split["id"], [line_id], None, "TXN-RECEIPT-2"))
        status = req(client, "GET", f"/api/table/split/{split['id']}/status").json()
        assert status["lines"][0]["status"] == "paid"
    finally:
        _cleanup_table("T-924")


# --------------------------------------------------------- floor-plan auto-close

def test_settling_a_split_frees_the_table_on_the_floor_plan(client, owner_headers, monkeypatch):
    from database import db
    import routes.transactions

    async def fake_create_transaction(payload, user):
        class T:
            id = "TXN-SPLIT-FLOORPLAN"
        return T()
    monkeypatch.setattr(routes.transactions, "create_transaction", fake_create_transaction)

    plan = req(client, "POST", "/api/floor-plans", headers=owner_headers, json={
        "name": "Test Floor", "locationId": "loc-1", "sections": [],
        "tables": [{
            "id": "TBL-T925", "number": "T-925", "capacity": 4, "maxCovers": 4,
            "shape": "square", "x": 0, "y": 0, "width": 60, "height": 60, "rotation": 0,
            "section": None, "status": "occupied", "isActive": True,
        }],
    }).json()

    _seed_table_order("T-925", items=[
        {"productId": "PROD-FRIES", "productName": "Fries", "category": "Sides", "quantity": 1},
    ])
    try:
        split = req(client, "GET", "/api/table/T-925/split?business=default").json()
        line_id = split["lines"][0]["id"]
        from services import bill_split
        _run(bill_split.mark_lines_paid(split["id"], [line_id], None, "TXN-SPLIT-FLOORPLAN"))

        status = req(client, "GET", f"/api/table/split/{split['id']}/status").json()
        assert status["status"] == "settled"

        refreshed_plan = req(client, "GET", f"/api/floor-plans/{plan['id']}", headers=owner_headers).json()
        table = next(t for t in refreshed_plan["tables"] if t["id"] == "TBL-T925")
        assert table["status"] == "available"
    finally:
        _cleanup_table("T-925")
        req(client, "DELETE", f"/api/floor-plans/{plan['id']}", headers=owner_headers)


# ------------------------------------------------------------- staff dashboard

def test_active_splits_lists_every_open_table_with_claims_and_tabs(client, owner_headers):
    _seed_table_order("T-926")
    try:
        split = req(client, "GET", "/api/table/T-926/split?business=default").json()
        line_id = split["lines"][0]["id"]
        token = _guest_token("+61412345026")
        req(client, "POST", f"/api/table/split/{split['id']}/claim",
            headers={"Authorization": f"Bearer {token}"}, json={"lineIds": [line_id]})

        # active-splits is a staff-only monitoring feed — requires auth.
        body = req(client, "GET", "/api/table/active-splits", headers=owner_headers).json()
        row = next(s for s in body["splits"] if s["id"] == split["id"])
        assert row["tableNumber"] == "T-926"
        assert row["totalAmount"] == round(sum(l["unitPrice"] for l in split["lines"]), 2)
        claim = next(c for c in row["claims"] if c["phone"] == "+61412345026")
        assert claim["paid"] is False
        assert row["openTabs"] == []
    finally:
        _cleanup_table("T-926")


# --------------------------------------------------------- staff-endpoint auth
# Regression coverage for a real vulnerability: this whole router rides
# server.py's "/api/table/" public prefix (for the genuinely guest-facing
# endpoints above), which doesn't distinguish "guest-facing" from
# "staff-only" — active-splits, staff-status and staff-process-tab were all
# reachable with no credential at all before Depends(get_user) was added.

def test_active_splits_rejects_an_unauthenticated_caller(anon):
    r = req(anon, "GET", "/api/table/active-splits")
    assert r.status_code in (401, 403), r.text


def test_staff_status_rejects_an_unauthenticated_caller(anon):
    r = req(anon, "GET", "/api/table/T-999/split/staff-status")
    assert r.status_code in (401, 403), r.text


def test_staff_process_tab_rejects_an_unauthenticated_caller(anon):
    r = req(anon, "POST", "/api/table/split/some-split-id/staff-process-tab",
            json={"tabId": "does-not-matter", "amount": 10})
    assert r.status_code in (401, 403), r.text


# ----------------------------------------------------------- tenant isolation
# Remediation of the final readiness audit's High finding: db.bill_splits
# carried no businessId at all — get_or_create_split resolved a table's
# open kitchen order by tableNumber alone, so two businesses that happen to
# both have a "Table 5" with an open order at the same time would collide,
# with whichever business's order Mongo returned first becoming BOTH
# tables' bill. Fixed: the QR link must now carry a real ?business=, every
# kitchen-order lookup and the created split are scoped to it, and the
# staff-facing monitoring/collection endpoints are scoped to the caller's
# own business.

def _make_business(client, owner_headers, *, biz_id, email):
    """A second, independent business + logged-in owner, for cross-tenant
    tests — same pattern as test_voice_inbound_safety.py's _login_as."""
    from database import db
    _run(db.businesses.insert_one({
        "id": biz_id, "slug": biz_id, "name": f"Biz {biz_id}", "status": "active",
    }))
    client.post("/api/auth/register", headers=owner_headers, json={
        "name": "Bill Split Test Owner", "email": email, "password": "BillSplitTest2026!",
    })
    _run(db.auth_users.update_one({"email": email}, {"$set": {"role": "owner", "businessId": biz_id}}))
    r = client.post("/api/auth/login", json={"email": email, "password": "BillSplitTest2026!"})
    assert r.status_code == 200, f"login failed: {r.text[:200]}"
    client.cookies.clear()
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _cleanup_business(biz_id):
    from database import db
    _run(db.businesses.delete_many({"id": biz_id}))
    _run(db.auth_users.delete_many({"businessId": biz_id}))


def test_get_split_rejects_a_missing_or_unresolvable_business(client):
    _seed_table_order("T-NOBIZ")
    try:
        r = req(client, "GET", "/api/table/T-NOBIZ/split")
        assert r.status_code == 400, r.text
        r = req(client, "GET", "/api/table/T-NOBIZ/split?business=does-not-exist")
        assert r.status_code == 404, r.text
    finally:
        _cleanup_table("T-NOBIZ")


def test_two_businesses_with_the_same_table_number_never_share_a_bill(client, owner_headers):
    """The actual collision the missing businessId allowed: both businesses
    have an open order on a table labelled 'T-COLLIDE' — a guest scanning
    either QR must only ever see their own venue's order and lines."""
    biz_b = "bill-split-biz-b"
    try:
        _make_business(client, owner_headers, biz_id=biz_b, email="billsplit-b-owner@nua.com")
        _seed_table_order("T-COLLIDE", order_id="KORD-SPLIT-DEFAULT", business_id="default",
                           items=[{"productId": "PROD-BURGER", "productName": "Burger",
                                   "category": "Mains", "quantity": 1}])
        from database import db
        _run(db.kitchen_orders.insert_one({
            "id": "KORD-SPLIT-BIZB", "tableNumber": "T-COLLIDE", "businessId": biz_b,
            "items": [{"productId": "PROD-FRIES", "productName": "Fries",
                       "category": "Sides", "quantity": 3}],
            "status": "new",
        }))

        split_default = req(client, "GET", "/api/table/T-COLLIDE/split?business=default").json()
        split_b = req(client, "GET", f"/api/table/T-COLLIDE/split?business={biz_b}").json()

        assert split_default["id"] != split_b["id"]
        assert [l["productName"] for l in split_default["lines"]] == ["Burger"]
        assert [l["productName"] for l in split_b["lines"]] == ["Fries", "Fries", "Fries"]
    finally:
        _cleanup_table("T-COLLIDE")
        _run(__import__("database").db.kitchen_orders.delete_many({"tableNumber": "T-COLLIDE"}))
        _cleanup_business(biz_b)


def test_active_splits_never_shows_another_business_open_split(client, owner_headers):
    biz_b = "bill-split-biz-b2"
    try:
        biz_b_headers = _make_business(client, owner_headers, biz_id=biz_b, email="billsplit-b2-owner@nua.com")
        _seed_table_order("T-ISOL-1", order_id="KORD-ISOL-1")
        req(client, "GET", "/api/table/T-ISOL-1/split?business=default")

        body = req(client, "GET", "/api/table/active-splits", headers=biz_b_headers).json()
        assert all(s["tableNumber"] != "T-ISOL-1" for s in body["splits"]), (
            "a staff member of a different business must never see this business's open split"
        )
    finally:
        _cleanup_table("T-ISOL-1")
        _cleanup_business(biz_b)


def test_staff_status_is_scoped_to_the_callers_own_business(client, owner_headers):
    biz_b = "bill-split-biz-b3"
    try:
        biz_b_headers = _make_business(client, owner_headers, biz_id=biz_b, email="billsplit-b3-owner@nua.com")
        _seed_table_order("T-ISOL-2", order_id="KORD-ISOL-2")
        req(client, "GET", "/api/table/T-ISOL-2/split?business=default")

        r = req(client, "GET", "/api/table/T-ISOL-2/split/staff-status", headers=biz_b_headers)
        assert r.status_code == 404, (
            "another business's staff must not be able to read this table's split status"
        )
        r_owner = req(client, "GET", "/api/table/T-ISOL-2/split/staff-status", headers=owner_headers)
        assert r_owner.status_code == 200
    finally:
        _cleanup_table("T-ISOL-2")
        _cleanup_business(biz_b)


def test_staff_process_tab_rejects_a_tab_belonging_to_another_business(client, owner_headers):
    biz_b = "bill-split-biz-b4"
    try:
        biz_b_headers = _make_business(client, owner_headers, biz_id=biz_b, email="billsplit-b4-owner@nua.com")
        _seed_table_order("T-ISOL-3", order_id="KORD-ISOL-3")
        split = req(client, "GET", "/api/table/T-ISOL-3/split?business=default").json()
        line_id = split["lines"][0]["id"]
        token = _guest_token("+61412345099")
        req(client, "POST", f"/api/table/split/{split['id']}/claim",
            headers={"Authorization": f"Bearer {token}"}, json={"lineIds": [line_id]})
        r = req(client, "POST", f"/api/table/split/{split['id']}/partial-checkout",
                headers={"Authorization": f"Bearer {token}"},
                json={"amount": 5, "lineIds": [line_id], "totalAmount": 15})
        tab_id = r.json()["tabId"]

        r = req(client, "POST", "/api/table/split/x/staff-process-tab",
                headers=biz_b_headers, json={"tabId": tab_id, "amount": 10})
        assert r.status_code == 404, (
            "a staff member of a different business must not be able to collect this tab"
        )
    finally:
        _cleanup_table("T-ISOL-3")
        _cleanup_business(biz_b)


# ------------------------------------------------------- guest-intent tab


def test_partial_checkout_records_guest_intent_only_not_a_completed_payment(client):
    """Found during the Trust Release final readiness audit: this endpoint
    used to call split_payment.record_partial_payment(..., method="card", ...)
    immediately, marking the requested amount "paid" with no payment
    processor anywhere in the path. Now it only records the guest's stated
    intent (an open tab, $0 paid) — a staff member must actually collect and
    confirm it via /staff-process-tab before it counts as paid."""
    from database import db
    _seed_table_order("T-INTENT-1")
    try:
        split = req(client, "GET", "/api/table/T-INTENT-1/split?business=default").json()
        line_id = split["lines"][0]["id"]
        token = _guest_token("+61412345111")
        r = req(client, "POST", f"/api/table/split/{split['id']}/partial-checkout",
                headers={"Authorization": f"Bearer {token}"},
                json={"amount": 5, "lineIds": [line_id], "totalAmount": 15})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "open", "must not be pre-marked paid/partial — staff hasn't collected anything yet"
        assert body["paidAmount"] == 0.0
        assert "collect and confirm" in body["message"].lower()

        tab = _run(db.split_tabs.find_one({"id": body["tabId"]}, {"_id": 0}))
        assert tab["status"] == "open"
        assert tab["paidAmount"] == 0.0
        assert tab["payments"] == [], "no payment record must exist until staff actually collects it"
    finally:
        _cleanup_table("T-INTENT-1")


def test_partial_checkout_rejects_non_positive_amount(client):
    _seed_table_order("T-INTENT-2")
    try:
        split = req(client, "GET", "/api/table/T-INTENT-2/split?business=default").json()
        token = _guest_token("+61412345112")
        r = req(client, "POST", f"/api/table/split/{split['id']}/partial-checkout",
                headers={"Authorization": f"Bearer {token}"}, json={"amount": 0})
        assert r.status_code == 400, r.text
    finally:
        _cleanup_table("T-INTENT-2")


# --------------------------------------------------------------- group API


def test_create_group_404s_for_a_split_id_that_does_not_exist(client):
    """services/split_group.create_split_group used to create a group document
    for ANY split_id string with no check it corresponded to a real, open
    split — an orphaned group with nothing to ever attach to."""
    from database import db
    token = _guest_token("+61412345113")
    r = req(client, "POST", "/api/table/split/NOT-A-REAL-SPLIT-ID/group/create",
            headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 404, r.text
    assert _run(db.split_groups.find_one({"splitId": "NOT-A-REAL-SPLIT-ID"})) is None


def test_group_status_requires_a_guest_session(client):
    """get_group_status used to have no Depends(get_guest_session) at all —
    fully unauthenticated, readable by anyone who could guess/enumerate a
    split_id."""
    _seed_table_order("T-GROUP-1")
    try:
        split = req(client, "GET", "/api/table/T-GROUP-1/split?business=default").json()
        r = req(client, "GET", f"/api/table/split/{split['id']}/group/status")
        assert r.status_code in (401, 403, 422), (
            f"expected an auth failure with no guest session, got {r.status_code}: {r.text[:200]}"
        )
    finally:
        _cleanup_table("T-GROUP-1")


def test_group_status_redacts_organizer_and_participants_for_a_non_participant(client):
    """A guest who is not in the group must not learn the organizer's phone
    number or the participant list — those are phone-number PII, and any
    guest holding a valid session token for a completely different phone
    could otherwise read them just by knowing the split_id."""
    _seed_table_order("T-GROUP-2")
    try:
        split = req(client, "GET", "/api/table/T-GROUP-2/split?business=default").json()
        organizer_token = _guest_token("+61412345114")
        r = req(client, "POST", f"/api/table/split/{split['id']}/group/create",
                headers={"Authorization": f"Bearer {organizer_token}"})
        assert r.status_code == 200, r.text

        outsider_token = _guest_token("+61412345115")
        r = req(client, "GET", f"/api/table/split/{split['id']}/group/status",
                headers={"Authorization": f"Bearer {outsider_token}"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert "organizerPhone" not in body
        assert "participants" not in body

        r_organizer = req(client, "GET", f"/api/table/split/{split['id']}/group/status",
                           headers={"Authorization": f"Bearer {organizer_token}"})
        assert r_organizer.status_code == 200
        assert r_organizer.json().get("organizerPhone") == "+61412345114"
    finally:
        _cleanup_table("T-GROUP-2")


# ------------------------------------------------------- websocket broadcast


class _FakeWebSocket:
    def __init__(self):
        self.messages = []

    async def send_json(self, msg):
        self.messages.append(msg)


def _register_fake_ws(split_id):
    from services import split_realtime
    mgr = split_realtime.get_manager()
    ws = _FakeWebSocket()
    _run(mgr.register_connection(split_id, ws))
    return ws


def _no_phone_leaked(messages, *phones):
    """No broadcast message anywhere in `messages` — at any nesting level —
    may contain any of `phones` as a value."""
    import json
    blob = json.dumps(messages, default=str)
    return all(phone not in blob for phone in phones)


def test_group_create_invite_and_partial_checkout_never_broadcast_a_phone_number(client):
    """These broadcasts go out on /ws/split/{split_id}, which has no
    authentication at all by design (see websocket_split_updates's own
    docstring) — anyone who can open it for a split_id (itself reachable
    via the unauthenticated GET .../split) can watch every event on it.
    group_created used to carry the group's raw organizerPhone and
    participants list; guest_joined_group and guest_intends_partial_payment
    each carried the acting guest's raw phone. Found during a second
    independent final readiness audit."""
    _seed_table_order("T-WS-PII-1")
    try:
        split = req(client, "GET", "/api/table/T-WS-PII-1/split?business=default").json()
        ws = _register_fake_ws(split["id"])

        organizer_phone = "+61412345200"
        invitee_phone = "+61412345201"
        organizer_token = _guest_token(organizer_phone)

        r = req(client, "POST", f"/api/table/split/{split['id']}/group/create",
                headers={"Authorization": f"Bearer {organizer_token}"})
        assert r.status_code == 200, r.text

        r2 = req(client, "POST", f"/api/table/split/{split['id']}/group/invite",
                  headers={"Authorization": f"Bearer {organizer_token}"}, json={"phone": invitee_phone})
        assert r2.status_code == 200, r2.text

        invitee_token = _guest_token(invitee_phone)
        line_id = split["lines"][0]["id"]
        req(client, "POST", f"/api/table/split/{split['id']}/claim",
            headers={"Authorization": f"Bearer {invitee_token}"}, json={"lineIds": [line_id]})
        r3 = req(client, "POST", f"/api/table/split/{split['id']}/partial-checkout",
                  headers={"Authorization": f"Bearer {invitee_token}"},
                  json={"amount": 1, "lineIds": [line_id], "totalAmount": 15})
        assert r3.status_code == 200, r3.text

        assert len(ws.messages) >= 3, "expected at least the group-create/invite/partial-payment broadcasts"
        assert _no_phone_leaked(ws.messages, organizer_phone, invitee_phone), (
            f"a guest phone number must never appear in an unauthenticated websocket broadcast, "
            f"got messages: {ws.messages}"
        )
    finally:
        _cleanup_table("T-WS-PII-1")
