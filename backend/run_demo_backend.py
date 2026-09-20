"""Local live-verification runner: in-memory Mongo, real uvicorn server, no
external services required. Recreated from the pattern in
tests/inprocess/conftest.py — swap the Mongo driver for an in-memory one
before anything imports database.py, then boot the real app with uvicorn so
it can be driven from an actual browser instead of TestClient.
"""
import os

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "demo")
os.environ.setdefault("JWT_SECRET", "dev-secret-not-for-production")
os.environ.setdefault("ADMIN_EMAIL", "owner@nua.com")
os.environ.setdefault("ADMIN_PASSWORD", "NuaOwner2026!")
os.environ.setdefault("DEMO_STAFF_PASSWORD", "Staff2026!")
os.environ.setdefault("SUPPORT_OVERRIDE_KEY", "dev-only-support-override-key")

import mongomock_motor
import motor.motor_asyncio as motor_asyncio
motor_asyncio.AsyncIOMotorClient = mongomock_motor.AsyncMongoMockClient

import uvicorn
import server

if __name__ == "__main__":
    uvicorn.run(server.app, host="0.0.0.0", port=8001)
