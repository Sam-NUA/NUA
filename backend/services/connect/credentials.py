"""Per-venue provider credential storage.

Credentials are encrypted at rest with Fernet (AES-128-CBC + HMAC), keyed off
the app's existing JWT_SECRET so there's no second secret to provision or
lose — the same way the rest of NUA already treats JWT_SECRET as the one
app-wide key. Only ever decrypted in-process to make an outbound call to the
provider or to run a connection test; never returned to a client verbatim
(get_credentials_masked strips values down to a last-4 hint).
"""
import base64
import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from cryptography.fernet import Fernet, InvalidToken

from database import db


def _fernet() -> Fernet:
    # No hardcoded fallback: this key encrypts third-party provider
    # credentials at rest, so a known, source-visible default would mean
    # every deployment that forgot to set JWT_SECRET stores those
    # credentials under a publicly-guessable key. Tests/local dev set
    # JWT_SECRET explicitly (tests/inprocess/conftest.py, run_demo_backend.py,
    # scripts/run_e2e_server.py) so this never needs a fallback there either.
    secret = os.environ["JWT_SECRET"].encode("utf-8")
    key = base64.urlsafe_b64encode(hashlib.sha256(secret).digest())
    return Fernet(key)


def _encrypt(data: Dict[str, Any]) -> str:
    return _fernet().encrypt(json.dumps(data).encode("utf-8")).decode("utf-8")


def _decrypt(token: str) -> Dict[str, Any]:
    try:
        return json.loads(_fernet().decrypt(token.encode("utf-8")).decode("utf-8"))
    except InvalidToken:
        return {}


async def save_credentials(business_id: str, provider: str, creds: Dict[str, Any]) -> None:
    doc = {
        "businessId": business_id,
        "provider": provider,
        "encrypted": _encrypt(creds),
        "fieldNames": sorted(creds.keys()),
        "updatedAt": datetime.now(timezone.utc).isoformat(),
    }
    await db.integration_credentials.update_one(
        {"businessId": business_id, "provider": provider},
        {"$set": doc, "$setOnInsert": {"createdAt": doc["updatedAt"]}},
        upsert=True,
    )


async def get_credentials(business_id: str, provider: str) -> Optional[Dict[str, Any]]:
    doc = await db.integration_credentials.find_one(
        {"businessId": business_id, "provider": provider}, {"_id": 0}
    )
    if not doc:
        return None
    return _decrypt(doc["encrypted"])


async def get_credentials_masked(business_id: str, provider: str) -> Optional[Dict[str, Any]]:
    """Field names + a last-4 hint only — safe to return to the frontend."""
    doc = await db.integration_credentials.find_one(
        {"businessId": business_id, "provider": provider}, {"_id": 0}
    )
    if not doc:
        return None
    creds = _decrypt(doc["encrypted"])
    return {
        k: (f"...{str(v)[-4:]}" if v else "")
        for k, v in creds.items()
    }


async def delete_credentials(business_id: str, provider: str) -> None:
    await db.integration_credentials.delete_one({"businessId": business_id, "provider": provider})


async def has_credentials(business_id: str, provider: str) -> bool:
    return await db.integration_credentials.count_documents(
        {"businessId": business_id, "provider": provider}
    ) > 0


async def update_status(business_id: str, provider: str, status: str, error: Optional[str] = None) -> None:
    await db.integration_credentials.update_one(
        {"businessId": business_id, "provider": provider},
        {"$set": {
            "status": status,
            "lastError": error,
            "lastCheckedAt": datetime.now(timezone.utc).isoformat(),
        }},
    )


async def get_status_doc(business_id: str, provider: str) -> Optional[Dict[str, Any]]:
    doc = await db.integration_credentials.find_one(
        {"businessId": business_id, "provider": provider},
        {"_id": 0, "status": 1, "lastError": 1, "lastCheckedAt": 1, "updatedAt": 1, "fieldNames": 1},
    )
    return doc
