"""Backup, restore, and the drill that proves the restore actually works.

The point isn't that a backup file gets produced — it's that the file, once
produced, can genuinely be restored. Every test that matters here runs the
real restore path, not a mock of it: create_backup() dumps the live data,
restore_into() writes it into a target, and run_restore_drill() does both
against a disposable scratch database and diffs the result against live.
"""
import asyncio

from conftest import req


def _loop():
    return asyncio.get_event_loop()


def test_backup_archive_round_trips_a_seeded_collection():
    from database import db
    from services import backup
    loop = _loop()

    loop.run_until_complete(db.suppliers.insert_many([
        {"id": "SUP-BK1", "name": "Backup Test Supplier A"},
        {"id": "SUP-BK2", "name": "Backup Test Supplier B"},
    ]))

    archive = loop.run_until_complete(backup.create_backup())
    verification = backup.verify_backup(archive)
    assert verification["ok"], verification["problems"]
    assert verification["manifest"]["collections"]["suppliers"]["count"] >= 2


def test_verify_backup_catches_a_corrupted_archive():
    from database import db
    from services import backup
    loop = _loop()
    archive = bytearray(loop.run_until_complete(backup.create_backup()))
    # Flip a byte in the middle of the archive — not enough to break the
    # gzip/tar container, just enough that a payload no longer matches its
    # recorded checksum.
    mid = len(archive) // 2
    archive[mid] ^= 0xFF
    result = backup.verify_backup(bytes(archive))
    # Either the corruption is caught as a checksum mismatch, or it's severe
    # enough to break the archive/manifest read entirely — both are a
    # legitimate "don't trust this backup" outcome, and either way it must
    # not silently report ok.
    assert result.get("ok") is not True


def test_restore_into_a_fresh_database_recreates_the_data():
    from database import client, db as live
    from services import backup
    loop = _loop()

    loop.run_until_complete(live.suppliers.insert_one(
        {"id": "SUP-RESTORE", "name": "Restore Target Supplier"}))
    archive = loop.run_until_complete(backup.create_backup())

    scratch = client["backup_restore_probe"]
    loop.run_until_complete(client.drop_database("backup_restore_probe"))
    try:
        loop.run_until_complete(backup.restore_into(archive, scratch, wipe=True))
        row = loop.run_until_complete(
            scratch.suppliers.find_one({"id": "SUP-RESTORE"}, {"_id": 0}))
        assert row == {"id": "SUP-RESTORE", "name": "Restore Target Supplier"}
    finally:
        loop.run_until_complete(client.drop_database("backup_restore_probe"))


def test_restore_upserts_rather_than_duplicating_on_a_second_run():
    from database import client
    from services import backup
    loop = _loop()

    scratch = client["backup_upsert_probe"]
    loop.run_until_complete(client.drop_database("backup_upsert_probe"))
    try:
        loop.run_until_complete(scratch.suppliers.insert_one(
            {"id": "SUP-UPSERT", "name": "Original name"}))
        from database import db as live
        archive_src = {"id": "SUP-UPSERT", "name": "Updated via restore"}
        loop.run_until_complete(live.suppliers.update_one(
            {"id": "SUP-UPSERT"}, {"$set": archive_src}, upsert=True))
        archive = loop.run_until_complete(backup.create_backup())

        loop.run_until_complete(backup.restore_into(archive, scratch, wipe=False))
        matches = loop.run_until_complete(
            scratch.suppliers.count_documents({"id": "SUP-UPSERT"}))
        assert matches == 1, "restoring twice should upsert, not duplicate the row"
        row = loop.run_until_complete(
            scratch.suppliers.find_one({"id": "SUP-UPSERT"}, {"_id": 0}))
        assert row["name"] == "Updated via restore"
    finally:
        loop.run_until_complete(client.drop_database("backup_upsert_probe"))
        loop.run_until_complete(
            __import__("database").db.suppliers.delete_one({"id": "SUP-UPSERT"}))


def test_restore_drill_proves_the_backup_matches_live_and_cleans_up():
    from database import client
    from services import backup
    loop = _loop()

    before = set(loop.run_until_complete(client.list_database_names()))
    report = loop.run_until_complete(backup.run_restore_drill())

    assert report["ok"] is True, report
    assert report["archiveVerified"] is True
    for coll, counts in report["collections"].items():
        assert counts["matches"], f"{coll}: live={counts['archiveCount']} restored={counts['restoredCount']}"

    after = set(loop.run_until_complete(client.list_database_names()))
    assert after == before, "the drill's scratch database should be dropped, not left behind"


def test_backup_endpoints_are_owner_only(client, owner_headers):
    r = req(client, "GET", "/api/ops/backup", headers=owner_headers)
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/gzip"

    r = req(client, "POST", "/api/ops/backup/drill", headers=owner_headers)
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_backup_endpoints_refuse_a_manager(client, owner_headers):
    req(client, "POST", "/api/auth/staff/add", headers=owner_headers, json={
        "name": "Backup Manager", "email": "backup.mgr@nua.com",
        "password": "MgrPass123!", "role": "manager"})
    tok = req(client, "POST", "/api/auth/login",
              json={"email": "backup.mgr@nua.com", "password": "MgrPass123!"}).json()
    client.cookies.clear()
    mh = {"Authorization": f"Bearer {tok['token']}"}
    assert req(client, "GET", "/api/ops/backup", headers=mh).status_code == 403
    assert req(client, "POST", "/api/ops/backup/drill", headers=mh).status_code == 403


def test_backup_endpoints_refuse_an_anonymous_caller(anon):
    assert req(anon, "GET", "/api/ops/backup").status_code == 401
    assert req(anon, "POST", "/api/ops/backup/drill").status_code == 401
