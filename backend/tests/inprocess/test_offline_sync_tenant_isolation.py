"""routes/settings.py's POST /offline/sync had no auth dependency at all
and upserted caller-supplied transaction/product documents by id with no
tenant check whatsoever — any authenticated staff member of any business
could overwrite another business's transaction or product (with entirely
caller-controlled fields) just by knowing/guessing its id. Found during
the tenant-ownership release-closure pass while enumerating every
untagged-data mutation path in the codebase; this endpoint has no
frontend caller and no prior test coverage, so the gap had never
surfaced. Fixed: requires Depends(get_user), refuses (skips, doesn't
error the whole batch) any id that already belongs to a different
business, and stamps the caller's own businessId on every upserted
document.
"""
import asyncio

from database import db
from tests.inprocess.conftest import req


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_business(client, owner_headers, *, biz_id, email):
    _run(db.businesses.insert_one({
        "id": biz_id, "slug": biz_id, "name": f"Biz {biz_id}", "status": "active",
    }))
    client.post("/api/auth/register", headers=owner_headers, json={
        "name": "Offline Sync Test Owner", "email": email, "password": "OfflineSyncTest2026!",
    })
    _run(db.auth_users.update_one({"email": email}, {"$set": {"role": "owner", "businessId": biz_id}}))
    r = client.post("/api/auth/login", json={"email": email, "password": "OfflineSyncTest2026!"})
    assert r.status_code == 200, f"login failed: {r.text[:200]}"
    client.cookies.clear()
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _cleanup_business(biz_id):
    _run(db.businesses.delete_many({"id": biz_id}))
    _run(db.auth_users.delete_many({"businessId": biz_id}))


def test_offline_sync_requires_authentication(anon):
    r = req(anon, "POST", "/api/offline/sync", json={"transactions": [], "products": []})
    assert r.status_code == 401


def test_offline_sync_stamps_the_callers_own_businessId(client, owner_headers):
    txn_id = "OFFLINE-SYNC-TXN-1"
    prod_id = "OFFLINE-SYNC-PROD-1"
    try:
        r = req(client, "POST", "/api/offline/sync", headers=owner_headers, json={
            "transactions": [{"id": txn_id, "total": 25.0}],
            "products": [{"id": prod_id, "name": "Synced Product", "price": 5.0}],
        })
        assert r.status_code == 200, r.text[:200]
        body = r.json()
        assert body["synced"]["transactions"] == 1
        assert body["synced"]["products"] == 1

        txn = _run(db.transactions.find_one({"id": txn_id}, {"_id": 0}))
        prod = _run(db.products.find_one({"id": prod_id}, {"_id": 0}))
        assert txn["businessId"] == "default"
        assert prod["businessId"] == "default"
    finally:
        _run(db.transactions.delete_many({"id": txn_id}))
        _run(db.products.delete_many({"id": prod_id}))


def test_offline_sync_refuses_to_overwrite_another_businesss_transaction(client, owner_headers):
    biz_b = "offline-sync-biz-b"
    txn_id = "OFFLINE-SYNC-TXN-CROSS-1"
    try:
        biz_b_headers = _make_business(client, owner_headers, biz_id=biz_b, email="offline-sync-b@nua.com")
        # Business B creates the transaction first.
        seed = req(client, "POST", "/api/offline/sync", headers=biz_b_headers, json={
            "transactions": [{"id": txn_id, "total": 99.0}],
        })
        assert seed.status_code == 200, seed.text[:200]

        # Business A (owner_headers = "default") tries to overwrite it by id.
        hijack = req(client, "POST", "/api/offline/sync", headers=owner_headers, json={
            "transactions": [{"id": txn_id, "total": 1.0}],
        })
        assert hijack.status_code == 200, hijack.text[:200]
        assert hijack.json()["synced"]["transactions"] == 0, (
            "a sync attempt against another business's existing transaction id must be skipped, not applied"
        )

        still_theirs = _run(db.transactions.find_one({"id": txn_id}, {"_id": 0}))
        assert still_theirs["businessId"] == biz_b
        assert still_theirs["total"] == 99.0, "another business's transaction must never be overwritten"
    finally:
        _run(db.transactions.delete_many({"id": txn_id}))
        _cleanup_business(biz_b)
