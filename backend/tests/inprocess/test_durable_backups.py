import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from database import db
from services import backup, durable_backups


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_retained_backup_reads_object_before_success(monkeypatch):
    import vercel.blob
    archive = run(backup.create_backup())
    monkeypatch.setenv('BLOB_READ_WRITE_TOKEN', 'test-private-storage')
    put = AsyncMock(return_value=SimpleNamespace(url='https://unit.private.blob.vercel-storage.com/backup', pathname='backup'))
    get = AsyncMock(return_value=SimpleNamespace(status_code=200, content=archive))
    monkeypatch.setattr(vercel.blob, 'put_async', put)
    monkeypatch.setattr(vercel.blob, 'get_async', get)
    metadata, restored = run(durable_backups.retain(archive, 'backup-a'))
    assert metadata['verified'] and 'url' not in metadata
    assert restored == archive
    assert put.call_args.kwargs['access'] == 'private'
    assert get.call_args.kwargs['use_cache'] is False
    # A new reader obtains persisted bytes, not a process-local archive.
    assert run(durable_backups.read(metadata['id'], 'backup-a')) == archive
    assert run(durable_backups.read(metadata['id'], 'backup-b')) is None


def test_corrupt_object_never_records_success(monkeypatch):
    import vercel.blob
    monkeypatch.setenv('BLOB_READ_WRITE_TOKEN', 'test-private-storage')
    monkeypatch.setattr(vercel.blob, 'put_async', AsyncMock(return_value=SimpleNamespace(url='https://unit.private.blob.vercel-storage.com/corrupt', pathname='corrupt')))
    monkeypatch.setattr(vercel.blob, 'get_async', AsyncMock(return_value=SimpleNamespace(status_code=200, content=b'wrong')))
    with pytest.raises(durable_backups.BackupStorageUnavailable):
        run(durable_backups.retain(b'original', 'corrupt-tenant'))
    assert run(db.durable_backups.count_documents({'businessId': 'corrupt-tenant'})) == 0


def test_storage_unconfigured_has_no_local_fallback(monkeypatch):
    monkeypatch.delenv('BLOB_READ_WRITE_TOKEN', raising=False)
    with pytest.raises(durable_backups.BackupStorageUnavailable):
        run(durable_backups.retain(b'archive'))


def test_uploads_survive_new_read_and_are_tenant_scoped(client, owner_headers):
    response = client.post('/api/product-images', headers=owner_headers, json={
        'name': 'durable-probe', 'contentType': 'image/png', 'dataUrl': 'data:image/png;base64,AA=='})
    assert response.status_code == 200
    image_id = response.json()['id']
    row = run(db.product_images.find_one({'id': image_id}))
    assert row['businessId']
    archive = run(backup.create_backup(business_id=row['businessId']))
    assert backup.verify_backup(archive)['manifest']['collections']['product_images']['count'] >= 1
    # Untagged legacy images are not exposed to arbitrary tenants.
    run(db.product_images.insert_one({'id': 'legacy-private-probe', 'name': 'legacy'}))
    listed = client.get('/api/product-images', headers=owner_headers).json()
    assert any(i['id'] == image_id for i in listed)
    assert all(i['id'] != 'legacy-private-probe' for i in listed)
