"""Final pre-merge assurance pass: the genuinely anonymous guest-facing
endpoints in routes/public.py and routes/table_ordering.py previously had
no business-resolution signal at all, so every guest on every business's
public booking/menu/table-QR page saw and wrote to one pooled dataset
mixed across every business on the deployment.

Fixed by reusing routes/online_orders.py's already-shipped ?business=
<slug-or-id> resolution (the /order-online storefront's own mechanism)
rather than inventing a second one — an optional `business` param that
resolves against db.businesses and scopes the query/write, falling back
to today's exact pooled behavior when absent or unresolvable (the
single-business-deployment case, unaffected either way).

Covers: cross-tenant read isolation (a guest passing business A's slug
never sees business B's menu/events/table data), cross-tenant write
isolation (a reservation/waitlist-entry/table-order created with business
A's slug is stamped and later exposed as business A's, not mixed into B's
staff-facing views), and the critical negative case this whole fix exists
to prevent: an anonymous caller cannot use a spoofed X-Tenant-Id/
X-Business-Id header to read a specific target business's data when no
?business= param is given (see routes/public.py's _public_tenant_filter
docstring for exactly why middleware.actor_context.tenant_scope_filter
itself is NOT safe to reuse directly in these genuinely anonymous routes).
"""
import asyncio
from datetime import datetime, timedelta, timezone

from database import db
from tests.inprocess.conftest import req


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _future_date(days=14):
    return (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%d")


def _make_business(biz_id, slug, name):
    _run(db.businesses.insert_one({
        "id": biz_id, "slug": slug, "name": name, "ownerId": "system",
        "status": "active", "onboardingComplete": True,
    }))


def _cleanup_business(biz_id):
    _run(db.businesses.delete_one({"id": biz_id}))


# --------------------------------------------------------------- /public/menu

def test_public_menu_scoped_by_business_slug_does_not_leak_the_other_business(client):
    _make_business("PETR-BIZ-A", "petr-biz-a", "Biz A")
    _make_business("PETR-BIZ-B", "petr-biz-b", "Biz B")
    _run(db.products.insert_one({
        "id": "PETR-PROD-A", "name": "Biz A Secret Dish", "category": "Mains",
        "price": 11.0, "businessId": "PETR-BIZ-A",
    }))
    _run(db.products.insert_one({
        "id": "PETR-PROD-B", "name": "Biz B Secret Dish", "category": "Mains",
        "price": 22.0, "businessId": "PETR-BIZ-B",
    }))
    try:
        menu_a = req(client, "GET", "/api/public/menu", params={"business": "petr-biz-a"}).json()
        names_a = {item["name"] for cat in menu_a["categories"] for item in cat["items"]}
        assert "Biz A Secret Dish" in names_a
        assert "Biz B Secret Dish" not in names_a, "business A's public menu must never show business B's product"

        menu_b = req(client, "GET", "/api/public/menu", params={"business": "petr-biz-b"}).json()
        names_b = {item["name"] for cat in menu_b["categories"] for item in cat["items"]}
        assert "Biz B Secret Dish" in names_b
        assert "Biz A Secret Dish" not in names_b
    finally:
        _run(db.products.delete_many({"id": {"$in": ["PETR-PROD-A", "PETR-PROD-B"]}}))
        _cleanup_business("PETR-BIZ-A"); _cleanup_business("PETR-BIZ-B")


def test_public_menu_resolves_by_business_id_too_not_only_slug(client):
    _make_business("PETR-BIZ-C", "petr-biz-c", "Biz C")
    _run(db.products.insert_one({
        "id": "PETR-PROD-C", "name": "Biz C Dish", "category": "Mains",
        "price": 9.0, "businessId": "PETR-BIZ-C",
    }))
    try:
        menu = req(client, "GET", "/api/public/menu", params={"business": "PETR-BIZ-C"}).json()
        names = {item["name"] for cat in menu["categories"] for item in cat["items"]}
        assert "Biz C Dish" in names
    finally:
        _run(db.products.delete_many({"id": "PETR-PROD-C"}))
        _cleanup_business("PETR-BIZ-C")


def test_public_menu_unresolvable_slug_is_rejected(client):
    """An unresolvable ?business= must behave exactly like no param at all
    (the documented, safe fallback) — not 404, not 500, and specifically
    not "treat the raw string as a businessId anyway" (which would let a
    guest probe for real internal BIZ-xxxxxxxx ids by trial and error)."""
    r = req(client, "GET", "/api/public/menu", params={"business": "totally-made-up-slug-xyz"})
    assert r.status_code == 404


def test_anonymous_caller_cannot_use_tenant_header_to_target_a_business(client):
    """The specific attack this fix must not reintroduce: no ?business=
    given, but the caller sets X-Tenant-Id to a real business's id, hoping
    ActorContextMiddleware's actor-context fallback (built for a different,
    legitimate no-JWT-integration-caller case) leaks that business's menu.
    Must come back fully unscoped (today's pre-fix pooled behavior), never
    scoped to the header's target."""
    _make_business("PETR-BIZ-D", "petr-biz-d", "Biz D")
    _run(db.products.insert_one({
        "id": "PETR-PROD-D", "name": "Biz D Header Target Dish", "category": "Mains",
        "price": 5.0, "businessId": "PETR-BIZ-D",
    }))
    try:
        no_param = req(client, "GET", "/api/public/menu").json()
        spoofed = req(client, "GET", "/api/public/menu", headers={"X-Tenant-Id": "PETR-BIZ-D"}).json()
        assert no_param == spoofed, (
            "an anonymous caller's X-Tenant-Id header must never change what /public/menu returns"
        )
    finally:
        _run(db.products.delete_many({"id": "PETR-PROD-D"}))
        _cleanup_business("PETR-BIZ-D")


# ----------------------------------------------------------- /public/events

def test_public_events_scoped_by_business(client):
    _make_business("PETR-BIZ-E1", "petr-biz-e1", "Biz E1")
    _make_business("PETR-BIZ-E2", "petr-biz-e2", "Biz E2")
    _run(db.events.insert_one({
        "id": "PETR-EVT-1", "name": "Biz E1 Wine Night", "isActive": True, "businessId": "PETR-BIZ-E1",
    }))
    _run(db.events.insert_one({
        "id": "PETR-EVT-2", "name": "Biz E2 Trivia Night", "isActive": True, "businessId": "PETR-BIZ-E2",
    }))
    try:
        events_1 = req(client, "GET", "/api/public/events", params={"business": "petr-biz-e1"}).json()
        names_1 = {e["name"] for e in events_1}
        assert "Biz E1 Wine Night" in names_1
        assert "Biz E2 Trivia Night" not in names_1
    finally:
        _run(db.events.delete_many({"id": {"$in": ["PETR-EVT-1", "PETR-EVT-2"]}}))
        _cleanup_business("PETR-BIZ-E1"); _cleanup_business("PETR-BIZ-E2")


# ------------------------------------------------------------- /public/book

def test_public_book_stamps_the_resolved_business_and_scopes_experience_lookup(client):
    _make_business("PETR-BIZ-F", "petr-biz-f", "Biz F")
    try:
        r = req(client, "POST", "/api/public/book", json={
            "guestName": "Cross Tenant Test", "partySize": 2, "date": _future_date(), "time": "19:00",
            "business": "petr-biz-f",
        })
        assert r.status_code == 200, r.text[:300]
        res_id = r.json()["reservationId"]
        stored = _run(db.reservations.find_one({"id": res_id}, {"_id": 0}))
        assert stored["businessId"] == "PETR-BIZ-F"
    finally:
        _run(db.reservations.delete_many({"guestName": "Cross Tenant Test"}))
        _cleanup_business("PETR-BIZ-F")


# -------------------------------------------------------- /public/join-waitlist

def test_public_join_waitlist_position_is_scoped_per_business(client):
    """Regression guard for a correctness bug this fix could have
    introduced: once scoped, the "next position" computation must be
    relative to THIS business's own waiting list, not the pooled one —
    otherwise a business with zero of its own waiting guests could get
    told they're #47 because of every OTHER business's queue."""
    _make_business("PETR-BIZ-G", "petr-biz-g", "Biz G")
    try:
        r = req(client, "POST", "/api/public/join-waitlist", json={
            "guestName": "Waitlist Cross Tenant Test", "partySize": 2, "business": "petr-biz-g",
        })
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        assert body["position"] == 1, "first guest on a fresh business's waitlist must be position 1"
        stored = _run(db.waitlist.find_one({"id": body["id"]}, {"_id": 0}))
        assert stored["businessId"] == "PETR-BIZ-G"
    finally:
        _run(db.waitlist.delete_many({"guestName": "Waitlist Cross Tenant Test"}))
        _cleanup_business("PETR-BIZ-G")


# ------------------------------------- resolve_or_require_business_id (P2)

def test_public_book_refuses_when_ambiguous_between_multiple_businesses_and_no_business_given(client):
    """Task #64 of the tenant-ownership release-closure pass: /public/book
    used to silently create an untagged (businessId=None) reservation,
    checked against rules/capacity pooled across EVERY business, whenever
    ?business= was absent — operationally meaningless on any deployment
    with more than one business (whose tables/kitchen is actually being
    held?). Now refused (400) rather than guessed when more than one
    business exists and none was specified."""
    _make_business("PETR-BIZ-AMBIG-1", "petr-biz-ambig-1", "Ambig One")
    _make_business("PETR-BIZ-AMBIG-2", "petr-biz-ambig-2", "Ambig Two")
    try:
        r = req(client, "POST", "/api/public/book", json={
            "guestName": "Ambiguous Booking Test", "partySize": 2, "date": _future_date(), "time": "19:00",
        })
        assert r.status_code == 400, (
            f"a booking with no ?business= on a multi-business deployment must be refused, not pooled, got {r.status_code}: {r.text[:200]}"
        )
        leaked = _run(db.reservations.find_one({"guestName": "Ambiguous Booking Test"}))
        assert leaked is None, "a refused booking must never be created as an untagged row"
    finally:
        _run(db.reservations.delete_many({"guestName": "Ambiguous Booking Test"}))
        _cleanup_business("PETR-BIZ-AMBIG-1")
        _cleanup_business("PETR-BIZ-AMBIG-2")


def test_public_join_waitlist_refuses_when_ambiguous_between_multiple_businesses(client):
    _make_business("PETR-BIZ-AMBIG-3", "petr-biz-ambig-3", "Ambig Three")
    _make_business("PETR-BIZ-AMBIG-4", "petr-biz-ambig-4", "Ambig Four")
    try:
        r = req(client, "POST", "/api/public/join-waitlist", json={
            "guestName": "Ambiguous Waitlist Test", "partySize": 2,
        })
        assert r.status_code == 400, (
            f"a waitlist join with no ?business= on a multi-business deployment must be refused, not pooled, got {r.status_code}"
        )
        leaked = _run(db.waitlist.find_one({"guestName": "Ambiguous Waitlist Test"}))
        assert leaked is None
    finally:
        _run(db.waitlist.delete_many({"guestName": "Ambiguous Waitlist Test"}))
        _cleanup_business("PETR-BIZ-AMBIG-3")
        _cleanup_business("PETR-BIZ-AMBIG-4")


def test_public_book_auto_resolves_when_exactly_one_business_exists(client):
    """The single-tenant-deployment case must stay unaffected: with no
    ?business= given and exactly one business in the whole deployment,
    the booking auto-resolves to it rather than refusing or pooling."""
    from database import db as _db
    existing = _run(_db.businesses.find({}, {"_id": 0}).to_list(50))
    try:
        # Isolate to exactly one business for this test's own duration.
        _run(_db.businesses.delete_many({}))
        _make_business("PETR-BIZ-SOLE", "petr-biz-sole", "Sole Business")
        r = req(client, "POST", "/api/public/book", json={
            "guestName": "Sole Business Booking Test", "partySize": 2, "date": _future_date(), "time": "19:00",
        })
        assert r.status_code == 200, r.text[:300]
        res_id = r.json()["reservationId"]
        stored = _run(_db.reservations.find_one({"id": res_id}, {"_id": 0}))
        assert stored["businessId"] == "PETR-BIZ-SOLE"
    finally:
        _run(_db.reservations.delete_many({"guestName": "Sole Business Booking Test"}))
        _cleanup_business("PETR-BIZ-SOLE")
        for b in existing:
            _run(_db.businesses.insert_one(b))


# ----------------------------------------------------- table_ordering.py

def test_table_menu_scoped_by_business_does_not_leak_the_other_business(client):
    _make_business("PETR-BIZ-H1", "petr-biz-h1", "Biz H1")
    _make_business("PETR-BIZ-H2", "petr-biz-h2", "Biz H2")
    _run(db.products.insert_one({
        "id": "PETR-PROD-H1", "name": "Biz H1 Table Dish", "category": "Mains",
        "price": 8.0, "stock": 10, "businessId": "PETR-BIZ-H1",
    }))
    _run(db.products.insert_one({
        "id": "PETR-PROD-H2", "name": "Biz H2 Table Dish", "category": "Mains",
        "price": 9.0, "stock": 10, "businessId": "PETR-BIZ-H2",
    }))
    try:
        menu = req(client, "GET", "/api/table/ANY-TABLE-ID/menu", params={"business": "petr-biz-h1"}).json()
        names = {item["name"] for cat in menu["categories"] for item in cat["items"]}
        assert "Biz H1 Table Dish" in names
        assert "Biz H2 Table Dish" not in names
    finally:
        _run(db.products.delete_many({"id": {"$in": ["PETR-PROD-H1", "PETR-PROD-H2"]}}))
        _cleanup_business("PETR-BIZ-H1"); _cleanup_business("PETR-BIZ-H2")


def test_table_order_is_stamped_with_the_resolved_business_and_cant_use_another_businesss_product(client):
    _make_business("PETR-BIZ-I1", "petr-biz-i1", "Biz I1")
    _make_business("PETR-BIZ-I2", "petr-biz-i2", "Biz I2")
    _run(db.products.insert_one({
        "id": "PETR-PROD-I1", "name": "I1 Dish", "category": "Mains",
        "price": 12.0, "stock": 10, "businessId": "PETR-BIZ-I1",
    }))
    _run(db.products.insert_one({
        "id": "PETR-PROD-I2", "name": "I2 Dish", "category": "Mains",
        "price": 15.0, "stock": 10, "businessId": "PETR-BIZ-I2",
    }))
    try:
        # A guest scanning business I1's table must not be able to order
        # business I2's product just by knowing its productId.
        r = req(client, "POST", "/api/table/ANY-TABLE-ID/order", params={"business": "petr-biz-i1"}, json={
            "items": [{"productId": "PETR-PROD-I1", "quantity": 1}, {"productId": "PETR-PROD-I2", "quantity": 1}],
        })
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        item_names = {i["name"] for i in body["items"]}
        assert "I1 Dish" in item_names
        assert "I2 Dish" not in item_names, "a business I1 table order must not be able to include business I2's product"

        stored = _run(db.kitchen_orders.find_one({"id": body["orderId"]}, {"_id": 0}))
        assert stored["businessId"] == "PETR-BIZ-I1"
    finally:
        _run(db.kitchen_orders.delete_many({"tableId": "ANY-TABLE-ID", "businessId": "PETR-BIZ-I1"}))
        _run(db.products.delete_many({"id": {"$in": ["PETR-PROD-I1", "PETR-PROD-I2"]}}))
        _cleanup_business("PETR-BIZ-I1"); _cleanup_business("PETR-BIZ-I2")


def test_table_qr_codes_requires_auth_and_is_scoped_to_the_callers_own_business(client, owner_headers):
    anon = req(client, "GET", "/api/tables/qr-codes")
    assert anon.status_code == 401


def test_anonymous_table_menu_cannot_use_tenant_header_to_target_a_business(client):
    """Same spoofed-header attack as the /public/menu test above, for the
    table-QR path."""
    _make_business("PETR-BIZ-J", "petr-biz-j", "Biz J")
    _run(db.products.insert_one({
        "id": "PETR-PROD-J", "name": "Biz J Header Target Dish", "category": "Mains",
        "price": 5.0, "stock": 5, "businessId": "PETR-BIZ-J",
    }))
    try:
        no_param = req(client, "GET", "/api/table/ANY-TABLE-ID/menu").json()
        spoofed = req(client, "GET", "/api/table/ANY-TABLE-ID/menu", headers={"X-Tenant-Id": "PETR-BIZ-J"}).json()
        assert no_param == spoofed
    finally:
        _run(db.products.delete_many({"id": "PETR-PROD-J"}))
        _cleanup_business("PETR-BIZ-J")
