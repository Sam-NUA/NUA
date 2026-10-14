// Offline-first queue for POS sales. Regional AU connectivity drop-outs mean
// a till losing its connection mid-service is a real, expected event — not
// an edge case. When a sale can't reach the server because the network
// itself failed (not because the server rejected it), the sale is queued
// locally in IndexedDB instead of being lost, and flushed automatically the
// moment connectivity returns.
//
// Scope: cash transaction creation only. Card/gateway uncertainty requires review.
// Payment methods that inherently require a live gateway round-trip
// (QR/UPI confirmation, Stripe redirect, split payments) can't complete
// offline regardless of this queue and are left as-is.
import { transactionsAPI } from '../services/api';
import { trackEvent } from './telemetry';
import { getSessionToken } from '../platform/sessionToken';

const DB_VERSION = 3;
const STORE = 'pending_transactions';
const COURSE_STORE_NAME = 'pending_course_actions';
const CACHE_STORE = 'cached_reads';
let currentBusinessId = null;
let activatedToken = null;
let epoch = 0;
function claims(token) {
  try { return JSON.parse(atob(token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/'))); }
  catch { return null; }
}
export function captureScope() {
  if (!currentBusinessId) throw new Error('Offline storage is locked');
  const token = getSessionToken();
  if (token !== activatedToken) {
    // A refresh may rotate the token for the same actor. A different tab's
    // login must never reuse this tab's previous business/menu/queue.
    const prior = claims(activatedToken), next = claims(token);
    if (!prior?.sub || next?.sub !== prior.sub || next?.businessId !== currentBusinessId) {
      throw new Error('Offline session changed');
    }
  }
  return { businessId: currentBusinessId, epoch, token };
}
export function assertScope(scope) {
  if (!scope || scope.epoch !== epoch || scope.businessId !== currentBusinessId
      || scope.token !== getSessionToken()) throw new Error('Offline session changed');
}
function scopedRequest(scope) {
  assertScope(scope);
  if (!scope.token) throw new Error('Offline replay requires an authenticated session');
  return { adapter: 'fetch', withCredentials: false,
    headers: { Authorization: `Bearer ${scope.token}`, 'X-Offline-Business-Id': scope.businessId },
    _offlineScope: () => assertScope(scope), _skipAuthRefresh: true };
}
function dbNameFor(businessId) {
  // Older shared AND first-login-migrated databases have unproven ownership.
  // Preserve them untouched for operator reconciliation; never auto-replay.
  return `nua-offline-v2-biz-${encodeURIComponent(businessId)}`;
}

function openNamedDB(name) {
  return new Promise((resolve, reject) => {
    if (!('indexedDB' in window)) { reject(new Error('IndexedDB unavailable')); return; }
    const req = indexedDB.open(name, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE)) {
        db.createObjectStore(STORE, { keyPath: 'id' });
      }
      if (!db.objectStoreNames.contains(COURSE_STORE_NAME)) {
        db.createObjectStore(COURSE_STORE_NAME, { keyPath: 'id' });
      }
      if (!db.objectStoreNames.contains(CACHE_STORE)) {
        db.createObjectStore(CACHE_STORE, { keyPath: 'key' });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function openDB(scope = captureScope()) {
  assertScope(scope);
  const db = await openNamedDB(dbNameFor(scope.businessId));
  try { assertScope(scope); } catch (error) { db.close(); throw error; }
  return db;
}

/** Only call with the business returned by a verified login/auth/me. */
export async function activate(businessId, token = getSessionToken()) {
  if (!businessId) { lock(); return; }
  if (businessId !== currentBusinessId || token !== activatedToken) epoch += 1;
  currentBusinessId = businessId;
  activatedToken = token;
}
export function lock() { epoch += 1; currentBusinessId = null; activatedToken = null; }

async function withStore(mode, fn, scope = captureScope()) {
  const db = await openDB(scope);
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, mode);
    const store = tx.objectStore(STORE);
    const result = fn(store);
    tx.oncomplete = () => { db.close(); resolve(result); };
    tx.onabort = () => { db.close(); reject(tx.error || new Error('Storage write aborted')); };
    tx.onerror = () => reject(tx.error);
  });
}

function genId() {
  return (typeof crypto !== 'undefined' && crypto.randomUUID) ? crypto.randomUUID() : `q-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export async function enqueueTransaction(payload, scope = captureScope()) {
  const record = { id: genId(), businessId: scope.businessId, payload, state: 'pending', queuedAt: new Date().toISOString() };
  await withStore('readwrite', (store) => store.add(record), scope);
  return record;
}

export async function getQueued(scope = captureScope()) {
  const db = await openDB(scope);
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, 'readonly');
    const store = tx.objectStore(STORE);
    const req = store.getAll();
    req.onsuccess = () => {
      try { assertScope(scope); resolve(req.result || []); } catch (error) { reject(error); }
      finally { db.close(); }
    };
    req.onerror = () => reject(req.error);
  });
}

export async function removeQueued(id, scope = captureScope()) {
  await withStore('readwrite', (store) => store.delete(id), scope);
}

export async function countQueued() {
  try { const rows = await getQueued(); return rows.length; }
  catch { return 0; }
}

// A network-level failure (no response reached the client at all) vs. a
// real server rejection (validation error, 409, etc.) — only the former
// should be queued; the latter must still surface to the cashier. Exported
// so a component can make the same call for reads (fall back to cache) that
// this file already makes for writes (queue and retry).
export function isNetworkFailure(error) {
  return !error.response && !!error.request;
}

/**
 * Wraps transactionsAPI.create with offline fallback. On a genuine network
 * failure, queues the sale and returns a synthetic response shaped like the
 * real one so existing calling code (which reads res.data.id/.total) keeps
 * working unchanged. Throws through any real server-side rejection as-is.
 */
function offlineCashEligible(payload) {
  return String(payload.paymentMethod).toLowerCase() === 'cash'
    && !payload.pointsRedeemed && !payload.pointsDiscount
    && !payload.isSplitPayment && !payload.paymentSplits?.length && !payload.splitDetails?.length
    && !payload.appliedDiscounts?.some(d => d.voucherId || d.code);
}
async function markForReview(record, error, scope) {
  await withStore('readwrite', store => store.put({ ...record, state: 'review',
    rejectionStatus: error?.response?.status || null }), scope);
}
export async function createTransactionResilient(payload) {
  const scope = captureScope();
  const withOpId = { ...payload, clientOpId: payload.clientOpId || genId() };
  // Persist cash intent BEFORE sending: a process kill after a lost response
  // must leave the same idempotency key available for replay.
  const record = offlineCashEligible(payload) ? await enqueueTransaction(withOpId, scope) : null;
  try {
    const response = await transactionsAPI.create(withOpId, scopedRequest(scope));
    assertScope(scope);
    if (record) await removeQueued(record.id, scope);
    return response;
  } catch (error) {
    assertScope(scope);
    if (record && !isNetworkFailure(error)) await markForReview(record, error, scope);
    if (!record || !isNetworkFailure(error)) throw error;
    return { data: { id: `OFFLINE-${record.id.slice(0, 8)}`, queuedOffline: true } };
  }
}

// ── Coursing actions ──────────────────────────────────────────────────────
// A till that loses its connection mid-service still has to be able to send
// food and fire courses; those calls used to fail hard while the sale beside
// them queued happily. Same queue, same rules: only network-level failures
// are held, real rejections still surface.
const COURSE_STORE = COURSE_STORE_NAME;

async function withCourseStore(mode, fn, scope = captureScope()) {
  const db = await openDB(scope);
  return new Promise((resolve, reject) => {
    if (!db.objectStoreNames.contains(COURSE_STORE)) { resolve(null); return; }
    const tx = db.transaction(COURSE_STORE, mode);
    const result = fn(tx.objectStore(COURSE_STORE));
    tx.oncomplete = () => { db.close(); resolve(result); };
    tx.onabort = () => { db.close(); reject(tx.error || new Error('Storage write aborted')); };
    tx.onerror = () => reject(tx.error);
  });
}

export async function getQueuedCourseActions(scope = captureScope()) {
  const db = await openDB(scope);
  return new Promise((resolve, reject) => {
    if (!db.objectStoreNames.contains(COURSE_STORE)) { resolve([]); return; }
    const req = db.transaction(COURSE_STORE, 'readonly').objectStore(COURSE_STORE).getAll();
    req.onsuccess = () => {
      try { assertScope(scope); resolve(req.result || []); } catch (error) { reject(error); }
      finally { db.close(); }
    };
    req.onerror = () => { db.close(); reject(req.error); };
  });
}

/**
 * Run a coursing call, queueing it if the network (not the server) failed.
 *
 * `kind` names the action so the flush knows how to replay it. Replay order
 * matters — firing a course before the ticket it belongs to exists would
 * fail — so the queue is strictly FIFO and stops at the first still-offline
 * error rather than skipping ahead.
 */
export async function courseActionResilient(kind, args, run) {
  const scope = captureScope();
  try {
    return await run(scopedRequest(scope));
  } catch (error) {
    if (!isNetworkFailure(error)) throw error;
    const record = { id: genId(), businessId: scope.businessId, kind, args, state: 'review', queuedAt: new Date().toISOString() };
    await withCourseStore('readwrite', (store) => store.add(record), scope);
    return { data: null, queuedOffline: true, requiresReview: true, queuedKind: kind };
  }
}

async function replayCourseAction(row, scope) {
  const config = scopedRequest(scope);
  const { coursingAPI, kitchenAPI } = await import('../services/api');
  const a = row.args || {};
  switch (row.kind) {
    case 'sendToKitchen': return coursingAPI.sendToKitchen(a.payload, config);
    case 'addRound':      return coursingAPI.addRound(a.orderId, a.payload, config);
    case 'fire':          return kitchenAPI.fireCourse(a.orderId, a.course, config);
    case 'hold':          return kitchenAPI.holdCourse(a.orderId, a.course, config);
    case 'serve':         return kitchenAPI.serveCourse(a.orderId, a.course, config);
    case 'void':          return coursingAPI.voidItems(a.orderId, a.payload, config);
    case 'settle':        return coursingAPI.settle(a.payload, config);
    default: throw new Error('Unknown queued action requires reconciliation');
  }
}

export async function flushCourseActions(onProgress, scope = captureScope()) {
  const rows = await getQueuedCourseActions(scope);
  for (const row of rows) {
    if (row.state === 'review') break;
    try {
      if (row.businessId !== scope.businessId) throw new Error('Queue ownership mismatch');
      await replayCourseAction(row, scope);
      await withCourseStore('readwrite', (store) => store.delete(row.id), scope);
      onProgress?.((await getQueuedCourseActions()).length);
    } catch (error) {
      if (isNetworkFailure(error)) break;   // still offline — keep the rest
      trackEvent('sync_failure', { entity: 'course_action', kind: row.kind, status: error?.response?.status });
      assertScope(scope);
      if (!row.state || row.state !== 'review') {
        await withCourseStore('readwrite', store => store.put({ ...row, state: 'review', rejectionStatus: error?.response?.status || null }), scope);
      }
      break; // Stop dependent actions; preserve them for reconciliation.
    }
  }
}

// ── Read-side cache: menu and open tickets ─────────────────────────────────
// The queue above only covers what a till *sends* while offline — it still
// couldn't show a menu to sell from, or the floor's open tickets, the moment
// it lost connectivity, because nothing cached what the server last said.
// A regional drop-out mid-service used to mean a blank product grid, not
// just a sale that queues quietly.
async function withCacheStore(mode, fn, scope = captureScope()) {
  const db = await openDB(scope);
  return new Promise((resolve, reject) => {
    const tx = db.transaction(CACHE_STORE, mode);
    const result = fn(tx.objectStore(CACHE_STORE));
    tx.oncomplete = () => { db.close(); resolve(result); };
    tx.onabort = () => { db.close(); reject(tx.error || new Error('Storage write aborted')); };
    tx.onerror = () => reject(tx.error);
  });
}

async function readCache(key, scope = captureScope()) {
  const db = await openDB(scope);
  return new Promise((resolve, reject) => {
    const tx = db.transaction(CACHE_STORE, 'readonly');
    const req = tx.objectStore(CACHE_STORE).get(key);
    req.onsuccess = () => {
      try { assertScope(scope); resolve(req.result || null); } catch (error) { reject(error); }
      finally { db.close(); }
    };
    req.onerror = () => { db.close(); reject(req.error); };
  });
}

async function writeCache(row, scope = captureScope()) {
  try { await withCacheStore('readwrite', (store) => store.put(row), scope); }
  catch { /* best-effort — a cache write failing must never break the live path */ }
}

/**
 * The two halves of the pattern above, exposed separately for call sites
 * that already run their own parallel fetch (POSTerminal's initial load
 * fires eight requests via Promise.allSettled) rather than wanting this
 * module to make the network call itself: cache what succeeded, read back
 * what's cached when it didn't.
 */
export async function cacheCatalogue(products, categories, scope = captureScope()) {
  await writeCache({ key: 'catalogue', products, categories, cachedAt: new Date().toISOString() }, scope);
}

export async function getCachedCatalogue(scope = captureScope()) {
  const cached = await readCache('catalogue', scope);
  return { products: cached?.products || [], categories: cached?.categories || [],
          cachedAt: cached?.cachedAt || null };
}

/**
 * Load the menu with an offline fallback. Tries the network first; on
 * success, refreshes the cache so the next drop-out has something recent to
 * fall back to. On a genuine network failure, returns whatever was cached
 * last, tagged with how stale it is — a real rejection (e.g. a 401) is
 * thrown through as-is rather than silently masked by stale data.
 *
 * For a call site that already runs its own fetch (see cacheCatalogue /
 * getCachedCatalogue above); this is the convenience wrapper for a simpler
 * caller that just wants "the menu, offline-safe" in one call.
 */
export async function loadCatalogueResilient(fetchProducts, fetchCategories) {
  const scope = captureScope();
  try {
    const [products, categories] = await Promise.all([fetchProducts(), fetchCategories()]);
    await writeCache({ key: 'catalogue', products, categories, cachedAt: new Date().toISOString() }, scope);
    assertScope(scope);
    return { products, categories, offline: false, cachedAt: null };
  } catch (error) {
    if (!isNetworkFailure(error)) throw error;
    const cached = await readCache('catalogue', scope);
    return {
      products: cached?.products || [],
      categories: cached?.categories || [],
      offline: true,
      cachedAt: cached?.cachedAt || null,
    };
  }
}

/**
 * Same shape, for the floor's open tickets — so a table-side view or the
 * kitchen board still shows the last-known state instead of going blank,
 * even though nothing can be marked fired/served until the connection is
 * back (those actions go through courseActionResilient's write queue).
 */
export async function loadOpenTicketsResilient(fetchTickets) {
  const scope = captureScope();
  try {
    const tickets = await fetchTickets();
    await writeCache({ key: 'tickets', tickets, cachedAt: new Date().toISOString() }, scope);
    assertScope(scope);
    return { tickets, offline: false, cachedAt: null };
  } catch (error) {
    if (!isNetworkFailure(error)) throw error;
    const cached = await readCache('tickets', scope);
    return { tickets: cached?.tickets || [], offline: true, cachedAt: cached?.cachedAt || null };
  }
}

let syncing = false;
export async function flushQueue(onProgress) {
  if (syncing) return;
  if (!currentBusinessId) return;
  const scope = captureScope();
  syncing = true;
  try {
    const rows = await getQueued(scope);
    for (const row of rows) {
      if (row.state === 'review') continue;
      try {
        if (row.businessId !== scope.businessId || !row.payload?.clientOpId || !offlineCashEligible(row.payload)) {
          throw new Error('Unsafe queued sale requires reconciliation');
        }
        await transactionsAPI.create(row.payload, scopedRequest(scope));
        await removeQueued(row.id, scope);
        onProgress?.(await countQueued());
      } catch (error) {
        if (isNetworkFailure(error)) break; // still offline — stop, retry later
        trackEvent('sync_failure', { entity: 'transaction', status: error?.response?.status });
        assertScope(scope);
        await markForReview(row, error, scope);
        break; // Preserve financial records; no blind retries of rejected sales.
      }
    }
    // Sales first: a queued fire refers to a ticket a queued send created.
    await flushCourseActions(onProgress, scope);
  } finally { syncing = false; }
}

export async function getQueueStatus() {
  try {
    const scope = captureScope();
    const sales = await getQueued(scope);
    const actions = await getQueuedCourseActions(scope);
    return { sales: sales.length, review: sales.filter(row => row.state === 'review').length + actions.filter(row => row.state === 'review').length };
  } catch { return { sales: 0, review: 0 }; }
}
