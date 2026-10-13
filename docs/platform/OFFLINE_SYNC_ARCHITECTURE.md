# Offline sync architecture

## The headline finding: this mostly already exists

`frontend/src/lib/offlineQueue.js` (pre-existing, not written this pass)
is a real, working, IndexedDB-backed offline-first implementation, already
wired into the actual checkout flow (`pages/POSTerminal.jsx:1010`'s
`createTransactionResilient` call) and already covered by
`hooks/useOfflineQueue.js`'s auto-flush-on-mount/online/30s-poll logic.
Per ADR-001, this pass **extends** it rather than replacing it — IndexedDB
works unchanged inside a Capacitor WebView, so most of what follows is
"verify it still holds on Android," not "build it for Android."

## What it already does

- **Durable local database**: IndexedDB, database `nua-offline`, three
  object stores — `pending_transactions` (sales), `pending_course_actions`
  (fire/hold/serve/send-to-kitchen calls), `cached_reads` (menu + open
  tickets, so the POS has something to render while offline, not just
  something to queue into).
- **Idempotency**: every queued transaction carries a `clientOpId`,
  attached *before* the very first network attempt (not only once queued)
  — so a request that actually succeeded server-side but whose response
  never made it back is recognized as a replay, not rung up twice. The
  server-side half of this contract (`backend/routes/transactions.py`'s
  `clientOpId` dedup check, `services/pos_sale_store.py`'s atomic
  transaction) was independently audited and fixed earlier in this
  session's launch-audit work (PR #18/#19) — this is the exact "shared,
  non-platform-specific contract" ADR-001 flags as not Windows- or
  Android-exclusive.
- **Network-failure detection**: `isNetworkFailure(error)` distinguishes
  "no response reached the client at all" (queue it) from "the server
  rejected it" (surface the real error — a validation failure, an
  insufficient-stock 400, must never be silently swallowed into a queue
  that will never succeed).
- **FIFO replay with real rejection handling**: course actions replay in
  order (firing a course before the ticket that owns it exists would
  fail); a real rejection on replay (the ticket was closed while offline)
  is dropped rather than retried forever and blocking everything queued
  after it.
- **Retry triggers**: `online` event, a 30-second poll (the audit's own
  comment notes `online` "doesn't always fire cleanly" — the poll is the
  real safety net), and on every app mount/restart.

## What "restart app → order survives" actually relies on

IndexedDB is durable storage, not memory — it survives a full app
process restart on every platform this matters for (web tab close/reopen,
Capacitor app kill/relaunch, Electron app restart). `useOfflineQueue`'s
`useEffect` calls `trySync()` unconditionally on mount, which is exactly
what makes "restart → reconnect → sync" work without any extra plumbing:
the queue doesn't know or care that a restart happened, it just finds
whatever's still in IndexedDB and tries to flush it, same as any other
mount.

## Data classification (per the master directive's own categories)

| Category | What | Mechanism |
|---|---|---|
| Offline-required | Active products/categories/modifiers, current price config, open tickets | `cached_reads` store (`cacheCatalogue`/`getCachedCatalogue`, `loadOpenTicketsResilient`) |
| Offline-required (write) | New sales, course fire/hold/serve/send actions | `pending_transactions` / `pending_course_actions` |
| Cacheable | Reservations, customers, loyalty summaries, reports | Not yet cached offline — reads fail hard without connectivity today. Not addressed this pass (see backlog). |
| Online-only | Payment methods needing a live gateway round-trip (QR/UPI confirmation, Stripe redirect, split payments), admin settings, payment-provider config | Deliberately excluded by `offlineQueue.js`'s own docstring — "left as-is," not a gap, a design boundary. |

## What this pass verified vs. what it didn't

**Verified** (real test runs, not assumed): the full backend suite
including the points-redemption/transaction-dedup tests passes (925/925);
the frontend build succeeds with the offline queue code included
unchanged; `indexedDB` is a standard Capacitor-WebView-supported API (no
code change needed for Android to use it).

**NOT verified this pass** (no Android SDK/emulator in this sandbox — see
`CURRENT_ARCHITECTURE_AUDIT.md`'s toolchain section): the actual
offline→kill-app→relaunch→reconnect→sync flow running on a real Android
WebView. The code path is identical to web's (same `lib/offlineQueue.js`,
same IndexedDB API), so there is no *code* reason to expect different
behavior, but "no code reason to expect a difference" is not the same
claim as "verified on-device," and this document does not pretend it is.

## Windows: a separate, scoped primitive — real, tested, not wired in

`packages/platform-core/queue.cjs`'s `CashOrderQueue` (built on
`feat/windows-foundation`, folded in here) is a *different* offline
primitive from `lib/offlineQueue.js` above, not a second implementation
of the same thing: it's deliberately narrower in scope, and was designed
before the shared `platform/electron/*` adapters existed to connect it to
anything.

- **Identity-scoped, not just stored**: every operation requires an
  `activate({businessId, userId, deviceId})` call first — there's no
  "current queue," only "the queue for this exact verified identity."
  Switching identity (`activate` again) or logging out (`lock()`)
  immediately invalidates any in-flight read/write for the old identity
  (`context()`/`current()`), including mid-flush — a `flush()` already
  running for business A stops replaying as soon as the app activates
  business B, even without waiting for the current attempt to finish.
- **Cash-only by contract, not by convention**: `enqueue()` throws for
  anything but a plain `paymentMethod: 'cash'` order with no
  `customerId`/`pointsRedeemed`/`pointsDiscount`/`giftCards`, and
  (tightened in a follow-up commit during this same session) an explicit
  field/shape allowlist on both the order and its items — no locally
  invented payment authorization, loyalty, or arbitrary extra fields can
  ever reach the queue, let alone replay from it.
- **Exactly-once replay, verified by test, not by inspection**: `clientOpId`
  is generated once and persisted *before* the first network attempt
  (`packages/platform-core/test/queue.test.cjs`'s "lost response then
  restart replays same ID and exactly one server order" test); a
  foreign-tenant or wrong-business response is never marked synced
  (`result.businessId !== JSON.parse(c.scope)[0]` → treated as a 409
  conflict, not success); parallel `flush()` calls serialize through one
  `exclusive()` queue rather than racing.
- **Durable, atomic, encrypted storage**: backed by the same
  `EncryptedStore` (temp-file-then-rename, real AES-GCM in its tests) used
  for the auth token — a failed write never silently drops a queued order,
  and a failed *encryption* (OS lock, DPAPI unavailable) leaves the
  previous value readable rather than corrupting it
  (`apps/windows/test/store.test.cjs`'s "failed encryption preserves
  previous value" test).

**What this is not, yet**: nothing in the real checkout flow calls
`CashOrderQueue` — `POSTerminal.jsx` still goes through
`lib/offlineQueue.js` on every platform, Windows included. Wiring it in
for real would mean deciding how it coexists with (or replaces) the
existing queue for cash orders specifically, migrating/quarantining
whatever's already sitting in a Windows install's `lib/offlineQueue.js`
IndexedDB store, and proving the exact same restart/reconnect/exactly-
one/foreign-tenant acceptance milestone above against it — explicitly
flagged in `SECURITY_MODEL.md` as deliberately not rushed this pass, not
forgotten.

## Backlog (see MOBILE_DESKTOP_BACKLOG.md for the full list)

- Capacitor's `Network` plugin (more reliable than `navigator.onLine` on
  some Android OEM WebViews) isn't yet wired into `useOfflineQueue`'s
  trigger — it still uses the web `online`/`offline` events plus the
  30-second poll, which should still work but hasn't been swapped to the
  more platform-correct signal (`platform/capacitor/NetworkService.js`
  already exists for this).
- Reservations/customers/loyalty reads have no offline cache — a dropout
  mid-service means those screens go blank, not stale-but-usable, the way
  the menu and open tickets already do.
- No storage-quota handling — if IndexedDB ever hits a platform-specific
  quota wall (more likely on iOS WebKit than Android per general web
  platform knowledge, not verified against this app's actual data volumes),
  there's no fallback/eviction policy.
