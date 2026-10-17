'use strict';
const fs = require('node:fs/promises');
const path = require('node:path');

// Electron 44's Windows OSCrypt key is DPAPI-wrapped in sessionData/Local
// State. Chromium schedules that preference write; fsyncing our ciphertext
// alone can otherwise acknowledge records whose key disappears on taskkill.
// Observe and flush the protected metadata, never rewrite it or expose a key.
async function waitForWindowsKey({ safeStorage, sessionDataPath, platform = process.platform,
  timeoutMs = 20000, intervalMs = 100 }) {
  if (platform !== 'win32' || !safeStorage.isEncryptionAvailable()) {
    throw new Error('Windows OS encryption unavailable');
  }
  safeStorage.encryptString('NUA key persistence readiness');
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    let handle;
    try {
      handle = await fs.open(path.join(sessionDataPath, 'Local State'), 'r+');
      const metadata = JSON.parse(await handle.readFile('utf8'));
      const protectedKey = metadata.os_crypt?.encrypted_key;
      if (typeof protectedKey === 'string' && protectedKey.length > 8
          && Buffer.from(protectedKey, 'base64').subarray(0, 5).toString() === 'DPAPI') {
        await handle.sync();
        return;
      }
    } catch (error) {
      if (error.code !== 'ENOENT' && !(error instanceof SyntaxError)) throw error;
    } finally {
      if (handle) await handle.close();
    }
    await new Promise(resolve => setTimeout(resolve, intervalMs));
  }
  throw new Error('Windows protected encryption key has not been persisted; no durable records accepted');
}
module.exports = { waitForWindowsKey };
