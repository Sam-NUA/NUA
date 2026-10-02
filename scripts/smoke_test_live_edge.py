#!/usr/bin/env python3
"""Live two-tenant / role / payment-sandbox smoke test — run against a real
deployed edge (any BASE_URL that answers HTTP, not the in-process mongomock
suite tests/inprocess/ already cover). This is the check
docs/DEPLOYMENT_READINESS.md's release order (step 6) asks for before any
production promotion: "run login, role/tenant, booking, checkout and
receiver smoke flows through the actual edge using sandbox providers."

Usage:
    SMOKE_BASE_URL=https://<your-vercel-url> \
    SMOKE_OWNER_EMAIL=owner@nua.com SMOKE_OWNER_PASSWORD=... \
    SMOKE_MONGO_URL=mongodb://... SMOKE_DB_NAME=... \
    python3 scripts/smoke_test_live_edge.py

SMOKE_MONGO_URL/SMOKE_DB_NAME are required for the tenant-isolation section
only: the live product has no self-service way to create a second,
independently-owned business (register() always forces a newly-enrolled
staff account onto the enrolling owner's own businessId — see
routes/auth.py register() and routes/multi_tenant.py create_business()).
Until a proper operator-facing "provision a second tenant" admin endpoint
exists (tracked as a backlog item, see docs/COLLABORATION_HANDOFF.md), the
one direct-DB step below (flipping a second staff account's businessId) is
how this script — and this repo's own tests/inprocess/*_tenant_isolation.py
suite — establishes two genuinely separate tenants for the isolation check.
Role and payment-sandbox checks need no DB access at all and run against
any BASE_URL with just the owner credential.

Exits non-zero on the first failed assertion; prints a step-by-step log.
"""
from __future__ import annotations
import os
import sys
import uuid

import requests

BASE_URL = os.environ.get("SMOKE_BASE_URL", "").rstrip("/")
OWNER_EMAIL = os.environ.get("SMOKE_OWNER_EMAIL", "owner@nua.com")
OWNER_PASSWORD = os.environ.get("SMOKE_OWNER_PASSWORD", "")
MONGO_URL = os.environ.get("SMOKE_MONGO_URL", "")
DB_NAME = os.environ.get("SMOKE_DB_NAME", "")

FAILURES: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}" + (f" — {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(label)


def api(method: str, path: str, token: str | None = None, **kw) -> requests.Response:
    headers = kw.pop("headers", {})
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return requests.request(method, f"{BASE_URL}{path}", headers=headers, timeout=15, **kw)


def main() -> int:
    if not BASE_URL:
        print("SMOKE_BASE_URL is required (the live edge to test — e.g. the Vercel staging URL)")
        return 2
    if not OWNER_PASSWORD:
        print("SMOKE_OWNER_PASSWORD is required — never hardcode it, pass via env")
        return 2

    print(f"=== Live smoke test against {BASE_URL} ===\n")

    # --- 1. Health ---
    r = api("GET", "/api/health")
    check("GET /api/health returns 200", r.status_code == 200, r.text[:200])

    # --- 2. Owner login ---
    r = api("POST", "/api/auth/login", json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD})
    check("Owner login succeeds", r.status_code == 200, r.text[:200])
    if r.status_code != 200:
        print("\nCannot continue without a working owner login.")
        return 1
    owner_token = r.json()["token"]
    owner_business_id = r.json()["user"]["businessId"]

    # --- 3. Role boundaries (same tenant, no DB access needed) ---
    suffix = uuid.uuid4().hex[:8]
    manager_email = f"smoke-manager-{suffix}@nua-smoke-test.com"
    cashier_email = f"smoke-cashier-{suffix}@nua-smoke-test.com"
    r = api("POST", "/api/auth/staff/add", token=owner_token,
            json={"name": "Smoke Manager", "email": manager_email, "password": "SmokeTest2026!", "role": "manager"})
    check("Owner can enroll a manager", r.status_code == 200, r.text[:200])
    manager_id = r.json().get("id") if r.status_code == 200 else None
    r = api("POST", "/api/auth/register", token=owner_token,
            json={"name": "Smoke Cashier", "email": cashier_email, "password": "SmokeTest2026!", "role": "cashier"})
    check("Owner can enroll a cashier", r.status_code == 200, r.text[:200])
    cashier_id = r.json().get("user", {}).get("id") if r.status_code == 200 else None

    manager_token = api("POST", "/api/auth/login", json={"email": manager_email, "password": "SmokeTest2026!"}).json().get("token")
    cashier_token = api("POST", "/api/auth/login", json={"email": cashier_email, "password": "SmokeTest2026!"}).json().get("token")
    check("Manager login succeeds", bool(manager_token))
    check("Cashier login succeeds", bool(cashier_token))

    r = api("GET", "/api/auth/reports/labor-cost", token=cashier_token)
    check("Cashier is blocked from owner-only labor-cost report", r.status_code == 403, f"got {r.status_code}")
    r = api("GET", "/api/auth/reports/labor-cost", token=manager_token)
    check("Manager is blocked from owner-only labor-cost report", r.status_code == 403, f"got {r.status_code}")
    r = api("GET", "/api/auth/reports/labor-cost", token=owner_token)
    check("Owner can reach the owner-only labor-cost report", r.status_code == 200, f"got {r.status_code}")
    r = api("GET", "/api/auth/staff", token=cashier_token)
    check("Cashier is blocked from the staff list (owner/manager only)", r.status_code == 403, f"got {r.status_code}")
    r = api("GET", "/api/auth/staff", token=manager_token)
    check("Manager can reach the staff list", r.status_code == 200, f"got {r.status_code}")

    # --- 4. Payment sandbox ---
    r = api("POST", "/api/stripe/checkout", token=owner_token,
            json={"originUrl": BASE_URL, "amount": 12.34})
    check("Stripe sandbox checkout session is created", r.status_code == 200 and "url" in r.json(),
          f"status={r.status_code} body={r.text[:200]}")

    # --- 5. Tenant isolation (requires direct Mongo access to provision tenant B) ---
    if not MONGO_URL or not DB_NAME:
        print("\n[SKIP] Tenant isolation section — SMOKE_MONGO_URL/SMOKE_DB_NAME not provided.")
        print("       Role and payment checks above still ran against the real edge.")
    else:
        import pymongo
        mongo = pymongo.MongoClient(MONGO_URL)[DB_NAME]
        tenant_b_email = f"smoke-tenant-b-owner-{suffix}@nua-smoke-test.com"
        tenant_b_biz = f"SMOKE-TENANT-B-{suffix}"
        r = api("POST", "/api/auth/register", token=owner_token,
                json={"name": "Tenant B Owner", "email": tenant_b_email, "password": "SmokeTenantB2026!"})
        check("Tenant B account created (pre-reassignment)", r.status_code == 200, r.text[:200])
        mongo.auth_users.update_one({"email": tenant_b_email},
                                     {"$set": {"role": "owner", "businessId": tenant_b_biz}})
        r = api("POST", "/api/auth/login", json={"email": tenant_b_email, "password": "SmokeTenantB2026!"})
        check("Tenant B owner login succeeds", r.status_code == 200, r.text[:200])
        tenant_b_token = r.json().get("token")

        r = api("POST", "/api/customers", token=owner_token,
                json={"name": "Tenant A Smoke Customer", "email": f"smoke-a-{suffix}@nua-smoke-test.com", "phone": f"+614{suffix}"})
        check("Tenant A can create a customer", r.status_code == 200, r.text[:200])
        tenant_a_customer_id = r.json().get("id") if r.status_code == 200 else None

        r = api("POST", "/api/customers", token=tenant_b_token,
                json={"name": "Tenant B Smoke Customer", "email": f"smoke-b-{suffix}@nua-smoke-test.com", "phone": f"+615{suffix}"})
        check("Tenant B can create a customer", r.status_code == 200, r.text[:200])
        tenant_b_customer_id = r.json().get("id") if r.status_code == 200 else None

        a_list = api("GET", "/api/customers", token=owner_token).json()
        b_list = api("GET", "/api/customers", token=tenant_b_token).json()
        check("Tenant A's customer list excludes Tenant B's customer",
              not any(c.get("id") == tenant_b_customer_id for c in a_list))
        check("Tenant B's customer list excludes Tenant A's customer",
              not any(c.get("id") == tenant_a_customer_id for c in b_list))
        check("Tenant A's customer list includes its own customer",
              any(c.get("id") == tenant_a_customer_id for c in a_list))
        check("Tenant B's customer list includes its own customer",
              any(c.get("id") == tenant_b_customer_id for c in b_list))

        # Cleanup — this script creates real rows on whatever BASE_URL it's
        # pointed at; never leave smoke-test accounts/data behind.
        mongo.auth_users.delete_many({"email": {"$in": [manager_email, cashier_email, tenant_b_email]}})
        mongo.customers.delete_many({"id": {"$in": [tenant_a_customer_id, tenant_b_customer_id]}})

    print(f"\n=== {len(FAILURES)} failure(s) ===" if FAILURES else "\n=== All checks passed ===")
    for f in FAILURES:
        print(f"  - {f}")

    # Always clean up the staff accounts this script created, mongo or not.
    for sid in (manager_id, cashier_id):
        if sid:
            api("DELETE", f"/api/auth/staff/{sid}", token=owner_token)

    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
