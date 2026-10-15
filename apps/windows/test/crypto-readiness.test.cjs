'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { waitForWindowsKey } = require('../src/crypto-readiness.cjs');
const safeStorage = { isEncryptionAvailable: () => true, encryptString: () => Buffer.from('ciphertext') };

test('durable writes wait for Chromium to persist its DPAPI-protected key', async t => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'nua-key-ready-'));
  t.after(() => fs.rm(root, { recursive: true, force: true }));
  let ready = false;
  const waiting = waitForWindowsKey({ safeStorage, sessionDataPath: root, platform: 'win32', intervalMs: 5 })
    .then(() => { ready = true; });
  await fs.writeFile(path.join(root, 'Local State'), JSON.stringify({ os_crypt: {} }));
  await new Promise(resolve => setTimeout(resolve, 20));
  assert.equal(ready, false);
  const contents = JSON.stringify({ os_crypt: { encrypted_key: Buffer.from('DPAPI-protected-test-key').toString('base64') } });
  await fs.writeFile(path.join(root, 'Local State'), contents);
  await waiting;
  assert.equal(await fs.readFile(path.join(root, 'Local State'), 'utf8'), contents);
});

test('missing key metadata or unavailable OS encryption never opens durable storage', async t => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'nua-key-locked-'));
  t.after(() => fs.rm(root, { recursive: true, force: true }));
  await assert.rejects(waitForWindowsKey({ safeStorage, sessionDataPath: root, platform: 'win32', timeoutMs: 20, intervalMs: 5 }), /not been persisted/);
  await assert.rejects(waitForWindowsKey({ safeStorage: { isEncryptionAvailable: () => false }, sessionDataPath: root, platform: 'win32' }), /unavailable/);
  await assert.rejects(waitForWindowsKey({ safeStorage, sessionDataPath: root, platform: 'linux' }), /unavailable/);
});
