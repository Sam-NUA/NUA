'use strict';
const fs = require('node:fs/promises');
const path = require('node:path');
const { createHash, randomUUID } = require('node:crypto');
// Main process only. No renderer API accepts filenames or encryption keys.
class EncryptedStore {
  constructor(root, cryptoProvider) { this.root = root; this.crypto = cryptoProvider; this.writes = Promise.resolve(); }
  filename(scope) {
    if (typeof scope !== 'string' || !scope || scope.length > 500) throw new Error('Invalid storage scope');
    return path.join(this.root, createHash('sha256').update(scope).digest('hex') + '.bin');
  }
  async read(scope) {
    let bytes;
    try { bytes = await fs.readFile(this.filename(scope)); }
    catch (e) { if (e.code === 'ENOENT') return null; throw e; }
    // Corrupt or unavailable encryption is a hard failure, never an empty queue.
    return JSON.parse(await this.crypto.decryptString(bytes));
  }
  async write(scope, value) {
    const serialized = JSON.stringify(value);
    if (Buffer.byteLength(serialized) > 8 * 1024 * 1024) throw new Error('Storage capacity exceeded');
    const file = this.filename(scope);
    const operation = this.writes.then(async () => {
      await fs.mkdir(this.root, { recursive: true });
      const temporary = file + '.' + randomUUID() + '.tmp';
      const bytes = await this.crypto.encryptString(serialized);
      const handle = await fs.open(temporary, 'wx', 0o600);
      try { await handle.writeFile(bytes); await handle.sync(); }
      finally { await handle.close(); }
      try { await fs.rename(temporary, file); }
      finally { await fs.rm(temporary, { force: true }); }
    });
    this.writes = operation.catch(() => {});
    return operation;
  }
}
module.exports = { EncryptedStore };
