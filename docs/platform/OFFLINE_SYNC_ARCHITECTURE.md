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
