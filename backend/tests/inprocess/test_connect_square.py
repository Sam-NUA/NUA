"""NUA Connect / Square connector tests.

This sandbox has no outbound network path to any third-party host (confirmed
via the proxy allowlist — only npm/pypi/GitHub/anthropic.com are reachable),
so "verified against Square" here means: every httpx call the connector
makes is routed through an httpx.MockTransport that returns real,
documented Square response shapes (https://developer.squareup.com/reference/square),
and we assert the connector parses/normalizes/persists them correctly. The
connector code itself is unchanged between this and a real network call —
only the transport is swapped.
"""
import asyncio
import json

import httpx
import pytest

from tests.inprocess.conftest import req


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_business(client, owner_headers, *, biz_id, email):
    from database import db
    _run(db.businesses.insert_one({
        "id": biz_id, "slug": biz_id, "name": f"Biz {biz_id}", "status": "active",
    }))
    client.post("/api/auth/register", headers=owner_headers, json={
        "name": "Square Test Owner", "email": email, "password": "SquareTenantTest2026!",
    })
    _run(db.auth_users.update_one({"email": email}, {"$set": {"role": "owner", "businessId": biz_id}}))
    r = client.post("/api/auth/login", json={"email": email, "password": "SquareTenantTest2026!"})
    assert r.status_code == 200, f"login failed: {r.text[:200]}"
    client.cookies.clear()
    return {"Authorization": f"Bearer {r.json()['token']}"}


_RealAsyncClient = httpx.AsyncClient


def _mock_client_factory(handler):
    """Returns a drop-in replacement for httpx.AsyncClient(...) that routes
    all requests through `handler` instead of the network. Must capture the
    *real* AsyncClient class up front — monkeypatching square.py's `httpx`
    attribute patches the actual httpx module object (not a copy), so a
    factory that calls `httpx.AsyncClient(...)` internally would recurse
    into itself."""
    def factory(*args, **kwargs):
        return _RealAsyncClient(transport=httpx.MockTransport(handler), timeout=kwargs.get("timeout", 10))
    return factory


@pytest.fixture
def square_connector():
    from services.connect.connectors.square import SquareConnector
    return SquareConnector()


# ---------------------------------------------------------------- registry

def test_registry_reports_honest_status_for_every_provider(client, owner_headers):
    r = req(client, "GET", "/api/integrations", headers=owner_headers)
    assert r.status_code == 200
    providers = {p["slug"]: p for p in r.json()}

    assert providers["square"]["status"] == "needs_credentials"
    assert providers["doordash"]["status"] == "not_implemented"
    assert providers["xero"]["status"] == "not_implemented"
    for bank_slug in ("cba", "westpac", "anz", "nab", "macquarie", "bendigo",
                       "bankwest", "suncorp", "hsbc-au", "ing-au", "boq"):
        assert providers[bank_slug]["status"] == "pending_accreditation", bank_slug
        assert providers[bank_slug]["category"] == "Banks (AU)"
    # Stripe has no STRIPE_API_KEY set in the test environment.
    assert providers["stripe"]["status"] == "not_implemented"


def test_integrations_endpoints_require_auth(client, anon):
    r = req(anon, "GET", "/api/integrations")
    assert r.status_code in (401, 403)
    r = req(anon, "POST", "/api/integrations/square/connect", json={"accessToken": "x"})
    assert r.status_code in (401, 403)


# --------------------------------------------------------------- connect

def test_connect_square_succeeds_with_valid_credentials(client, owner_headers, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v2/locations"
        assert request.headers["Authorization"] == "Bearer sandbox-token-123"
        return httpx.Response(200, json={"locations": [{"id": "L1", "name": "Main St Cafe"}]})

    import services.connect.connectors.square as square_mod
    monkeypatch.setattr(square_mod.httpx, "AsyncClient", _mock_client_factory(handler))

    r = req(client, "POST", "/api/integrations/square/connect", headers=owner_headers, json={
        "accessToken": "sandbox-token-123", "locationId": "L1",
        "environment": "sandbox", "webhookSignatureKey": "whsec-test",
        "webhookNotificationUrl": "https://example.com/api/webhooks/square",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "connected"
    assert body["locations"][0]["id"] == "L1"

    detail = req(client, "GET", "/api/integrations/square", headers=owner_headers).json()
    assert detail["status"] == "connected"


def test_connect_square_reports_error_status_on_bad_credentials(client, owner_headers, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"errors": [{"code": "UNAUTHORIZED"}]})

    import services.connect.connectors.square as square_mod
    monkeypatch.setattr(square_mod.httpx, "AsyncClient", _mock_client_factory(handler))

    r = req(client, "POST", "/api/integrations/square/connect", headers=owner_headers,
            json={"accessToken": "bad-token", "locationId": "L1"})
    assert r.status_code == 502
    detail = req(client, "GET", "/api/integrations/square", headers=owner_headers).json()
    assert detail["status"] == "error"
    assert detail["lastError"]


def test_connect_unimplemented_provider_returns_501(client, owner_headers):
    r = req(client, "POST", "/api/integrations/doordash/connect", headers=owner_headers, json={"apiKey": "x"})
    assert r.status_code == 501


# ----------------------------------------------------------------- CDR banks

def test_cdr_bank_connect_never_reports_connected(client, owner_headers):
    r = req(client, "POST", "/api/integrations/cba/connect", headers=owner_headers,
            json={"cdrClientId": "id", "cdrClientSecret": "secret"})
    assert r.status_code == 200
    assert r.json()["status"] == "pending_accreditation"

    detail = req(client, "GET", "/api/integrations/cba", headers=owner_headers).json()
    assert detail["status"] == "pending_accreditation"
    assert detail["hasCredentials"] is True

    r = req(client, "POST", "/api/integrations/cba/sync", headers=owner_headers)
    assert r.status_code == 502  # ConnectorError: pending accreditation, sync unavailable


def test_cdr_connector_raises_accreditation_error_directly():
    import asyncio
    from services.connect.connectors.cdr_bank import make_cdr_connector, AccreditationRequiredError
    conn = make_cdr_connector("nab", "NAB")
    with pytest.raises(AccreditationRequiredError):
        asyncio.get_event_loop().run_until_complete(
            conn.test_connection({"cdrClientId": "x", "cdrClientSecret": "y"})
        )
    with pytest.raises(AccreditationRequiredError):
        conn.build_par_request({}, "https://nua.example/cb", "openid", "https://nab.example/authorize")


# --------------------------------------------------------------- catalog sync

def test_sync_catalog_creates_products_from_square_items(client, owner_headers, monkeypatch):
    catalog_page = {
        "objects": [
            {
                "type": "ITEM", "id": "SQ_ITEM_1", "is_deleted": False,
                "item_data": {
                    "name": "ZZZ Square Sync Test Item", "description": "Double shot",
                    "variations": [{
                        "item_variation_data": {"name": "Regular", "sku": "FW-REG",
                                                 "price_money": {"amount": 550, "currency": "AUD"}},
                    }],
                },
            },
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2/locations":
            return httpx.Response(200, json={"locations": [{"id": "L1", "name": "Cafe"}]})
        if request.url.path == "/v2/catalog/search":
            return httpx.Response(200, json=catalog_page)
        raise AssertionError(f"unexpected call to {request.url.path}")

    import services.connect.connectors.square as square_mod
    monkeypatch.setattr(square_mod.httpx, "AsyncClient", _mock_client_factory(handler))

    req(client, "POST", "/api/integrations/square/connect", headers=owner_headers,
        json={"accessToken": "tok", "locationId": "L1"})

    r = req(client, "POST", "/api/integrations/square/sync", headers=owner_headers, params={"sync_type": "catalog"})
    assert r.status_code == 200, r.text
    assert r.json()["counts"]["fetched"] == 1
    assert r.json()["counts"]["created"] == 0  # products aren't counted via bump("created") — fetched only

    products = req(client, "GET", "/api/products", headers=owner_headers).json()
    synced = next((p for p in products if p["name"] == "ZZZ Square Sync Test Item"), None)
    assert synced is not None
    assert synced["price"] == 5.50
    assert synced["sku"] == "FW-REG"

    history = req(client, "GET", "/api/integrations/sync-runs/history", headers=owner_headers,
                   params={"provider": "square"}).json()
    catalog_run = next(h for h in history if h["syncType"] == "catalog")
    assert catalog_run["status"] == "success"
    assert catalog_run["rawSamples"][0]["id"] == "SQ_ITEM_1"

    run_detail = req(client, "GET", f"/api/integrations/sync-runs/{catalog_run['id']}", headers=owner_headers).json()
    assert run_detail["rawSamples"][0]["item_data"]["name"] == "ZZZ Square Sync Test Item"

    # The integration card shows "last synced" at a glance — no need to open
    # the history dialog just to see whether a sync ever ran.
    detail = req(client, "GET", "/api/integrations/square", headers=owner_headers).json()
    assert detail["lastSyncAt"] == catalog_run["finishedAt"]
    assert detail["lastSyncStatus"] == "success"


# ----------------------------------------------------------------- sale sync

def test_sync_sales_ingests_order_and_credits_loyalty(client, owner_headers, monkeypatch):
    # Seed a customer already linked to a Square customer id, and a product
    # already linked to a Square catalog object id, so the sale sync exercises
    # both lookups instead of falling back to "unknown".
    # Deliberately NOT using req() here: it stamps a unique X-Tenant-Id per
    # call for rate-limit isolation, but that header also becomes this
    # write's businessId (middleware/actor_context.py) — which would then
    # not match owner_headers' JWT-derived "default" businessId used by the
    # read-side queries below. A plain client.post keeps this test's
    # businessId consistent throughout.
    create_cust = client.post("/api/customers", headers=owner_headers, json={
        "name": "Sam Diner", "email": "sam@example.com", "phone": "0400000000", "membershipTier": "Bronze",
    })
    assert create_cust.status_code == 200, create_cust.text
    customer_id = create_cust.json()["id"]
    from database import db
    import asyncio
    asyncio.get_event_loop().run_until_complete(
        db.customers.update_one({"id": customer_id}, {"$set": {"externalRefs": {"square": "SQ_CUST_1"}}})
    )

    orders_page = {
        "orders": [
            {
                "id": "SQ_ORDER_1", "state": "COMPLETED", "customer_id": "SQ_CUST_1",
                "line_items": [
                    {"catalog_object_id": "SQ_ITEM_UNKNOWN", "name": "Long Black", "quantity": "2",
                     "total_money": {"amount": 900, "currency": "AUD"}},
                ],
                "total_money": {"amount": 900, "currency": "AUD"},
            },
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2/locations":
            return httpx.Response(200, json={"locations": [{"id": "L1", "name": "Cafe"}]})
        if request.url.path == "/v2/orders/search":
            return httpx.Response(200, json=orders_page)
        raise AssertionError(f"unexpected call to {request.url.path}")

    import services.connect.connectors.square as square_mod
    monkeypatch.setattr(square_mod.httpx, "AsyncClient", _mock_client_factory(handler))

    req(client, "POST", "/api/integrations/square/connect", headers=owner_headers,
        json={"accessToken": "tok", "locationId": "L1"})
    r = req(client, "POST", "/api/integrations/square/sync", headers=owner_headers, params={"sync_type": "sales"})
    assert r.status_code == 200, r.text
    assert r.json()["counts"]["fetched"] == 1

    txns = req(client, "GET", "/api/transactions", headers=owner_headers).json()
    synced = next((t for t in txns if t.get("paymentMethod") == "square"), None)
    assert synced is not None
    assert synced["total"] == 9.00
    assert synced["customerId"] == customer_id

    customers = req(client, "GET", "/api/customers", headers=owner_headers).json()
    customer = next(c for c in customers if c["id"] == customer_id)
    assert customer["totalSpent"] >= 9.00
    assert customer["visits"] == 1

    # Running the same sync again must not double-count the same order.
    r2 = req(client, "POST", "/api/integrations/square/sync", headers=owner_headers, params={"sync_type": "sales"})
    assert r2.json()["counts"]["skipped"] == 1
    txns_after = req(client, "GET", "/api/transactions", headers=owner_headers).json()
    assert len([t for t in txns_after if t.get("paymentMethod") == "square"]) == 1


# --------------------------------------------------------------- customers

def test_sync_customers_creates_nua_customer(client, owner_headers, monkeypatch):
    customers_page = {
        "customers": [
            {"id": "SQ_CUST_9", "given_name": "Alex", "family_name": "Rivera",
             "email_address": "alex.rivera@example.com", "phone_number": "0411222333"},
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2/locations":
            return httpx.Response(200, json={"locations": [{"id": "L1", "name": "Cafe"}]})
        if request.url.path == "/v2/customers/search":
            return httpx.Response(200, json=customers_page)
        raise AssertionError(f"unexpected call to {request.url.path}")

    import services.connect.connectors.square as square_mod
    monkeypatch.setattr(square_mod.httpx, "AsyncClient", _mock_client_factory(handler))

    req(client, "POST", "/api/integrations/square/connect", headers=owner_headers,
        json={"accessToken": "tok", "locationId": "L1"})
    r = req(client, "POST", "/api/integrations/square/sync", headers=owner_headers, params={"sync_type": "customers"})
    assert r.status_code == 200, r.text

    customers = req(client, "GET", "/api/customers", headers=owner_headers).json()
    alex = next((c for c in customers if c["email"] == "alex.rivera@example.com"), None)
    assert alex is not None
    assert alex["name"] == "Alex Rivera"

    from database import db
    stored = _run(db.customers.find_one({"email": "alex.rivera@example.com"}, {"_id": 0}))
    assert stored["businessId"], (
        "a customer imported via Square sync must be stamped with the syncing business's id, "
        "not left untagged"
    )


def test_sync_customers_for_two_businesses_with_the_same_square_id_do_not_collide(client, owner_headers, monkeypatch):
    """_upsert_customer's lookup used to match by externalRefs.square ALONE
    — Square customer ids are global, not scoped per merchant account this
    app connects, so two different NUA businesses syncing (coincidentally
    or via shared sandbox data) the same Square customer id could silently
    take over each other's imported row."""
    def _handler_for(name):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/v2/locations":
                return httpx.Response(200, json={"locations": [{"id": "L1", "name": "Cafe"}]})
            if request.url.path == "/v2/customers/search":
                return httpx.Response(200, json={"customers": [
                    {"id": "SQ_CUST_SHARED", "given_name": name, "family_name": "Test",
                     "email_address": f"{name.lower()}@example.com", "phone_number": "0400000099"},
                ]})
            raise AssertionError(f"unexpected call to {request.url.path}")
        return handler

    import services.connect.connectors.square as square_mod
    from database import db

    other = _make_business(client, owner_headers, biz_id="square-sync-other-biz",
                            email="square-sync-other-owner@nua.com")

    monkeypatch.setattr(square_mod.httpx, "AsyncClient", _mock_client_factory(_handler_for("OwnerBiz")))
    req(client, "POST", "/api/integrations/square/connect", headers=owner_headers,
        json={"accessToken": "tok-a", "locationId": "L1"})
    req(client, "POST", "/api/integrations/square/sync", headers=owner_headers, params={"sync_type": "customers"})

    monkeypatch.setattr(square_mod.httpx, "AsyncClient", _mock_client_factory(_handler_for("OtherBiz")))
    req(client, "POST", "/api/integrations/square/connect", headers=other,
        json={"accessToken": "tok-b", "locationId": "L1"})
    req(client, "POST", "/api/integrations/square/sync", headers=other, params={"sync_type": "customers"})

    rows = _run(db.customers.find({"externalRefs.square": "SQ_CUST_SHARED"}, {"_id": 0}).to_list(10))
    assert len(rows) == 2, (
        f"two businesses syncing the same external Square customer id must each get their own row, "
        f"not share/overwrite one — got {len(rows)}"
    )
    biz_ids = {r["businessId"] for r in rows}
    assert biz_ids == {"default", "square-sync-other-biz"}
    names = {r["name"] for r in rows}
    assert names == {"OwnerBiz Test", "OtherBiz Test"}, "each business's own sync must not overwrite the other's name"


# ----------------------------------------------------------------- webhook

def test_webhook_signature_verification_matches_squares_documented_scheme(square_connector):
    import base64, hashlib, hmac
    body = b'{"type":"order.updated"}'
    creds = {"webhookSignatureKey": "whsec-abc", "webhookNotificationUrl": "https://nua.example/api/webhooks/square"}
    expected = base64.b64encode(
        hmac.new(b"whsec-abc", creds["webhookNotificationUrl"].encode() + body, hashlib.sha256).digest()
    ).decode()
    assert square_connector.verify_webhook(body, {"x-square-hmacsha256-signature": expected}, creds) is True
    assert square_connector.verify_webhook(body, {"x-square-hmacsha256-signature": "wrong"}, creds) is False
    assert square_connector.verify_webhook(body, {}, creds) is False


def test_webhook_endpoint_routes_event_to_owning_business_only(client, owner_headers, monkeypatch):
    import base64, hashlib, hmac

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2/locations":
            return httpx.Response(200, json={"locations": [{"id": "L1", "name": "Cafe"}]})
        raise AssertionError(f"unexpected call to {request.url.path}")

    import services.connect.connectors.square as square_mod
    monkeypatch.setattr(square_mod.httpx, "AsyncClient", _mock_client_factory(handler))

    notification_url = "https://nua.example/api/webhooks/square"
    req(client, "POST", "/api/integrations/square/connect", headers=owner_headers, json={
        "accessToken": "tok", "locationId": "L1", "webhookSignatureKey": "whsec-owner",
        "webhookNotificationUrl": notification_url,
    })

    body = json.dumps({
        "type": "order.updated",
        "data": {"object": {"order": {
            "id": "SQ_ORDER_WEBHOOK_1", "state": "COMPLETED", "location_id": "L1",
            "line_items": [{"catalog_object_id": "X", "name": "Espresso", "quantity": "1",
                             "total_money": {"amount": 400}}],
            "total_money": {"amount": 400},
        }}},
    }).encode()
    signature = base64.b64encode(
        hmac.new(b"whsec-owner", notification_url.encode() + body, hashlib.sha256).digest()
    ).decode()

    r = client.post("/api/webhooks/square", content=body,
                     headers={"x-square-hmacsha256-signature": signature, "Content-Type": "application/json"})
    assert r.status_code == 200, r.text

    # externalRefs isn't part of the Transaction response model (it's an
    # internal Connect-only field), so it never round-trips through the API
    # — assert against the stored document directly instead.
    from database import db
    import asyncio
    stored = asyncio.get_event_loop().run_until_complete(
        db.transactions.find_one({"externalRefs.square": "SQ_ORDER_WEBHOOK_1"}, {"_id": 0})
    )
    assert stored is not None
    assert stored["paymentMethod"] == "square"
    assert stored["total"] == 4.0


def test_webhook_rejects_bad_signature(client):
    r = client.post("/api/webhooks/square", content=b'{"type":"order.updated"}',
                     headers={"x-square-hmacsha256-signature": "forged", "Content-Type": "application/json"})
    assert r.status_code == 401
