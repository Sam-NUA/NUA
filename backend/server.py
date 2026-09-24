from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path(__file__).parent / '.env')

from fastapi import FastAPI, APIRouter
from starlette.middleware.cors import CORSMiddleware
import logging
import os
import re
from typing import Optional

from database import client

from routes.products import router as products_router
from routes.stock_transfers import router as stock_transfers_router
from routes.appointments import router as appointments_router
from routes.transactions import router as transactions_router
from routes.customers import router as customers_router
from routes.identity import router as identity_router
from routes.reservations import router as reservations_router
from routes.kitchen import router as kitchen_router
from routes.coursing import router as coursing_router
from routes.analytics import router as analytics_router
from routes.settings import router as settings_router
from routes.loyalty import router as loyalty_router
from routes.public import router as public_router
from routes.table_ordering import router as table_ordering_router
from routes.integrations import router as integrations_router
from routes.auth import router as auth_router, seed_admin
from routes.ai_pantry import router as ai_pantry_router
from routes.multi_tenant import router as multi_tenant_router, seed_default_business
from routes.advanced_features import router as advanced_features_router
from routes.realtime import router as realtime_router
from routes.staff_management import router as staff_mgmt_router
from routes.awards import router as awards_router
from routes.bookings_inbox import router as bookings_inbox_router
from routes.channel_menus import router as channel_menus_router
from routes.social_media import router as social_media_router
from routes.menu_features import router as menu_features_router
from routes.enterprise_features import router as enterprise_router
from routes.gamification import router as gamification_router
from routes.reservation_features import router as reservation_features_router
from routes.booking_analytics import router as booking_analytics_router
from routes.items_system import router as items_system_router
from routes.v15_features import router as v15_router
from routes.loyalty_engine import router as loyalty_engine_router
from routes.loyalty_v2 import router as loyalty_v2_router
from routes.guest_session import router as guest_session_router
from routes.measured_inventory import router as measured_inventory_router
from routes.notifications import router as notifications_router
from routes.phase_ef import router as phase_ef_router
from routes.phase_ef_wave2 import router as phase_ef_wave2_router
from routes.v25_suite import router as v25_suite_router
from routes.licensing import router as licensing_router
from routes.ownership_migration import router as ownership_migration_router
from routes.v26_commerce import router as v26_commerce_router
from routes.online_orders import router as online_orders_router
from routes.inventory_accounting import router as inventory_accounting_router
from routes.super import router as super_router
from routes.temperature import router as temperature_router
from routes.table_courses import router as table_courses_router
from routes.finalize import router as finalize_router
from routes.payroll import router as payroll_router, _apply_persisted_wallet_credentials
from routes.commerce_v29 import router as commerce_v29_router
from routes.accounting import router as accounting_router
from routes.rules_engine import router as rules_engine_router
from routes.audit import router as audit_router
from routes.approvals import router as approvals_router
from routes.nua import router as nua_router
from routes.repo_sync import router as repo_sync_router
from routes.marketing_digest import router as marketing_digest_router
from routes.hq import router as hq_router
from routes.ops import router as ops_router
from routes.changelog import router as changelog_router
from routes.crypto_payments import router as crypto_payments_router
from routes.voice_calls import router as voice_calls_router
from routes.voice_inbound import router as voice_inbound_router
from routes.bill_split import router as bill_split_router
from middleware.license_middleware import LicenseEnforcementMiddleware
from middleware.actor_context import ActorContextMiddleware

app = FastAPI()

api_router = APIRouter(prefix="/api")

# Include all route modules
api_router.include_router(auth_router)
api_router.include_router(products_router)
api_router.include_router(stock_transfers_router)
api_router.include_router(appointments_router)
api_router.include_router(transactions_router)
api_router.include_router(customers_router)
api_router.include_router(identity_router)
api_router.include_router(reservations_router)
api_router.include_router(kitchen_router)
api_router.include_router(coursing_router)
api_router.include_router(analytics_router)
api_router.include_router(settings_router)
api_router.include_router(loyalty_router)
api_router.include_router(loyalty_v2_router)
api_router.include_router(guest_session_router)
api_router.include_router(measured_inventory_router)
api_router.include_router(notifications_router)
api_router.include_router(public_router)
api_router.include_router(table_ordering_router)
api_router.include_router(integrations_router)
api_router.include_router(ai_pantry_router)
api_router.include_router(advanced_features_router)  # Must be before multi_tenant to avoid /business/settings conflict
api_router.include_router(realtime_router)
api_router.include_router(staff_mgmt_router)
api_router.include_router(awards_router)
api_router.include_router(bookings_inbox_router)
api_router.include_router(channel_menus_router)
api_router.include_router(social_media_router)
api_router.include_router(menu_features_router)
api_router.include_router(enterprise_router)
api_router.include_router(gamification_router)
api_router.include_router(reservation_features_router)
api_router.include_router(booking_analytics_router)
api_router.include_router(items_system_router)
api_router.include_router(v15_router)
api_router.include_router(loyalty_engine_router)
api_router.include_router(phase_ef_router)
api_router.include_router(phase_ef_wave2_router)
api_router.include_router(v25_suite_router)
api_router.include_router(licensing_router)
api_router.include_router(ownership_migration_router)
api_router.include_router(v26_commerce_router)
api_router.include_router(online_orders_router)
api_router.include_router(inventory_accounting_router)
api_router.include_router(super_router)
api_router.include_router(temperature_router)
api_router.include_router(table_courses_router)
api_router.include_router(finalize_router)
api_router.include_router(payroll_router)
api_router.include_router(commerce_v29_router)
api_router.include_router(accounting_router)
api_router.include_router(rules_engine_router)
api_router.include_router(audit_router)
api_router.include_router(approvals_router)
api_router.include_router(nua_router)
api_router.include_router(repo_sync_router)
api_router.include_router(marketing_digest_router)
api_router.include_router(hq_router)
api_router.include_router(multi_tenant_router)
api_router.include_router(ops_router)
api_router.include_router(changelog_router)
api_router.include_router(crypto_payments_router)
api_router.include_router(voice_calls_router)
api_router.include_router(voice_inbound_router)
api_router.include_router(bill_split_router)

@api_router.get("/")
async def root():
    return {
        "name": "NUA API",
        "version": "5.0.0",
        "status": "Production Ready",
        "features": [
            "Staff Auth & RBAC", "AI Smart Pantry", "Member Portal & Vouchers",
            "Multi-Business Management", "Stripe Payments", "Table-Side QR Ordering",
            "18+ Hospitality Integrations", "Kitchen Display", "Reservations & Floor Plans",
            "Menu Engineering", "Demand Forecasting", "Automation Engine",
        ],
    }

from routes.booking_sync import router as booking_sync_router
api_router.include_router(booking_sync_router)
app.include_router(api_router)

# ============ Per-tenant rate limiter (lightweight in-memory) ============
from collections import defaultdict
from time import time
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

def _rate_limit_identity(request) -> str:
    """Prefer the authenticated user (from the Bearer token or session cookie)
    over raw IP — several client apps (POS, Staff app, Dashboard app) can
    legitimately share one venue's NAT'd IP, and keying on IP alone would let
    them starve each other's bucket. Falls back to IP for unauthenticated
    requests (e.g. login itself)."""
    token = None
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
    if not token:
        token = request.cookies.get("access_token")
    if token:
        try:
            import jwt, os
            payload = jwt.decode(token, os.environ["JWT_SECRET"], algorithms=["HS256"])
            sub = payload.get("sub")
            if sub:
                return f"user:{sub}"
        except Exception:
            pass
    ip = request.client.host if request.client else "?"
    return f"ip:{ip}"


# ═══════════════════════════════════════════════════════════════════════════
# Default-deny at the door.
#
# Auth used to be opt-in: an endpoint was protected only if whoever wrote it
# remembered a `Depends`. With ~280 GET routes that is a losing game, and it
# lost — a sweep found the customer list, the P&L, the command centre and the
# business settings (writable!) all answering with no credential at all.
#
# So the default is inverted here. Anything under /api/ needs a valid token
# unless it is on the list below, and the list is short because the genuinely
# public surface is small: the booking portal, the QR table menu, the online
# storefront, the member join page, login, and payment webhooks.
#
# This checks the token is *real* (signature, type, expiry) but not who it
# belongs to — the per-route Depends still do the user lookup and the role and
# permission checks. This layer only closes "no credential, or a forged one".
# ═══════════════════════════════════════════════════════════════════════════
PUBLIC_API_PREFIXES = (
    "/api/public/",              # booking portal: menu, slots, book, waitlist, events
    "/api/table/",               # QR table ordering: menu, place order, order status
    "/api/online/orders/track/", # order tracking by code, from the SMS link
    "/api/waitlist/track/",      # waitlist position tracking by code, same access model
    "/api/stripe/checkout/status/",
    # same "browser away and back" story as Stripe checkout status — two
    # prefixes because Coinbase Commerce doesn't echo the charge code back
    # on redirect, so the by-order lookup is a distinct path, not a suffix
    # of the by-charge-code one.
    "/api/crypto/checkout/status/", "/api/crypto/checkout/status-by-order/",
    # Self-service kiosk: add-to-cart, course, checkout, upsell — no staff
    # login exists on a kiosk terminal. Deliberately "session/" (trailing
    # slash) so this never matches GET /api/v25/kiosk/sessions (plural, no
    # trailing slash) — that one's the staff-facing "what's on every kiosk
    # right now" view and stays behind auth. Actually under /api/v25/kiosk/,
    # not /api/kiosk/ — the v25_suite router is mounted with prefix "/v25";
    # this list previously used the wrong path entirely (missing the /v25
    # segment), meaning EVERY kiosk endpoint 401'd for the guest kiosk client
    # they're meant to serve, on a terminal with no way to log in.
    "/api/v25/kiosk/session/",
    # Twilio voice webhooks — Twilio can't carry our JWT, so these are
    # authenticated instead by request-signature validation inside
    # routes/voice_calls.py (services/voice_calls.validate_signature), the
    # same trust model as the Coinbase webhook below uses HMAC for.
    "/api/voice/twiml/", "/api/voice/gather/", "/api/voice/status/",
    # Inbound-call gather turns only — trailing slash so this can never
    # match /api/voice/inbound/status, /config, /recent or /active (the
    # owner/staff-facing endpoints in routes/voice_inbound.py, which stay
    # behind the normal auth middleware). The bare POST /api/voice/inbound
    # webhook itself (no call_id suffix yet) is listed as an exact path in
    # PUBLIC_API_PATHS below instead, for the same reason — a prefix with
    # no trailing slash there would have also matched every one of those
    # staff-only sub-paths.
    "/api/voice/inbound/gather/",
)

PUBLIC_API_PATHS = {
    "/api/", "/api/health", "/api/healthz", "/api/ready",
    "/api/ops/device-status",     # login-screen peripheral status — counts/booleans only
    # Auth itself, plus the endpoints the login screen needs before there is a user.
    "/api/auth/login", "/api/auth/register", "/api/auth/logout", "/api/auth/refresh",
    "/api/auth/me",
    # A locked-out staff member has no session by definition — both steps of
    # self-service password recovery have to be reachable with no token.
    "/api/auth/forgot-password", "/api/auth/reset-password",
    # The second half of login: password passed, code still owed. It carries
    # its own short-lived challenge token in the body instead of a session
    # token, which this middleware doesn't know how to read — the endpoint
    # verifies that token itself.
    "/api/auth/2fa/challenge",
    # Staff PIN login — same "no token yet" story as /api/auth/login. This
    # was missing before and silently made PIN login unreachable in
    # production (every call 401'd here before the route's own PIN check
    # ever ran) — there was no test hitting it end-to-end to catch that.
    "/api/auth/pin-login", "/api/auth/pin-login/approve",
    "/api/business/theme",       # login-screen branding
    # The menu, as guests see it. /products strips cost/stock/sku for guests.
    "/api/products", "/api/categories", "/api/modifiers",
    "/api/online/categories", "/api/online/products", "/api/online/orders",
    "/api/online/orders/checkout",
    # Guest-facing voucher check (online ordering, table QR) — dry-run only,
    # deliberately returns nothing beyond a discount amount + label.
    "/api/vouchers/public-check",
    # Guest-facing loyalty portal — a customer checking their own points/tier
    # by phone, no staff login involved. Returns first name only, never the
    # full customer record.
    "/api/loyalty/v2/guest-lookup",
    "/api/loyalty/v2/guest-lookup/request-code",
    # Passwordless guest identity (services/guest_session.py) — same
    # unauthenticated-by-design posture as the loyalty guest lookup above,
    # generalized for booking/waitlist/ordering instead of loyalty-only.
    # The token itself, not this middleware, is what verifies the caller.
    "/api/guest/session/request-code",
    "/api/guest/session/verify",
    "/api/guest/session/me",
    # Self-service kiosk session creation — no sid exists yet, so this can't
    # be covered by the "/api/v25/kiosk/session/" prefix above.
    "/api/v25/kiosk/session",
    # Smart-substitution suggestions for an 86'd kiosk item — same unattended
    # guest surface as the rest of the kiosk endpoints above.
    "/api/v25/substitute",
    # Payment provider callbacks — signed by the provider, not by a user.
    # /api/webhook/stripe (POS/online-order Stripe checkout, integrations.py)
    # and /api/license/stripe/webhook (billing/subscription events,
    # licensing.py — that router is mounted with prefix "/license", so its
    # webhook is NOT at the bare /api/stripe/webhook this list previously
    # had; that entry matched nothing real — the actual path 401'd every
    # delivery Stripe ever sent for a billing event before it could even
    # reach signature verification, the same class of bug as the kiosk
    # path above).
    "/api/webhook/stripe", "/api/license/stripe/webhook",
    # Square Connect webhook — authenticated by its own HMAC signature
    # (services/connect/connectors/square.py verify_webhook), not a user token.
    "/api/webhooks/square",
    # Coinbase Commerce webhook — authenticated by its own HMAC signature
    # (services/coinbase_commerce.py verify_webhook_signature), not a user token.
    "/api/webhook/coinbase",
    # Twilio's very first inbound-call webhook — no call_id exists yet (that
    # only appears once routes/voice_inbound.py creates the voice_calls doc
    # and hands back a gather URL under /api/voice/inbound/gather/, which is
    # in PUBLIC_API_PREFIXES above instead). Authenticated by Twilio request-
    # signature validation inside the route itself, same as the other voice
    # webhooks. Exact path only — never widen this to a prefix, or every
    # owner/staff-facing /api/voice/inbound/* endpoint below it would also
    # bypass auth.
    "/api/voice/inbound",
    # A browser reporting its own crash — has to work from the login screen
    # and the guest ordering pages, neither of which carries a token.
    "/api/ops/client-errors",
    # Booking policy the guest booking portal needs to enforce BEFORE
    # confirming (large-booking size tiers, experience requirements) — a
    # guest on BookingPortal.jsx has no token, same as the /api/public/
    # prefix, but these two live outside that prefix. Non-sensitive: booking
    # window/capacity policy and the experience catalog are guest-relevant
    # information, not business-internal data (no costs, no other guests'
    # records). POST /api/booking/rules stays behind its own
    # Depends(require_owner) at the route level regardless of this
    # allowlist entry — that's an independent check the middleware doesn't
    # weaken by letting the request past this layer.
    "/api/booking/rules", "/api/booking/experiences",
}


def _is_public_api(path: str) -> bool:
    return path in PUBLIC_API_PATHS or path.startswith(PUBLIC_API_PREFIXES)


class RequireAuthMiddleware(BaseHTTPMiddleware):
    """Reject /api/ traffic that carries no valid token, before it reaches a route."""

    async def dispatch(self, request, call_next):
        # request.scope["path"], not request.url.path: starlette's Request.url
        # rebuilds a URL by string-concatenating the raw, unvalidated Host
        # header with the real path and reparsing it (PYSEC-2026-161 /
        # GHSA-86qp-5c8j-p5mr) — a Host header like "x/api/public" turns
        # request.url.path into "/api/public/api/users", which
        # _is_public_api() then waves through with no token check at all,
        # while FastAPI's actual routing (which dispatches on scope["path"]
        # directly, never touching Host) still sends the request to the
        # real, sensitive handler. Verified end-to-end against a route with
        # no route-level Depends() (GET/POST /api/users): the unmodified
        # request correctly 401s, the same request with that Host header
        # reaches routes/settings.py's get_users()/create_user() with zero
        # authentication. scope["path"] is what the router actually uses
        # and is not derived from any header, so it can't be spoofed this
        # way regardless of which starlette version is installed.
        path = request.scope["path"]
        if request.method == "OPTIONS" or not path.startswith("/api/"):
            return await call_next(request)
        if _is_public_api(path):
            return await call_next(request)

        token = None
        auth_header = request.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            token = auth_header[7:].strip()
        if not token:
            token = request.cookies.get("access_token")
        if not token:
            # EventSource cannot set headers, so the SSE stream passes its JWT
            # as a query parameter. Same token, verified the same way here.
            token = request.query_params.get("token")
        if not token:
            return JSONResponse(status_code=401, content={"detail": "Not authenticated"})

        try:
            import jwt
            payload = jwt.decode(token, os.environ["JWT_SECRET"], algorithms=["HS256"])
        except Exception:
            return JSONResponse(status_code=401, content={"detail": "Invalid or expired token"})
        # A refresh token must not be usable as an access token.
        if payload.get("type") not in (None, "access"):
            return JSONResponse(status_code=401, content={"detail": "Invalid token type"})
        return await call_next(request)


def _table_id_from_path(path: str) -> Optional[str]:
    m = re.match(r"^/api/table/([^/]+)", path)
    return m.group(1) if m else None


class RateLimitMiddleware(BaseHTTPMiddleware):
    """120 req/min per (tenant, identity) for authenticated staff traffic.

    A handful of paths get a stricter, IP-only override instead of the
    default — specifically ones that are unauthenticated by design and
    where the normal per-(tenant, identity) bucket is too generous. An
    anonymous caller hammering /vouchers/public-check to brute-force valid
    voucher codes has no `identity` beyond "unauthenticated", so without
    this override every guessed code would share the same generous 120/min
    room as every other anonymous request across the whole API.

    /api/public/* and /api/table/* used to be excluded from rate limiting
    entirely (found during the Trust Release final readiness audit) — an
    anonymous caller could hit booking/waitlist creation, menu reads, or
    table order placement at unlimited rate. PREFIX_OVERRIDES below covers
    the write/enumeration-risk paths specifically (booking, waitlist,
    voice webhooks) with their own stricter limits; everything else under
    those two prefixes now falls through to a real, if generous, default
    instead of no limit at all.
    """
    PATH_OVERRIDES = {
        "/api/vouchers/public-check": (10, 60),  # 10 req/min per IP
        # Same rationale as vouchers/public-check — an unauthenticated
        # caller with no identity beyond "some IP" shouldn't get the
        # generous default room to enumerate phone numbers.
        "/api/loyalty/v2/guest-lookup": (10, 60),  # 10 req/min per IP
        # Same tier — this one sends a real SMS per call, so it matters just
        # as much that a single IP can't be used to spam a phone number or
        # run up a Twilio bill.
        "/api/loyalty/v2/guest-lookup/request-code": (10, 60),  # 10 req/min per IP
        # Same posture, generalized guest identity (services/guest_session.py)
        # rather than loyalty-specific — still unauthenticated-by-design and
        # still sends a real SMS per request-code call.
        "/api/guest/session/request-code": (10, 60),  # 10 req/min per IP
        "/api/guest/session/verify": (10, 60),  # 10 req/min per IP
        # Generous relative to the endpoints above — a genuine error storm
        # (a bad deploy looping on render) can legitimately fire many reports
        # per second from one browser, and losing those is exactly the
        # moment this feature exists to cover. Still bounded so one runaway
        # tab can't grow client_error_log unbounded.
        "/api/ops/client-errors": (30, 60),  # 30 req/min per IP
    }
    # Ordered (prefix, limit, window) list for endpoints whose path carries
    # a variable segment (table_id, call_id) that PATH_OVERRIDES' exact-match
    # dict can't key on. First matching prefix wins, checked before the
    # generic public/table default.
    PREFIX_OVERRIDES = (
        # Booking/waitlist creation — a real, moderately-costly write on a
        # fully anonymous surface; same tier as the guest-lookup overrides
        # above.
        ("/api/public/book", 10, 60),
        ("/api/public/join-waitlist", 10, 60),
        # Twilio's own webhook-delivery IPs are a shared pool across every
        # customer's calls, not one IP per caller, and legitimate retry
        # behavior for a single call can itself fire several requests in
        # quick succession — generous enough that real multi-call traffic
        # and retries are never mistaken for abuse, still bounded against a
        # flood. The route's own CallSid-based dedup (routes/voice_inbound.py)
        # is what actually protects against a duplicate booking; this is
        # just a backstop against volume.
        ("/api/voice/inbound", 60, 60),
    )
    # Everything else under /api/public/* and /api/table/* (menu reads,
    # availability checks, order status polling, table order placement) —
    # generous enough for normal guest traffic (including several guests at
    # one venue sharing a WiFi NAT's IP, see the table_id keying below),
    # bounded against a scraping/enumeration flood.
    GUEST_DEFAULT_LIMIT = (60, 60)

    def __init__(self, app):
        super().__init__(app)
        self.buckets = defaultdict(list)
        self.limit = 120
        self.window = 60
        self._last_evict = time()

    async def dispatch(self, request, call_next):
        # scope["path"], not request.url.path — see RequireAuthMiddleware's
        # comment on why request.url.path is Host-header-spoofable.
        path = request.scope["path"]
        if not path.startswith("/api/"):
            return await call_next(request)

        override = self.PATH_OVERRIDES.get(path)
        prefix_override = next((o for o in self.PREFIX_OVERRIDES if path.startswith(o[0])), None)
        is_guest_surface = path.startswith("/api/public") or path.startswith("/api/table")

        if override:
            limit, window = override
            key = f"path:{path}:{request.client.host if request.client else 'unknown'}"
        elif prefix_override:
            _prefix, limit, window = prefix_override
            key = f"prefix:{_prefix}:{request.client.host if request.client else 'unknown'}"
        elif is_guest_surface:
            limit, window = self.GUEST_DEFAULT_LIMIT
            ip = request.client.host if request.client else "unknown"
            # Table-scoped, not just IP-scoped: several guests at one venue
            # commonly share a single WiFi NAT's public IP, and keying
            # purely on IP would let one table's QR-ordering activity
            # throttle every other table's guests at the same venue. A
            # resolved business (menu/booking reads carry ?business=) is
            # folded in for the same reason on the business-scoped paths.
            table_id = _table_id_from_path(path)
            business = request.query_params.get("business")
            key = f"guest:{ip}:{table_id or business or 'na'}"
        else:
            limit, window = self.limit, self.window
            tenant = request.headers.get("X-Tenant-Id", "default")
            identity = _rate_limit_identity(request)
            key = f"{tenant}:{identity}"
        now = time()
        # Evict idle clients every 5 min so the bucket dict can't grow unbounded
        if now - self._last_evict > 300:
            self._last_evict = now
            stale = [k for k, ts in self.buckets.items() if not ts or now - ts[-1] > self.window]
            for k in stale:
                del self.buckets[k]
        self.buckets[key] = [t for t in self.buckets[key] if now - t < window]
        if len(self.buckets[key]) >= limit:
            return JSONResponse(status_code=429, content={"detail": f"Rate limit exceeded — {limit} req/{window}s"})
        self.buckets[key].append(now)
        return await call_next(request)

# Added before RateLimit so RateLimit ends up the outer of the two: an
# unauthenticated flood is still rate-limited rather than each request paying
# for a JWT verification.
app.add_middleware(RequireAuthMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(LicenseEnforcementMiddleware)
app.add_middleware(ActorContextMiddleware)


# ═════════════════════════════════════════════════════════════════════════
# /api/ash/* → /api/nua/* alias (backwards-compat shim after Ash → NUA rebrand)
# ═════════════════════════════════════════════════════════════════════════
class NuaAliasMiddleware(BaseHTTPMiddleware):
    """Rewrite /api/ash/... to /api/nua/... so old tests keep working after
    the routes were renamed to the /nua namespace."""
    async def dispatch(self, request, call_next):
        # scope["path"], not request.url.path — see RequireAuthMiddleware's
        # comment. Beyond just being unreliable here, request.url.path would
        # let a crafted Host header make this middleware rewrite
        # scope["path"] to an attacker-chosen value (this middleware is the
        # outermost layer, so that rewrite would reach every middleware and
        # route after it) instead of only ever touching a genuine /api/ash/*
        # request.
        p = request.scope["path"]
        if p.startswith("/api/ash/") or p == "/api/ash":
            new_path = "/api/nua/" + p[len("/api/ash/"):] if p != "/api/ash" else "/api/nua"
            request.scope["path"] = new_path
            request.scope["raw_path"] = new_path.encode()
        return await call_next(request)


app.add_middleware(NuaAliasMiddleware)

# CORS: set FRONTEND_URL (comma-separated for multiple origins) in production.
# With explicit origins we allow credentialed (cookie) requests; without it we
# fall back to a wildcard WITHOUT credentials — Bearer-token auth still works,
# but any-origin-with-cookies (a CSRF vector) does not.
frontend_url = os.environ.get("FRONTEND_URL", "").strip()
if frontend_url:
    cors_origins = [o.strip().rstrip("/") for o in frontend_url.split(",") if o.strip()]
    cors_origins += ["http://localhost:3000", "http://127.0.0.1:3000"]
    cors_credentials = True
else:
    cors_origins = ["*"]
    cors_credentials = False
app.add_middleware(
    CORSMiddleware,
    allow_credentials=cors_credentials,
    allow_origins=cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
    # Custom headers the SPA reads (e.g. AI fallback flag on booking inbox).
    expose_headers=["x-ai-parsed-fallback"],
)

# Outermost of all: added last, so it wraps everything else (CORS, rate
# limiting, the auth gate) and logs — and can catch an unhandled exception
# from — every request that reaches this process, not just the ones that get
# as far as a route handler.
from services.observability import ObservabilityMiddleware
app.add_middleware(ObservabilityMiddleware)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

@app.on_event("startup")
async def startup():
    from services import booking_sync
    if os.environ.get("NUA_BOOKINGS_API_URL"):
        await booking_sync.start_worker()
    await seed_admin()
    await seed_default_business()
    # Seed 5 demo customers + reservations/transactions/feedback (idempotent).
    try:
        from seeds.seed_customers import seed_demo_customers
        result = await seed_demo_customers()
        if result.get("seeded"):
            logger.info("Seeded %s demo customers", result.get("count"))
    except Exception as exc:
        logger.warning("Customer seed skipped: %s", exc)
    # Seed the What's New feed (idempotent).
    try:
        from seeds.seed_changelog import seed_changelog
        cl_result = await seed_changelog()
        if cl_result.get("seeded"):
            logger.info("Seeded %s changelog entries", cl_result.get("count"))
    except Exception as exc:
        logger.warning("Changelog seed skipped: %s", exc)
    logger.info("Admin seeded, default business created")
    # Preload persisted wallet credentials into process env
    try:
        await _apply_persisted_wallet_credentials()
    except Exception as exc:
        logger.warning("Wallet credentials preload skipped: %s", exc)
    # Seed Enterprise Chart of Accounts for the default business (idempotent).
    # Explicit business_id="default": at startup there is no request/actor
    # context to default from, and an untagged chart of accounts would be
    # treated as "visible to every business" by tenant_scope_filter's safe
    # default — defeating the whole point of accounts being scoped per
    # business. Other businesses seed their own via POST /accounting/seed.
    try:
        from services.accounting_service import seed_chart_of_accounts
        r = await seed_chart_of_accounts(business_id="default")
        if r.get("seeded"):
            logger.info("Chart of Accounts seeded: %s new accounts", r["seeded"])
    except Exception as exc:
        logger.warning("COA seed skipped: %s", exc)
    # Seed alcohol catalog + measured stock (idempotent)
    try:
        from services.alcohol_seeder import seed_alcohol_catalog
        r = await seed_alcohol_catalog(business_id="default")
        if r.get("categoriesInserted") or r.get("productsInserted"):
            logger.info("Alcohol catalog seeded: +%s categories, +%s products, +%s stock-units",
                          r["categoriesInserted"], r["productsInserted"], r["stockUnitsInserted"])
    except Exception as exc:
        logger.warning("Alcohol seed skipped: %s", exc)
    # Start Ash background scheduler
    try:
        from services.nua_scheduler import start_scheduler
        start_scheduler()
    except Exception as exc:
        logger.warning("Ash scheduler failed to start: %s", exc)
    # Analytics filters the course-event trail on time, and the trail needs a
    # TTL so it can't grow forever.
    try:
        from services.course_events import ensure_indexes
        await ensure_indexes()
    except Exception as exc:
        logger.warning("Course event indexes failed: %s", exc)
    # Course timing rules need minute-level granularity, so they get their own
    # loop rather than riding the hourly Ash scheduler.
    try:
        from services.coursing_scheduler import start_scheduler as start_coursing
        start_coursing()
    except Exception as exc:
        logger.warning("Coursing scheduler failed to start: %s", exc)
    # Daily GitHub auto-sync — see services/repo_sync_scheduler.py.
    # Polls every 30 min; performs one fetch+merge inside the target hour in
    # the configured timezone (default: 04:00 Australia/Sydney).
    # Disable with REPO_SYNC_ENABLED=false.
    try:
        from services.repo_sync_scheduler import start_scheduler as start_repo_sync
        start_repo_sync()
    except Exception as exc:
        logger.warning("Repo-sync scheduler failed to start: %s", exc)
    # Daily automatic backup restore-drill — catches a silently-broken
    # backup before the day it's actually needed.
    try:
        from services.backup_scheduler import start_scheduler as start_backup_drills
        start_backup_drills()
    except Exception as exc:
        logger.warning("Backup drill scheduler failed to start: %s", exc)
    # Burned TOTP codes and trusted devices both expire on their own.
    try:
        from services.two_factor import ensure_indexes as ensure_2fa_indexes
        await ensure_2fa_indexes()
    except Exception as exc:
        logger.warning("2FA indexes failed: %s", exc)
    # The high-traffic collections (transactions, kitchen orders, customers,
    # products) get indexes on the fields every dashboard and POS screen
    # actually filters or sorts by — see services/db_indexes.py for why.
    try:
        from services.db_indexes import ensure_indexes as ensure_core_indexes
        await ensure_core_indexes()
    except Exception as exc:
        logger.warning("Core indexes failed: %s", exc)
    # Captured errors expire on their own after 30 days.
    try:
        from services.observability import ensure_indexes as ensure_observability_indexes
        await ensure_observability_indexes()
    except Exception as exc:
        logger.warning("Observability indexes failed: %s", exc)
    # Ephemeral collections (kiosk carts, notifications, login lockouts)
    # expire on their own too — see services/retention.py for what's
    # deliberately NOT on this list (transactions, audit, BAS/GST).
    try:
        from services.retention import ensure_indexes as ensure_retention_indexes
        await ensure_retention_indexes()
    except Exception as exc:
        logger.warning("Retention indexes failed: %s", exc)

@app.on_event("shutdown")
async def shutdown_db_client():
    from services import booking_sync
    await booking_sync.stop_worker()
    try:
        from services.nua_scheduler import stop_scheduler
        stop_scheduler()
    except Exception:
        pass
    try:
        from services.coursing_scheduler import stop_scheduler as stop_coursing
        stop_coursing()
    except Exception:
        pass
    try:
        from services.repo_sync_scheduler import stop_scheduler as stop_repo_sync
        stop_repo_sync()
    except Exception:
        pass
    try:
        from services.backup_scheduler import stop_scheduler as stop_backup_drills
        stop_backup_drills()
    except Exception:
        pass
    client.close()
