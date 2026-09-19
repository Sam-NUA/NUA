"""Tenant-owned settings never fall back to unowned legacy documents.
Legacy settings require the support migration before they can be used.
"""
from __future__ import annotations
from typing import Any, Optional

from database import db
from middleware.actor_context import get_actor_context


async def get_setting(key: str, business_id: Optional[str] = None) -> Optional[Any]:
    """Read only this business's verified settings; absent values use caller defaults."""
    biz = business_id or get_actor_context().get("businessId")
    if biz:
        own = await db.settings.find_one({"key": key, "businessId": biz, "_ownershipQuarantined": {"$ne": True}}, {"_id": 0})
        if own is not None:
            return own.get("value")
    return None


async def set_setting(key: str, value: Any, business_id: Optional[str] = None) -> None:
    """Writes THIS business's own copy — never the shared legacy document,
    even if that's what this business happened to be reading before its
    first write. Two businesses editing the same key can never collide
    once both have written at least once."""
    biz = business_id or get_actor_context().get("businessId")
    if not biz:
        raise ValueError("Business context required for settings write")
    await db.settings.update_one(
        {"key": key, "businessId": biz},
        {"$set": {"key": key, "businessId": biz, "value": value}},
        upsert=True,
    )


async def get_scoped_singleton(collection, match: dict, business_id: Optional[str] = None) -> Optional[dict]:
    """Same pattern as get_setting, generalized to any single-conceptual-
    document collection keyed by something other than `key` (e.g.
    `db.loyalty_config`'s `{"id": "default"}`, `db.agent_autonomy`'s same
    shape). `match` identifies the singleton's own key fields, unrelated
    to which business owns which copy of it."""
    biz = business_id or get_actor_context().get("businessId")
    if biz:
        own = await collection.find_one({**match, "businessId": biz, "_ownershipQuarantined": {"$ne": True}}, {"_id": 0})
        if own is not None:
            return own
    return None


async def set_scoped_singleton(collection, match: dict, doc: dict, business_id: Optional[str] = None) -> None:
    biz = business_id or get_actor_context().get("businessId")
    if not biz:
        raise ValueError("Business context required for settings write")
    await collection.update_one(
        {**match, "businessId": biz},
        {"$set": {**doc, **match, "businessId": biz}},
        upsert=True,
    )
