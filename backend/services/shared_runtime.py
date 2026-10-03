"""Mongo-backed coordination; no warm-process state is required.

Rate limits use fixed UTC windows (a boundary may admit two windows' worth).
The live feed is a bounded invalidation log, not an accounting ledger. A
missing/evicted cursor tells the client to refresh authoritative API state.
"""
import hashlib
import json
import math
import uuid
from datetime import datetime, timedelta, timezone
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError


class SharedRuntime:
    def __init__(self, database):
        self.db = database

    async def allow(self, key, limit, window, now):
        bucket = math.floor(now / window)
        digest = hashlib.sha256(key.encode()).hexdigest()
        match = {"_id": f"{digest}:{window}:{bucket}"}
        update = {"$inc": {"count": 1}, "$setOnInsert": {
            "expiresAt": datetime.fromtimestamp((bucket + 2) * window, timezone.utc)}}
        try:
            row = await self.db.rate_limit_windows.find_one_and_update(
                match, update, upsert=True, return_document=ReturnDocument.AFTER)
        except DuplicateKeyError:
            row = await self.db.rate_limit_windows.find_one_and_update(
                match, {"$inc": {"count": 1}}, return_document=ReturnDocument.AFTER)
        return row["count"] <= limit, max(1, math.ceil((bucket + 1) * window - now))

    async def publish(self, business_id, event):
        if not business_id:
            return  # Never broadcast unscoped events across tenants.
        if len(json.dumps(event, default=str).encode()) > 16384:
            event = {"type": "sync.required"}
        item = {"id": uuid.uuid4().hex, "event": event}
        update = {"$push": {"events": {"$each": [item], "$slice": -100}},
                  "$set": {"expiresAt": datetime.now(timezone.utc) + timedelta(hours=1)}}
        try:
            await self.db.live_event_feeds.update_one({"_id": business_id}, update, upsert=True)
        except DuplicateKeyError:
            await self.db.live_event_feeds.update_one({"_id": business_id}, update)

    async def read(self, business_id, cursor=None):
        if not business_id:
            raise ValueError("Business scope is required")
        row = await self.db.live_event_feeds.find_one({"_id": business_id})
        events = (row or {}).get("events", [])
        last = events[-1]["id"] if events else "empty"
        ids = [item["id"] for item in events]
        if cursor == "empty":
            return {"cursor": last, "events": [e["event"] for e in events], "reset": bool(events)}
        if cursor not in ids:
            return {"cursor": last, "events": [], "reset": True}
        return {"cursor": last, "events": [e["event"] for e in events[ids.index(cursor)+1:]], "reset": False}

    async def ensure_indexes(self):
        await self.db.rate_limit_windows.create_index("expiresAt", expireAfterSeconds=0)
        await self.db.live_event_feeds.create_index("expiresAt", expireAfterSeconds=0)
