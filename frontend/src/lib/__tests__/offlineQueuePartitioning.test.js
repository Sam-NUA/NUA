/**
 * MOBILE_DESKTOP_BACKLOG.md — "local device storage must be partitioned
 * by authorised business/account context." Before this, offlineQueue.js
 * used one fixed IndexedDB database name for every business that ever
 * logged in on a device. jsdom has no real IndexedDB, so this uses
 * fake-indexeddb (dev-only, not part of the production bundle) to
 * exercise the real activate()/lock() logic end to end rather than
 * mocking it away.
 */
// jsdom's test environment doesn't expose the global structuredClone
// fake-indexeddb needs internally (real browsers and Node itself both do) —
// a test-environment gap, not a real app one.
if (typeof structuredClone === 'undefined') {
  global.structuredClone = (value) => JSON.parse(JSON.stringify(value));
}
import 'fake-indexeddb/auto';
import { activate, lock, enqueueTransaction, getQueued } from '../offlineQueue';

function uniqueBizId(label) {
  return `test-${label}-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

describe('offlineQueue business partitioning', () => {
  afterEach(() => { lock(); });

  it('scopes writes to the active business — a different business sees none of it', async () => {
    const bizA = uniqueBizId('a');
    const bizB = uniqueBizId('b');

    await activate(bizA);
    await enqueueTransaction({ items: [{ productId: 'p1', quantity: 1, price: 10 }] });
    const aRows = await getQueued();
    expect(aRows).toHaveLength(1);

    lock();
    await activate(bizB);
    const bRows = await getQueued();
    expect(bRows).toHaveLength(0);
  });

  it('a business that re-activates still sees its own previously-queued rows', async () => {
    const biz = uniqueBizId('reactivate');
    await activate(biz);
    await enqueueTransaction({ items: [{ productId: 'p1', quantity: 2, price: 5 }] });
    lock();
    await activate(biz);
    const rows = await getQueued();
    expect(rows).toHaveLength(1);
  });

  it('quarantines unscoped legacy rows instead of claiming another business data', async () => {
    // Simulate a row queued before this change shipped, under the old
    // fixed database name, by writing directly to it.
    const legacyDb = await new Promise((resolve, reject) => {
      const req = indexedDB.open('nua-offline', 3);
      req.onupgradeneeded = () => {
        const db = req.result;
        if (!db.objectStoreNames.contains('pending_transactions')) db.createObjectStore('pending_transactions', { keyPath: 'id' });
        if (!db.objectStoreNames.contains('pending_course_actions')) db.createObjectStore('pending_course_actions', { keyPath: 'id' });
        if (!db.objectStoreNames.contains('cached_reads')) db.createObjectStore('cached_reads', { keyPath: 'key' });
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
    await new Promise((resolve, reject) => {
      const tx = legacyDb.transaction('pending_transactions', 'readwrite');
      tx.objectStore('pending_transactions').put({ id: 'legacy-row-1', payload: { items: [] }, queuedAt: 'then' });
      tx.oncomplete = resolve;
      tx.onerror = () => reject(tx.error);
    });
    legacyDb.close();

    const biz = uniqueBizId('migrate');
    await activate(biz);
    const rows = await getQueued();
    expect(rows).toHaveLength(0);
    const retained = await new Promise((resolve, reject) => {
      const req = indexedDB.open('nua-offline', 3);
      req.onsuccess = () => {
        const db = req.result; const read = db.transaction('pending_transactions').objectStore('pending_transactions').getAll();
        read.onsuccess = () => { db.close(); resolve(read.result); };
        read.onerror = () => reject(read.error);
      };
    });
    expect(retained.map(row => row.id)).toContain('legacy-row-1');
  });

  it('locked storage rejects reads and writes', async () => {
    lock();
    await expect(getQueued()).rejects.toThrow('locked');
    await expect(enqueueTransaction({ items: [] })).rejects.toThrow('locked');
  });

  it('activate() is idempotent for the same business (no error on repeat calls)', async () => {
    const biz = uniqueBizId('idempotent');
    await activate(biz);
    await expect(activate(biz)).resolves.not.toThrow();
  });
});
