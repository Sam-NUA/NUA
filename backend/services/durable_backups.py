"""Private Vercel Blob archives, independent of the primary Mongo database.

No filesystem fallback. Blob must be a PRIVATE store connected to this
project. Credentials and private URLs are never returned by owner APIs.
"""
import asyncio
import hashlib
import os
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

from database import db


class BackupStorageUnavailable(RuntimeError):
    pass


def configured():
    return bool(os.environ.get("BLOB_READ_WRITE_TOKEN"))


async def retain(archive: bytes, business_id=None):
    if not configured():
        raise BackupStorageUnavailable("Private backup storage is not configured")
    from vercel.blob import put_async, get_async
    backup_id = uuid.uuid4().hex
    scope = hashlib.sha256((business_id or "deployment").encode()).hexdigest()[:24]
    path = f"nua-backups/{scope}/{datetime.now(timezone.utc):%Y/%m/%d}/{backup_id}.tar.gz"
    digest = hashlib.sha256(archive).hexdigest()
    blob = await asyncio.wait_for(put_async(
        path, archive, access="private", content_type="application/gzip",
        overwrite=False, multipart=len(archive) > 5_000_000), timeout=90)
    if not (urlparse(blob.url).hostname or "").endswith(".private.blob.vercel-storage.com"):
        raise BackupStorageUnavailable("Backup storage must be private")
    # Read the object back through the provider; a successful PUT alone is
    # insufficient evidence that the retained archive can be restored.
    stored = await asyncio.wait_for(get_async(blob.url, access="private", use_cache=False), timeout=45)
    if stored.status_code != 200 or hashlib.sha256(stored.content).hexdigest() != digest:
        raise BackupStorageUnavailable("Stored backup verification failed")
    metadata = {"id": backup_id, "businessId": business_id, "pathname": blob.pathname,
                "url": blob.url, "sha256": digest, "sizeBytes": len(archive),
                "createdAt": datetime.now(timezone.utc).isoformat(), "verified": True}
    await db.durable_backups.insert_one(metadata)
    return {k: v for k, v in metadata.items() if k not in ("_id", "url", "pathname")}, stored.content


async def read(backup_id, business_id):
    if not business_id:
        raise ValueError("Business scope required")
    row = await db.durable_backups.find_one({"id": backup_id, "businessId": business_id})
    if not row:
        return None
    from vercel.blob import get_async
    stored = await asyncio.wait_for(get_async(row["url"], access="private", use_cache=False), timeout=45)
    if stored.status_code != 200 or hashlib.sha256(stored.content).hexdigest() != row["sha256"]:
        raise BackupStorageUnavailable("Stored backup verification failed")
    return stored.content
