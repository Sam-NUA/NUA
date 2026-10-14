'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { createCipheriv, createDecipheriv, randomBytes } = require('node:crypto');
const { OfflineStore } = require('../src/offline-store.cjs');
const { EncryptedStore } = require('../src/encrypted-store.cjs');
function token(businessId, deviceId = 'DEV-A', sub = 'staff-A') {
  return 'header.' + Buffer.from(JSON.stringify({ sub, businessId, deviceId })).toString('base64url') + '.signature';
}
function memory() {
  const values = new Map();
  return { read: async key => structuredClone(values.get(key) ?? null), write: async (key, value) => { values.set(key, structuredClone(value)); } };
}
function setup(store = memory()) {
  let currentToken = token('A');
  const options = { store, readToken: async () => currentToken,
    verifyToken: async value => { const c = JSON.parse(Buffer.from(value.split('.')[1], 'base64url')); return { id: c.sub, businessId: c.businessId }; } };
  return { options, queue: new OfflineStore(options), switchTo: value => { currentToken = value; } };
}
const sale = { id: 'intent-1', businessId: 'A', state: 'pending', payload: { clientOpId: 'op-1', paymentMethod: 'cash', walkInName: 'A guest' } };
test('only server-verified, bound sessions can open a scope', async () => {
  const x = setup();
  await assert.rejects(x.queue.activate('B'));
  x.switchTo(token('A', null)); await assert.rejects(x.queue.activate('A'));
  await assert.rejects(x.queue.read('pending_transactions', 'A'));
  const unavailable = new OfflineStore({ ...x.options, verifyToken: async () => { throw new Error('offline'); } });
  await assert.rejects(unavailable.activate('A'));
});
test('business and device switches cannot read previous terminal records', async () => {
  const x = setup(); await x.queue.activate('A');
  await x.queue.mutate('pending_transactions', 'A', [{ op: 'add', value: sale }]);
  x.queue.lock(); x.switchTo(token('B', 'DEV-B')); await x.queue.activate('B');
  assert.deepEqual(await x.queue.read('pending_transactions', 'B'), []);
  await assert.rejects(x.queue.read('pending_transactions', 'A'));
  await assert.rejects(x.queue.mutate('pending_transactions', 'B', [{ op: 'put', value: sale }]));
  x.queue.lock(); x.switchTo(token('A')); await x.queue.activate('A');
  assert.equal((await x.queue.read('pending_transactions', 'A'))[0].payload.clientOpId, 'op-1');
});
test('lock during asynchronous read prevents late records escaping', async () => {
  let release;
  const x = setup({ read: () => new Promise(resolve => { release = resolve; }), write: async () => {} });
  await x.queue.activate('A'); const pending = x.queue.read('pending_transactions', 'A');
  await new Promise(resolve => setImmediate(resolve)); x.queue.lock();
  release({ version: 1, rows: [sale] }); await assert.rejects(pending, /session changed/);
});
test('encrypted records survive a new instance without plaintext financial data', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'nua-offline-'));
  // Test-only AES provider; production uses Windows safeStorage, checked in CI.
  const key = randomBytes(32);
  const crypto = {
    encryptString: async text => {
      const iv = randomBytes(12), c = createCipheriv('aes-256-gcm', key, iv);
      const bytes = Buffer.concat([c.update(text), c.final()]);
      return Buffer.concat([iv, c.getAuthTag(), bytes]);
    },
    decryptString: async bytes => {
      const d = createDecipheriv('aes-256-gcm', key, bytes.subarray(0, 12));
      d.setAuthTag(bytes.subarray(12, 28));
      return Buffer.concat([d.update(bytes.subarray(28)), d.final()]).toString();
    },
  };
  try {
    const first = setup(new EncryptedStore(root, crypto)); await first.queue.activate('A');
    await first.queue.mutate('pending_transactions', 'A', [{ op: 'add', value: sale }]);
    first.queue.lock();
    const restarted = setup(new EncryptedStore(root, crypto));
    await assert.rejects(restarted.queue.read('pending_transactions', 'A'));
    await restarted.queue.activate('A');
    assert.deepEqual(await restarted.queue.read('pending_transactions', 'A'), [sale]);
    for (const file of await fs.readdir(root)) assert.ok(!(await fs.readFile(path.join(root, file))).includes(Buffer.from('A guest')));
    await restarted.queue.mutate('pending_transactions', 'A', [{ op: 'delete', value: sale.id }]);
    assert.deepEqual(await restarted.queue.read('pending_transactions', 'A'), []);
  } finally { await fs.rm(root, { recursive: true, force: true }); }
});
