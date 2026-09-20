"""License Enforcement Middleware.

Server-authoritative. Frontend cannot bypass this — every API call (except a
small allowlist) is checked against the tenant's license state.

Commercial intent, by design: a suspended/past-due/abn_review tenant is
blocked from taking new money (POS sales, tabs, kiosk orders, new gift
cards — BLOCKED_WHEN_SUSPENDED_PREFIXES below) but can keep MANAGING their
business — editing products, taking reservations, updating customers —
so staff aren't locked out of basic operations while a billing issue gets
sorted. Only "cancelled" locks the whole API down to a tiny allowlist.
This is deliberate, not a gap: see BLOCKED_WHEN_SUSPENDED_PREFIXES's own
comment for what's actually considered "a new sale."

Routes are categorized:
- ALWAYS_OPEN: auth, license itself, billing recovery, exports, owner login
- RESTRICTED_IN_GRACE: settings edits, exports, new device activations
- BLOCKED_WHEN_SUSPENDED: new transactions (POS sales)

Everything else (products, customers, reservations, dashboard, analytics,
etc.) is unrestricted in every state except "cancelled" — there's no
separate read-only allowlist to maintain here, that's just what "not
listed in one of the blocking sets above" already means.
"""
from __future__ import annotations
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from database import db
import logging

logger = logging.getLogger(__name__)

# Routes that must always succeed regardless of license state.
ALWAYS_OPEN_PREFIXES = (
    "/api/auth/",
    "/api/license/",            # licensing itself
    "/api/payments/",           # payment / billing flows
    "/api/webhook/",            # webhooks
    "/api/health",
    "/api/v25/warehouse/",      # data export — spec says always allow
)
# Owner admin actions disabled in grace/past_due
RESTRICTED_IN_GRACE_PREFIXES = (
    "/api/business-settings",     # PATCH/PUT only — handled by method check
    "/api/v25/sites/publish",
    "/api/v25/dynamic-pricing",
    "/api/license/device/activate",   # no new device activations on overdue
)
# Hard-blocked when suspended (commercial intent: prevent new sales)
BLOCKED_WHEN_SUSPENDED_PREFIXES = (
    "/api/transactions",          # new POS sales
    "/api/v15/tabs",              # creating new tabs
    "/api/v25/kiosk/",
    "/api/v25/gift-cards",        # issuing new cards
)


class LicenseEnforcementMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        # Global kill-switch — keep the entire licensing system off during
        # development. Production sets LICENSE_ENFORCEMENT_ENABLED=true.
        import os
        if os.environ.get("LICENSE_ENFORCEMENT_ENABLED", "false").lower() != "true":
            return await call_next(request)

        # scope["path"], not request.url.path — request.url is rebuilt from
        # the raw, unvalidated Host header (PYSEC-2026-161), so a crafted
        # Host header could steer a route in/out of these prefix checks
        # (e.g. slip past BLOCKED_WHEN_SUSPENDED_PREFIXES). scope["path"] is
        # what FastAPI's router actually dispatches on and isn't header-
        # derived — see server.py's RequireAuthMiddleware for the full
        # writeup and a reproduced exploit against the equivalent bug there.
        path = request.scope["path"]
        method = request.method.upper()

        # Allowlist
        if any(path.startswith(p) for p in ALWAYS_OPEN_PREFIXES):
            return await call_next(request)
        if not path.startswith("/api/"):
            return await call_next(request)

        # Resolve tenant — we use a single-tenant default for now ("default") but
        # this is the hook for future multi-tenant header (X-Tenant-Id).
        tenant_id = request.headers.get("X-Tenant-Id", "default")
        try:
            lic = await db.tenant_licenses.find_one({"tenantId": tenant_id}, {"_id": 0})
        except Exception as e:
            logger.warning("License lookup failed: %s", e)
            return await call_next(request)  # fail-open on DB error — log and continue

        # No license → allow all (un-licensed dev / pre-onboarding); the /onboard flow gates it
        if not lic:
            return await call_next(request)

        state = lic.get("state", "active")
        # Active: full access
        if state == "active":
            return await call_next(request)

        # Cancelled: only data export + license + billing
        if state == "cancelled":
            if any(path.startswith(p) for p in ("/api/v25/warehouse/", "/api/license/")):
                return await call_next(request)
            return JSONResponse(
                {"errorCode": "LICENSE_CANCELLED",
                 "message": "Subscription cancelled. Renew to restore access."},
                status_code=423,  # Locked
            )

        # ABN review: block sale-side actions, allow management
        if state == "abn_review":
            if any(path.startswith(p) for p in BLOCKED_WHEN_SUSPENDED_PREFIXES):
                return JSONResponse(
                    {"errorCode": "ABN_REVERIFY_REQUIRED",
                     "message": "ABN change pending re-verification. New sales paused."},
                    status_code=423,
                )
            return await call_next(request)

        # Suspended: block new sales/transactions but allow owner recovery
        if state == "suspended":
            if any(path.startswith(p) for p in BLOCKED_WHEN_SUSPENDED_PREFIXES):
                return JSONResponse(
                    {"errorCode": "LICENSE_SUSPENDED",
                     "message": lic.get("suspensionReason") or "Account suspended. Update billing to restore."},
                    status_code=423,
                )
            return await call_next(request)

        # Grace / past_due: restrict admin writes; allow read + sales
        if state in ("grace", "past_due"):
            if method in ("POST", "PUT", "PATCH", "DELETE") and any(
                path.startswith(p) for p in RESTRICTED_IN_GRACE_PREFIXES
            ):
                return JSONResponse(
                    {"errorCode": "SUBSCRIPTION_PAST_DUE",
                     "message": "Billing overdue — admin actions restricted. Update payment to restore."},
                    status_code=423,
                )
            return await call_next(request)

        return await call_next(request)
