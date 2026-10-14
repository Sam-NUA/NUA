'use strict';
// Main-process storage boundary. Renderer hints never select a tenant or file.
// The real API verifies the exact bearer before an encrypted scope is opened.
class OfflineStore {
  constructor({ store, readToken, verifyToken }) {
    this.store = store; this.readToken = readToken; this.verifyToken = verifyToken;
    this.active = null; this.generation = 0; this.operations = Promise.resolve();
  }
  lock() { this.active = null; this.generation++; }
  async activate(expectedBusiness) {
    this.lock();
    const generation = this.generation;
    const token = await this.readToken();
    if (!token) throw new Error('Sign in before opening offline records');
    const user = await this.verifyToken(token);
    const claim = JSON.parse(Buffer.from(token.split('.')[1], 'base64url').toString('utf8'));
    if (!user.id || !user.businessId || user.businessId !== expectedBusiness
        || claim.sub !== user.id || claim.businessId !== user.businessId || !claim.deviceId) {
      throw new Error('Verified terminal session required');
    }
    if (generation !== this.generation || token !== await this.readToken()) throw new Error('Terminal session changed');
    this.active = { businessId: user.businessId, token,
      scope: JSON.stringify(['offline-v1', user.businessId, claim.deviceId]), generation };
  }
  context(expectedBusiness) {
    const c = this.active;
    if (!c || c.businessId !== expectedBusiness) throw new Error('Offline records are locked');
    return c;
  }
  assert(c) {
    if (this.active !== c || c.generation !== this.generation) throw new Error('Terminal session changed');
  }
  key(c, kind) {
    if (!['pending_transactions', 'pending_course_actions', 'cached_reads'].includes(kind)) throw new Error('Unsupported offline record type');
    return JSON.stringify([c.scope, kind]);
  }
  async rows(c, kind) {
    const value = await this.store.read(this.key(c, kind));
    this.assert(c);
    if (value === null) return [];
    if (value.version !== 1 || !Array.isArray(value.rows)) throw new Error('Offline records require recovery');
    return value.rows;
  }
  async read(kind, businessId) {
    const c = this.context(businessId);
    await this.operations;
    this.assert(c);
    return structuredClone(await this.rows(c, kind));
  }
  mutate(kind, businessId, commands) {
    const c = this.context(businessId);
    const owned = structuredClone(commands);
    if (!Array.isArray(owned) || !owned.length || owned.length > 4) throw new Error('Invalid offline write');
    const operation = this.operations.then(async () => {
      this.assert(c);
      let rows = await this.rows(c, kind);
      const key = kind === 'cached_reads' ? 'key' : 'id';
      for (const { op, value } of owned) {
        if (op === 'delete') {
          if (typeof value !== 'string' || !value || value.length > 200) throw new Error('Invalid record id');
          rows = rows.filter(row => row[key] !== value);
        } else if (op === 'add' || op === 'put') {
          if (!value || typeof value[key] !== 'string' || !value[key] || value[key].length > 200
              || (kind !== 'cached_reads' && value.businessId !== c.businessId)) throw new Error('Invalid offline ownership');
          const index = rows.findIndex(row => row[key] === value[key]);
          if (op === 'add' && index >= 0) throw new Error('Offline record already exists');
          if (index >= 0) rows[index] = value; else rows.push(value);
        } else throw new Error('Unsupported offline operation');
      }
      this.assert(c);
      await this.store.write(this.key(c, kind), { version: 1, rows });
      // A logout during atomic persistence leaves the record in its captured
      // old scope. Never acknowledge it as belonging to the new session.
      this.assert(c);
    });
    this.operations = operation.catch(() => {});
    return operation;
  }
}
module.exports = { OfflineStore };
