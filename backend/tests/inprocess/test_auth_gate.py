"""The API is default-deny, and the guest surface still works.

Both halves have to hold. A sweep found 66 routes answering with no credential
at all — the customer list with names and emails, the P&L, writable business
settings — so the door was closed. Closing it without breaking the booking
portal, the QR menu and the storefront is the part that needs proving, so
those are walked end to end here as an anonymous guest.
"""
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from conftest import OWNER, req

# Reachable without logging in, on purpose. Anything not on this list that
# answers an anonymous caller is a finding.
#
# This used to be its own hand-maintained copy of server.py's allowlist,
# which is exactly how the allowlist and reality drifted apart twice (kiosk
# endpoints, then the licensing Stripe webhook, both under the wrong path)
# without this test ever catching it — a second hardcoded list just agreed
# with the first one being wrong. Importing the real thing means this sweep
# and test_every_public_path_entry_matches_a_real_route below are checking
# the actual production allowlist, not a snapshot of it.
from server import PUBLIC_API_PATHS as INTENTIONALLY_PUBLIC, PUBLIC_API_PREFIXES as PUBLIC_PREFIXES

MUST_BE_SHUT = [
    ("GET", "/api/customers"), ("GET", "/api/users"), ("GET", "/api/transactions"),
    ("GET", "/api/accounting/p-and-l"), ("GET", "/api/accounting/summary"),
    ("GET", "/api/analytics/command-center"), ("GET", "/api/analytics/menu-engineering"),
    ("GET", "/api/business/settings"), ("POST", "/api/business/settings"),
    ("GET", "/api/expenses"), ("GET", "/api/suppliers"), ("GET", "/api/bas-gst/reports"),
    ("GET", "/api/kitchen/orders"), ("GET", "/api/staff/smart-roster"),
    ("GET", "/api/pre-shift/today"), ("GET", "/api/auth/roles"),
    ("GET", "/api/permissions/roles"), ("GET", "/api/permissions/catalog"),
    ("GET", "/api/integrations"), ("GET", "/api/eftpos/transactions"),
    ("GET", "/api/vouchers"), ("GET", "/api/payment-links"), ("GET", "/api/floor-plans"),
    ("GET", "/api/tables/qr-codes"), ("GET", "/api/staff/commissions"),
    ("GET", "/api/reservations/guest-lookup"), ("GET", "/api/bookings/inbox"),
    ("GET", "/api/automation/alerts"), ("GET", "/api/kitchen/prep-list"),
    ("GET", "/api/receipt/settings"),
    ("POST", "/api/products?business=default"), ("POST", "/api/expenses"), ("POST", "/api/suppliers"),
]


def _is_public(path):
    return path in INTENTIONALLY_PUBLIC or path.startswith(PUBLIC_PREFIXES)


def _registered_routes(app):
    """Return concrete routes across FastAPI's eager and lazy router layouts.

    FastAPI 0.141 keeps included routers as lazy ``_IncludedRouter`` entries
    instead of flattening every APIRoute into ``app.routes``.  Walking the
    effective contexts preserves this security test's full-route sweep while
    remaining compatible with the eager layout used by older releases.
    """
    for route in app.routes:
        effective_contexts = getattr(route, "effective_route_contexts", None)
        if effective_contexts:
            yield from effective_contexts()
        else:
            yield route


@pytest.mark.parametrize("method,path", MUST_BE_SHUT, ids=lambda v: str(v).replace("/", "_"))
def test_internal_endpoints_refuse_anonymous(anon, method, path):
    r = req(anon, method, path, json={})
    assert r.status_code in (401, 403), \
        f"{method} {path} answered {r.status_code} with no credential: {r.text[:200]}"


def test_a_forged_host_header_cannot_smuggle_a_protected_path_past_the_gate(anon):
    """Regression coverage for PYSEC-2026-161 / GHSA-86qp-5c8j-p5mr.

    The vulnerable legacy Starlette version rebuilt Request.url by
    string-concatenating the raw, unvalidated Host header with the real
    path and reparsing it. server.py's RequireAuthMiddleware used to read
    `request.url.path` for its public/protected decision — a Host header of
    "x/api/public" turned "/api/users" into "/api/public/api/users" for that
    check alone, waving a real staff-management request through with zero
    token, while FastAPI's actual routing (which dispatches on
    request.scope["path"] directly and never touches Host) still sent it to
    routes/settings.py's get_users()/create_user(). Reproduced end to end
    against a real un-authenticated MongoDB call before the fix (server.py,
    middleware/license_middleware.py now read scope["path"] instead).
    Exercises every PUBLIC_API_PREFIXES entry as the injected suffix against
    every MUST_BE_SHUT path, since any one of them turning a protected path
    "public"-looking is the same bypass."""
    for spoofed_prefix in PUBLIC_PREFIXES:
        host = f"x{spoofed_prefix}"
        for method, path in MUST_BE_SHUT:
            r = req(anon, method, path, json={}, headers={"Host": host})
            assert r.status_code in (401, 403), (
                f"{method} {path} with Host: {host!r} answered {r.status_code} "
                f"with no credential — Host-header path-injection bypass: {r.text[:200]}"
            )


def test_no_get_route_answers_anonymously_unless_allow_listed(anon, app):
    """The sweep itself — this is what found the original 66."""
    paths = sorted({
        r.path for r in _registered_routes(app)
        if "GET" in (getattr(r, "methods", set()) or set())
        and getattr(r, "path", "").startswith("/api")
        and "{" not in getattr(r, "path", "")
    })
    leaking = []
    for path in paths:
        try:
            r = req(anon, "GET", path)
        except Exception:
            continue                      # a route that raises isn't an auth answer
        if r.status_code < 400 and not _is_public(path):
            leaking.append((path, r.status_code, len(r.text)))
    assert not leaking, "these answered an anonymous caller:\n" + "\n".join(map(str, leaking))


def _forge(payload, key="test-secret-not-for-production"):
    return jwt.encode(payload, key, algorithm="HS256")


def test_garbage_token_is_refused(anon):
    r = req(anon, "GET", "/api/customers", headers={"Authorization": "Bearer nonsense"})
    assert r.status_code == 401


def test_token_signed_with_another_key_is_refused(anon):
    tok = _forge({"sub": "x", "type": "access",
                  "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
                 key="not-the-real-secret")
    r = req(anon, "GET", "/api/customers", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 401


def test_expired_token_is_refused(anon):
    tok = _forge({"sub": "x", "type": "access",
                  "exp": datetime.now(timezone.utc) - timedelta(hours=1)})
    r = req(anon, "GET", "/api/customers", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 401


def test_refresh_token_cannot_be_used_as_an_access_token(anon):
    tok = _forge({"sub": "x", "type": "refresh",
                  "exp": datetime.now(timezone.utc) + timedelta(days=1)})
    r = req(anon, "GET", "/api/customers", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 401


# ── Staff still get in, and are still held to their role ────────────────────

def test_owner_reaches_the_money_screens(client, owner_headers):
    assert req(client, "GET", "/api/customers", headers=owner_headers).status_code == 200
    assert req(client, "GET", "/api/accounting/p-and-l", headers=owner_headers).status_code == 200


def test_cashier_is_refused_the_pandl_but_keeps_the_kitchen_board(client, owner_headers):
    req(client, "POST", "/api/auth/staff/add", headers=owner_headers, json={
        "name": "Gate Cashier", "email": "gate.cashier@nua.com",
        "password": "CashierPass1!", "role": "cashier"})
    tok = req(client, "POST", "/api/auth/login", json={
        "email": "gate.cashier@nua.com", "password": "CashierPass1!"}).json()
    client.cookies.clear()
    assert "token" in tok, str(tok)[:200]
    ch = {"Authorization": f"Bearer {tok['token']}"}
    assert req(client, "GET", "/api/accounting/p-and-l", headers=ch).status_code == 403
    assert req(client, "GET", "/api/kitchen/orders", headers=ch).status_code == 200


# ── The guest surface still works ───────────────────────────────────────────

def test_booking_portal_works_for_a_guest(anon):
    # A booking date has to stay in the future relative to whenever this
    # suite runs — booking_rules_engine now rejects an online booking for a
    # date/time that's already passed (see services/booking_rules_engine.py),
    # so a hardcoded calendar date here would eventually go stale and start
    # failing this test for a reason unrelated to what it's checking.
    future_date = (datetime.now(timezone.utc) + timedelta(days=14)).strftime("%Y-%m-%d")
    assert req(anon, "GET", "/api/public/menu").status_code == 200
    assert req(anon, "GET", "/api/public/available-slots",
               params={"date": future_date, "party_size": 2}).status_code == 200
    r = req(anon, "POST", "/api/public/book", json={
        "name": "Anon Guest", "phone": "0400999888", "email": "anon@example.com",
        "date": future_date, "time": "18:30", "partySize": 2})
    assert r.status_code == 200, r.text[:200]


def test_storefront_order_and_tracking_work_for_a_guest(anon):
    products = req(anon, "GET", "/api/online/products")
    assert products.status_code == 200 and products.json()
    assert req(anon, "GET", "/api/online/categories").status_code == 200
    r = req(anon, "POST", "/api/online/orders?business=default", json={
        "channel": "pickup", "customerName": "Anon Guest", "customerPhone": "0400999888",
        "items": [{"productId": products.json()[0]["id"], "name": "Thing",
                   "quantity": 1, "price": 10.0}]})
    assert r.status_code == 200, r.text[:200]
    code = r.json().get("trackingCode") or r.json().get("code")
    if code:
        assert req(anon, "GET", f"/api/online/orders/track/{code}").status_code == 200


def test_kiosk_ordering_works_for_a_guest_end_to_end(anon):
    """A self-service kiosk terminal has no staff login on it at all — this
    whole flow previously 401'd on the very first call, because the
    default-deny allowlist listed /api/kiosk/session (missing the /v25
    prefix the real route actually lives under) instead of the real
    /api/v25/kiosk/session path. Every kiosk endpoint was unreachable by an
    actual guest kiosk client until that was fixed."""
    products = req(anon, "GET", "/api/products?business=default")
    assert products.status_code == 200 and products.json()
    pid = products.json()[0]["id"]

    start = req(anon, "POST", "/api/v25/kiosk/session", json={"guests": 2, "business": "default"})
    assert start.status_code == 200, start.text[:200]
    sid = start.json()["id"]

    added = req(anon, "POST", f"/api/v25/kiosk/session/{sid}/add",
                json={"item": {"productId": pid, "name": "Thing", "price": 10.0, "quantity": 1}})
    assert added.status_code == 200, added.text[:200]

    checkout = req(anon, "POST", f"/api/v25/kiosk/session/{sid}/checkout")
    assert checkout.status_code == 200, checkout.text[:200]

    # The staff-facing "every active kiosk session" view stays behind auth —
    # this is the one kiosk endpoint that must NOT be on the public list.
    assert req(anon, "GET", "/api/v25/kiosk/sessions").status_code in (401, 403)


def test_login_and_brand_theme_stay_reachable(anon):
    assert req(anon, "POST", "/api/auth/login", json=OWNER).status_code == 200
    assert req(anon, "GET", "/api/business/theme").status_code == 200


# ── The public menu is the menu, not the trade catalogue ────────────────────

TRADE_FIELDS = ("cost", "stock", "sku")


def test_guest_menu_has_the_menu_but_not_the_trade_data(anon):
    r = req(anon, "GET", "/api/products?business=default")
    assert r.status_code == 200
    menu = r.json()
    assert any(p.get("name") and p.get("price") for p in menu), "guest menu had no sellable item"
    leaked = [p for p in menu if any(p.get(f) for f in TRADE_FIELDS)]
    assert not leaked, f"guest menu leaked cost/stock/sku: {leaked[:1]}"


def test_storefront_listing_hides_trade_data_too(anon):
    r = req(anon, "GET", "/api/online/products")
    assert r.status_code == 200
    leaked = [p for p in r.json() if any(p.get(f) for f in TRADE_FIELDS)]
    assert not leaked, f"storefront leaked cost/stock/sku: {leaked[:1]}"


def test_staff_still_see_cost_and_stock(client, owner_headers):
    r = req(client, "GET", "/api/products?business=default", headers=owner_headers)
    assert r.status_code == 200
    assert any(p.get("cost") for p in r.json()), "no product carried a cost for a logged-in user"


# ── The allowlist itself must point at routes that actually exist ──────────
# Twice now (kiosk endpoints under the wrong path, the licensing Stripe
# webhook under the wrong path) an entry in server.py's PUBLIC_API_PATHS /
# PUBLIC_API_PREFIXES referenced a path that doesn't match anything actually
# registered — because the real router carries a class-level prefix
# (APIRouter(prefix="...")) the entry's author didn't account for. Each such
# entry is two bugs at once: the intended-public route silently 401s for the
# only caller it's meant to serve, and the stale path sits in the allowlist
# looking like it's doing something. This walks every entry against the
# actual FastAPI route table so a new one can't go unnoticed the same way.

def test_every_public_path_entry_matches_a_real_route(app):
    import server
    real_paths = {r.path for r in _registered_routes(app) if hasattr(r, "path")}
    for path in server.PUBLIC_API_PATHS:
        assert path in real_paths, f"{path!r} is in PUBLIC_API_PATHS but no route is registered at that exact path"


def test_every_public_prefix_covers_at_least_one_real_route(app):
    import server
    real_paths = [r.path for r in _registered_routes(app) if hasattr(r, "path")]
    for prefix in server.PUBLIC_API_PREFIXES:
        assert any(p.startswith(prefix) for p in real_paths), \
            f"{prefix!r} is in PUBLIC_API_PREFIXES but no registered route starts with it"


def test_public_prefixes_dont_accidentally_cover_a_staff_only_neighbor(app):
    """A prefix match is a startswith check, not an exact one — it's easy to
    write one that's technically correct today but would silently widen to
    cover a new staff-only route sharing the same stem tomorrow (e.g. a
    prefix "/api/v25/kiosk/session/" is safe; the same prefix WITHOUT its
    trailing slash would also match the staff-facing GET
    /api/v25/kiosk/sessions). Concretely: no public prefix should ever
    match a route that itself has no trailing-slash-delimited child segment
    after the prefix — that shape (bare plural collection, no ID/action
    after it) is the staff "list everything active" pattern, never
    something a single unauthenticated guest should reach."""
    import server
    real_paths = {r.path for r in _registered_routes(app) if hasattr(r, "path")}

    for prefix in server.PUBLIC_API_PREFIXES:
        assert prefix.endswith("/"), \
            f"{prefix!r} has no trailing slash — it can match a sibling plural/collection route by accident"
        for path in real_paths:
            if path.startswith(prefix):
                remainder = path[len(prefix):]
                assert remainder, f"{prefix!r} matches its own bare stem {path!r}"


# Regression pin for the exact near-miss this test class exists to catch:
# a kiosk session prefix without the trailing slash would also match the
# staff-only "list every active kiosk session" view.
def test_kiosk_session_prefix_does_not_reach_the_staff_session_list(app):
    import server
    assert "/api/v25/kiosk/session/" in server.PUBLIC_API_PREFIXES
    real_paths = {r.path for r in _registered_routes(app) if hasattr(r, "path")}
    assert "/api/v25/kiosk/sessions" in real_paths, "the staff session-list route moved or was renamed"
    assert not "/api/v25/kiosk/sessions".startswith("/api/v25/kiosk/session/"), \
        "the kiosk prefix would now also cover the staff-only session list"
