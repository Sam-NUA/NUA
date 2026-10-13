'use strict';
function scopeKey(identity) {
  if (!identity || ['businessId', 'userId', 'deviceId'].some(k => typeof identity[k] !== 'string' || !identity[k].trim() || identity[k].length > 160)) throw new Error('Verified identity required');
  return JSON.stringify([identity.businessId, identity.userId, identity.deviceId]);
}
// Adapter contract: read(scope), write(scope,value) must be durable + atomic.
// Caller MUST obtain identity from authenticated server response, not UI input.
// One queue instance per main process; renderer never owns these credentials.
class CashOrderQueue {
  constructor({ store, send, now = Date.now, id = () => globalThis.crypto.randomUUID() }) {
    this.store = store; this.send = send; this.now = now; this.id = id;
    this.scope = null; this.epoch = 0; this.operations = Promise.resolve();
  }
  activate(verifiedIdentity) { this.scope = scopeKey(verifiedIdentity); this.epoch++; }
  lock() { this.scope = null; this.epoch++; }
  context() { if (!this.scope) throw new Error('Authentication required'); return { scope: this.scope, epoch: this.epoch }; }
  current(c) { return this.scope === c.scope && this.epoch === c.epoch; }
  exclusive(operation) {
    const result = this.operations.then(operation);
    this.operations = result.catch(() => {});
    return result;
  }
  async rows(scope) {
    const value = await this.store.read(scope);
    if (value === null) return [];
    if (value.version !== 1 || !Array.isArray(value.orders)) throw new Error('Queue requires recovery');
    return value.orders;
  }
  save(scope, rows) { return this.store.write(scope, { version: 1, orders: rows }); }
  enqueue(payload) {
    const c = this.context();
    // No locally invented payment authorization, customer balances or loyalty.
    if (payload?.paymentMethod !== 'cash' || payload.customerId || payload.pointsRedeemed || payload.pointsDiscount || payload.giftCards?.length) throw new Error('Only simple cash orders may queue');
    const allowed = new Set(['paymentMethod', 'items', 'orderType', 'tableNumber', 'walkInName', 'location', 'cashier']);
    if (Object.keys(payload).some(key => !allowed.has(key)) || !Array.isArray(payload.items) ||
        !payload.items.length || payload.items.length > 200) throw new Error('Unsupported cash order fields');
    for (const item of payload.items) {
      if (!item || typeof item.productId !== 'string' || !item.productId || item.productId.length > 160 ||
          !Number.isSafeInteger(item.quantity) || item.quantity < 1 || item.quantity > 9999 ||
          Object.keys(item).some(key => !['productId', 'quantity'].includes(key))) throw new Error('Unsupported cash order item');
    }
    const owned = structuredClone(payload);
    owned.clientOpId = this.id(); // generated once, durable BEFORE the first send
    return this.exclusive(async () => {
      if (!this.current(c)) throw new Error('Session changed');
      const rows = await this.rows(c.scope);
      const row = { id: owned.clientOpId, payload: owned, state: 'pending', attempts: 0, queuedAt: this.now(), nextAttemptAt: 0 };
      rows.push(row);
      await this.save(c.scope, rows);
      return structuredClone(row);
    });
  }
  list() {
    const c = this.context();
    return this.exclusive(async () => {
      const rows = await this.rows(c.scope);
      if (!this.current(c)) throw new Error('Session changed');
      return structuredClone(rows);
    });
  }
  flush() {
    const c = this.context();
    return this.exclusive(async () => {
      const rows = await this.rows(c.scope);
      for (const row of rows) {
        if (!this.current(c)) break;
        if (row.state === 'conflict' || row.nextAttemptAt > this.now()) break; // preserve order
        if (row.state === 'synced') continue;
        row.state = 'sending'; row.attempts++;
        await this.save(c.scope, rows);
        if (!this.current(c)) break;
        try {
          // send must pin authentication to expectedScope, recheck it immediately
          // before dispatch, and reject account changes (never read "current token").
          const result = await this.send(structuredClone(row.payload), { expectedScope: c.scope });
          if (!result?.id || result.businessId !== JSON.parse(c.scope)[0]) throw Object.assign(new Error('Response scope mismatch'), { status: 409 });
          row.state = 'synced'; row.serverId = result.id; row.lastError = null;
        } catch (error) {
          const status = error.status || error.response?.status;
          row.state = status && status < 500 && status !== 429 ? 'conflict' : 'retry';
          row.lastError = status ? `HTTP_${status}` : 'NETWORK_OR_UNKNOWN'; // no payload/token/error text logging
          row.nextAttemptAt = this.now() + Math.min(300000, 1000 * 2 ** Math.min(row.attempts, 8));
          await this.save(c.scope, rows);
          break;
        }
        await this.save(c.scope, rows);
      }
    });
  }
}
module.exports = { CashOrderQueue, scopeKey };
