// Offline-first queue for POS sales. Regional AU connectivity drop-outs mean
// a till losing its connection mid-service is a real, expected event — not
// an edge case. When a sale can't reach the server because the network
// itself failed (not because the server rejected it), the sale is queued
// locally in IndexedDB instead of being lost, and flushed automatically the
// moment connectivity returns.
//
// Scope: transaction creation only (the standard cash/card checkout path).
// Payment methods that inherently require a live gateway round-trip
// (QR/UPI confirmation, Stripe redirect, split payments) can't complete
// offline regardless of this queue and are left as-is.
import { transactionsAPI } from '../services/api';
import { trackEvent } from './telemetry';

const LEGACY_DB_NAME = 'nua-offline';   // pre-partitioning name — see activate() below
const DB_VERSION = 3;   // v2 added the coursing action store; v3 adds the read-side cache
const STORE = 'pending_transactions';
const COURSE_STORE_NAME = 'pending_course_actions';
const CACHE_STORE = 'cached_reads';   // menu + open tickets, so the POS has something to render offline

// A single shared IndexedDB database meant a device used for two different
// businesses (a multi-venue consultant's own tablet, say) would share one
// offline queue across both — queued sales, cached menus, everything. Not
// hypothetical: named explicitly in MOBILE_DESKTOP_BACKLOG.md as a real,
// unaddressed gap. AuthContext calls activate(businessId) the moment a real
// session exists (and lock() on logout/sign-out failure) so every call
// below operates on that business's own database, never a shared one.
let currentBusinessId = null;
const migratedBusinessIds = new Set();

function dbNameFor(businessId) {
  return businessId ? `nua-offline-biz-${businessId}` : LEGACY_DB_NAME;
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

function openDB() {
  return openNamedDB(dbNameFor(currentBusinessId));
}

async function readAllFrom(db, storeName) {
  if (!db.objectStoreNames.contains(storeName)) return [];
  return new Promise((resolve) => {
    const req = db.transaction(storeName, 'readonly').objectStore(storeName).getAll();
    req.onsuccess = () => resolve(req.result || []);
    req.onerror = () => resolve([]);
  });
}

async function moveAllTo(sourceDb, targetDb, storeName) {
  const rows = await readAllFrom(sourceDb, storeName);
  if (!rows.length) return;
  await new Promise((resolve, reject) => {
    const tx = targetDb.transaction(storeName, 'readwrite');
    const store = tx.objectStore(storeName);
    for (const row of rows) store.put(row);
    tx.oncomplete = resolve;
    tx.onerror = () => reject(tx.error);
  });
  await new Promise((resolve, reject) => {
    const tx = sourceDb.transaction(storeName, 'readwrite');
    tx.objectStore(storeName).clear();
    tx.oncomplete = resolve;
    tx.onerror = () => reject(tx.error);
  });
}

/**
 * Switch every queue/cache operation in this module onto the given
 * business's own database. Whichever business activates FIRST on a given
 * device, after this change ships, claims anything still sitting in the
 * old shared database (a queued sale from an outage that was still
 * in-flight across the exact deploy boundary — narrow, but real: dropping
 * it would violate this codebase's "never silently lose a queued
 * financial transaction" rule everywhere else). Every business after the
 * first gets a clean, empty, correctly-scoped database, same as always.
 * Safe to call repeatedly with the same businessId (no-ops after the first
 * migration this session).
 */
export async function activate(businessId) {
  if (!businessId || currentBusinessId === businessId) return;
  currentBusinessId = businessId;
  if (migratedBusinessIds.has(businessId)) return;
  migratedBusinessIds.add(businessId);
  try {
    const legacyDb = await openNamedDB(LEGACY_DB_NAME);
    const hasAnything = (await readAllFrom(legacyDb, STORE)).length
      || (await readAllFrom(legacyDb, COURSE_STORE_NAME)).length;
    if (!hasAnything) return;
    const targetDb = await openNamedDB(dbNameFor(businessId));
    await moveAllTo(legacyDb, targetDb, STORE);
    await moveAllTo(legacyDb, targetDb, COURSE_STORE_NAME);
  } catch { /* best-effort — a failed migration must never block the real queue from working */ }
}

/** Called on logout — stops any further read/write from resolving against
 * whichever business was last active, so a fast account switch on a
 * shared device can't read or flush the previous session's queue. */
export function lock() {
  currentBusinessId = null;
}

async function withStore(mode, fn) {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, mode);
    const store = tx.objectStore(STORE);
    const result = fn(store);
    tx.oncomplete = () => resolve(result);
    tx.onerror = () => reject(tx.error);
  });
}

function genId() {
  return (typeof crypto !== 'undefined' && crypto.randomUUID) ? crypto.randomUUID() : `q-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export async function enqueueTransaction(payload) {
  const record = { id: genId(), payload, queuedAt: new Date().toISOString() };
  await withStore('readwrite', (store) => store.add(record));
  return record;
}

export async function getQueued() {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, 'readonly');
    const store = tx.objectStore(STORE);
    const req = store.getAll();
    req.onsuccess = () => resolve(req.result || []);
    req.onerror = () => reject(req.error);
  });
}

export async function removeQueued(id) {
  await withStore('readwrite', (store) => store.delete(id));
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
export async function createTransactionResilient(payload) {
  // Attached before the very first attempt, not only when queuing — a
  // request can succeed server-side and still count as a "network failure"
  // client-side if the response never makes it back (the connection drops
  // right after the server writes the sale). Without a clientOpId already
  // on the very first attempt, the retry that follows from the queue would
  // ring up a second, fully-effectuated duplicate sale; carrying the same
  // id from the first try means the backend's clientOpId dedup (see
  // backend/routes/transactions.py's create_transaction) recognizes the
  // retry as the same sale no matter which attempt actually landed.
  const withOpId = { ...payload, clientOpId: payload.clientOpId || genId() };
  try {
    return await transactionsAPI.create(withOpId);
  } catch (error) {
    if (!isNetworkFailure(error)) throw error;
    const record = await enqueueTransaction(withOpId);
    return {
      data: {
        id: `OFFLINE-${record.id.slice(0, 8)}`,
        total: (payload.items || []).reduce((s, i) => s + (i.price || 0) * (i.quantity || 1), 0),
        queuedOffline: true,
      },
    };
  }
}

// ── Coursing actions ──────────────────────────────────────────────────────
// A till that loses its connection mid-service still has to be able to send
// food and fire courses; those calls used to fail hard while the sale beside
// them queued happily. Same queue, same rules: only network-level failures
// are held, real rejections still surface.
const COURSE_STORE = COURSE_STORE_NAME;

async function withCourseStore(mode, fn) {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    if (!db.objectStoreNames.contains(COURSE_STORE)) { resolve(null); return; }
    const tx = db.transaction(COURSE_STORE, mode);
    const result = fn(tx.objectStore(COURSE_STORE));
    tx.oncomplete = () => resolve(result);
    tx.onerror = () => reject(tx.error);
  });
}

export async function getQueuedCourseActions() {
  const db = await openDB();
  return new Promise((resolve) => {
    if (!db.objectStoreNames.contains(COURSE_STORE)) { resolve([]); return; }
    const req = db.transaction(COURSE_STORE, 'readonly').objectStore(COURSE_STORE).getAll();
    req.onsuccess = () => resolve(req.result || []);
    req.onerror = () => resolve([]);
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
  try {
    return await run();
  } catch (error) {
    if (!isNetworkFailure(error)) throw error;
    const record = { id: genId(), kind, args, queuedAt: new Date().toISOString() };
    await withCourseStore('readwrite', (store) => store.add(record));
    return { data: null, queuedOffline: true, queuedKind: kind };
  }
}

async function replayCourseAction(row) {
  const { coursingAPI, kitchenAPI } = await import('../services/api');
  const a = row.args || {};
  switch (row.kind) {
    case 'sendToKitchen': return coursingAPI.sendToKitchen(a.payload);
    case 'addRound':      return coursingAPI.addRound(a.orderId, a.payload);
    case 'fire':          return kitchenAPI.fireCourse(a.orderId, a.course);
    case 'hold':          return kitchenAPI.holdCourse(a.orderId, a.course);
    case 'serve':         return kitchenAPI.serveCourse(a.orderId, a.course);
    case 'void':          return coursingAPI.voidItems(a.orderId, a.payload);
    case 'settle':        return coursingAPI.settle(a.payload);
    default: return null;   // unknown kind — drop rather than block the queue
  }
}

export async function flushCourseActions(onProgress) {
  const rows = await getQueuedCourseActions();
  for (const row of rows) {
    try {
      await replayCourseAction(row);
      await withCourseStore('readwrite', (store) => store.delete(row.id));
      onProgress?.((await getQueuedCourseActions()).length);
    } catch (error) {
      if (isNetworkFailure(error)) break;   // still offline — keep the rest
      // A real rejection on replay (the ticket was closed while we were away,
      // the course already fired) — drop it. Retrying forever would wedge
      // every later action behind one that can never succeed.
      trackEvent('sync_failure', { entity: 'course_action', kind: row.kind, status: error?.response?.status });
      await withCourseStore('readwrite', (store) => store.delete(row.id));
    }
  }
}

// ── Read-side cache: menu and open tickets ─────────────────────────────────
// The queue above only covers what a till *sends* while offline — it still
// couldn't show a menu to sell from, or the floor's open tickets, the moment
// it lost connectivity, because nothing cached what the server last said.
// A regional drop-out mid-service used to mean a blank product grid, not
// just a sale that queues quietly.
async function withCacheStore(mode, fn) {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(CACHE_STORE, mode);
    const result = fn(tx.objectStore(CACHE_STORE));
    tx.oncomplete = () => resolve(result);
    tx.onerror = () => reject(tx.error);
  });
}

async function readCache(key) {
  const db = await openDB();
  return new Promise((resolve) => {
    const tx = db.transaction(CACHE_STORE, 'readonly');
    const req = tx.objectStore(CACHE_STORE).get(key);
    req.onsuccess = () => resolve(req.result || null);
    req.onerror = () => resolve(null);
  });
}

async function writeCache(row) {
  try { await withCacheStore('readwrite', (store) => store.put(row)); }
  catch { /* best-effort — a cache write failing must never break the live path */ }
}

/**
 * The two halves of the pattern above, exposed separately for call sites
 * that already run their own parallel fetch (POSTerminal's initial load
 * fires eight requests via Promise.allSettled) rather than wanting this
 * module to make the network call itself: cache what succeeded, read back
 * what's cached when it didn't.
 */
export async function cacheCatalogue(products, categories) {
  await writeCache({ key: 'catalogue', products, categories, cachedAt: new Date().toISOString() });
}

export async function getCachedCatalogue() {
  const cached = await readCache('catalogue');
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
  try {
    const [products, categories] = await Promise.all([fetchProducts(), fetchCategories()]);
    await writeCache({ key: 'catalogue', products, categories, cachedAt: new Date().toISOString() });
    return { products, categories, offline: false, cachedAt: null };
  } catch (error) {
    if (!isNetworkFailure(error)) throw error;
    const cached = await readCache('catalogue');
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
  try {
    const tickets = await fetchTickets();
    await writeCache({ key: 'tickets', tickets, cachedAt: new Date().toISOString() });
    return { tickets, offline: false, cachedAt: null };
  } catch (error) {
    if (!isNetworkFailure(error)) throw error;
    const cached = await readCache('tickets');
    return { tickets: cached?.tickets || [], offline: true, cachedAt: cached?.cachedAt || null };
  }
}

let syncing = false;
export async function flushQueue(onProgress) {
  if (syncing) return;
  syncing = true;
  try {
    const rows = await getQueued();
    for (const row of rows) {
      try {
        await transactionsAPI.create(row.payload);
        await removeQueued(row.id);
        onProgress?.(await countQueued());
      } catch (error) {
        if (isNetworkFailure(error)) break; // still offline — stop, retry later
        // A real rejection on retry (e.g. stale data) — drop it rather than
        // block the queue forever; nothing silently retries an invalid sale.
        trackEvent('sync_failure', { entity: 'transaction', status: error?.response?.status });
        await removeQueued(row.id);
      }
    }
    // Sales first: a queued fire refers to a ticket a queued send created.
    await flushCourseActions(onProgress);
  } finally { syncing = false; }
}
