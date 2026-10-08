"""Single-use email recovery, with deployment-wide readiness (no account lookup)."""
import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from database import db


def reset_origin():
    value = os.environ.get("FRONTEND_URL", "").strip().rstrip("/")
    parsed = urlsplit(value)
    local = parsed.hostname in ("localhost", "127.0.0.1") and not os.environ.get("VERCEL")
    if (parsed.scheme != "https" and not (local and parsed.scheme == "http")) or not parsed.hostname:
        return None
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path:
        return None
    return value


def recovery_ready():
    return bool(reset_origin() and os.environ.get("SENDGRID_API_KEY", "").strip()
                and os.environ.get("SENDGRID_FROM_EMAIL", "").strip())


async def issue_reset(user):
    token = secrets.token_urlsafe(32)
    # One current link per account, shared across all serverless instances.
    await db.password_reset_tokens.replace_one(
        {"_id": user["id"]},
        {"_id": user["id"], "tokenHash": hashlib.sha256(token.encode()).hexdigest(),
         "credentialHash": user.get("password_hash", ""),
         "expiresAt": datetime.now(timezone.utc) + timedelta(minutes=30)}, upsert=True)
    return token


async def consume_reset(token):
    return await db.password_reset_tokens.find_one_and_delete({
        "tokenHash": hashlib.sha256(token.encode()).hexdigest(),
        "expiresAt": {"$gt": datetime.now(timezone.utc)},
    })


async def cancel_reset(token):
    await db.password_reset_tokens.delete_one({"tokenHash": hashlib.sha256(token.encode()).hexdigest()})
