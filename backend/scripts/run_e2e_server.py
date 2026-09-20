"""Boots the real FastAPI app against an in-memory Mongo, for the Playwright
E2E suite to run against.

Not for production, not even for local dev against real data — this exists
so `frontend/e2e/*.spec.js` has something to talk to in CI without a Mongo
service container. Same mongomock-motor swap tests/inprocess/conftest.py
already uses, just with uvicorn serving real HTTP instead of TestClient
calling the ASGI app in-process, because a browser (Playwright) needs an
actual socket to connect to.

Usage: python scripts/run_e2e_server.py [port]
"""
import os
import sys

# Runs regardless of invocation cwd — "server" has to resolve as a top-level
# module the way server.py's own sibling imports (routes.*, services.*, ...)
# expect, which means the backend/ directory itself on sys.path, not just
# this script's own scripts/ directory (what Python adds by default).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "e2e_tests")
os.environ.setdefault("JWT_SECRET", "e2e-test-secret-not-for-production")
os.environ.setdefault("ADMIN_EMAIL", "owner@nua.com")
os.environ.setdefault("ADMIN_PASSWORD", "NuaOwner2026!")
os.environ.setdefault("DEMO_STAFF_PASSWORD", "Staff2026!")
os.environ.setdefault("SUPPORT_OVERRIDE_KEY", "e2e-test-only-support-override-key")
# Without this, server.py's CORS setup falls back to allow_origins=["*"] with
# allow_credentials=False (see server.py's comment on frontend_url) — and the
# frontend's axios client sends every request withCredentials:true. Browsers
# refuse a wildcard-origin response to a credentialed request outright, so
# every single API call (including login) would fail at the CORS step before
# ever reaching a route. Point this at wherever playwright.config.js serves
# the built frontend.
os.environ.setdefault("FRONTEND_URL", "http://127.0.0.1:3100")

import mongomock_motor
import motor.motor_asyncio as motor_asyncio
motor_asyncio.AsyncIOMotorClient = mongomock_motor.AsyncMongoMockClient

import uvicorn

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8001
    uvicorn.run("server:app", host="127.0.0.1", port=port, log_level="warning")
