# Financial & offline integrity — remaining work

Tracks progress against P0.6/P0.7/P0.8 of the Trust Release directive
against the 5 gaps a read-only exploration of the payment, order, stock, and
offline-sync code paths found.

## Fixed in this pass

| Gap | Fix |
|---|---|
| Cumulative refund cap was read-then-write (two concurrent refund requests could both pass the cap check before either wrote, together exceeding the transaction total) | `POST /refunds` now claims the refund atomically on the original transaction document itself, via `find_one_and_update` with a `$expr` guard (`refundedTotal + amount <= total`, falling back to the legacy `db.refunds`-sum for the very first atomic claim against a transaction refunded before this field existed). MongoDB's own per-document serialization — not a Python-side check — decides which of two racing requests fits under the cap. |
| Online-order status transitions (`PATCH /online/orders/{id}/status`) were read-then-write: two near-simultaneous requests (two staff both accepting, or accept racing cancel) could both read the same pre-transition order, both pass every in-memory guard, and both apply side effects (double stock deduction), with whichever wrote last silently discarding the other's outcome | The transition is now claimed atomically first (`find_one_and_update` re-checking the order is still at the exact status this request read) before any side effects are computed. A request that loses the race gets a clean `409` instead of proceeding to recompute and clobber. Documented tradeoff: status now flips slightly before the derived side effects (stock, kitchen ticket, notifications) are persisted a few lines later — a process crash in that narrow window would leave status updated without those side effects applied. Judged strictly safer than the prior no-protection-at-all state; see "Deliberately out of scope" below for what a fully atomic version would need. |
| Stock decrements (POS sale, online-order accept, Ash's `mark_waste`) were unconditional `$inc`s with no floor — nothing stopped the stored count drifting arbitrarily negative under concurrent demand for the last unit(s) | Added `utils/stock_ops.clamp_negative_stock()`, called right after each of those three decrement paths: any product that ended up negative is clamped back to 0 in a follow-up bulk write. Deliberately does **not** block the sale/accept/waste-record that caused it — oversell was always an accepted POS scenario here (stale counts, walk-in demand), and refusing a sale for insufficient stock is a business-behavior change this pass didn't make. `routes/stock_transfers.py` was checked and already had a correct atomic `$gte`-guarded conditional decrement — no change needed there (the read-only exploration's report was wrong about this one file; verified directly by reading the code). |
| The offline queue's replayed sale (`POST /transactions`, the endpoint `frontend/src/lib/offlineQueue.js` actually posts to — not the separate, already-idempotent-but-unused `/v25/sync-queue` mechanism) had no dedup at all: a retry after a dropped response (the exact scenario the queue exists to survive) rings up a second, fully-effectuated duplicate sale | Added an optional `clientOpId` to `TransactionCreate`, a sparse-unique index on `transactions.clientOpId` (the actual atomic guard — MongoDB rejects the second insert, not a Python-side check), an early return-the-existing-transaction check before any side effects run (handles the common sequential-retry case), and a `DuplicateKeyError` catch at insert (handles the rarer genuinely-concurrent-duplicate case). Wired the frontend: `createTransactionResilient` now generates a stable `clientOpId` and attaches it to the payload *before* the very first attempt (not only when queuing), so a request that actually succeeded server-side but whose response never reached the client carries the same id on retry. |

Full backend suite re-verified green after every change above
(`python -m pytest tests/inprocess -q` — 492 passed, 0 failed). New tests
in `tests/inprocess/test_financial_offline_integrity.py` include two
genuine-concurrency tests (`ThreadPoolExecutor`, two real HTTP requests
in flight at once against the shared in-process test server) for the
refund cap and the clientOpId dedup; the online-order accept race test
found in practice that asyncio + mongomock's fake I/O rarely produces true
interleaving in this harness (each request tends to run close to
atomically), so it asserts the invariant that must hold regardless of
interleaving (stock deducted at most once) rather than a specific pair of
HTTP status codes.

## Deliberately out of scope for this pass

- **Stripe/Coinbase checkout-session idempotency** (area 1 of the original
  report). A double-click or client retry on "Pay with card" can still
  create two live Stripe Checkout Sessions / Coinbase charges for the same
  cart. Not fixed here — the natural fix (an idempotency key derived from
  the cart/order, checked against `db.payment_transactions` before calling
  out to Stripe/Coinbase) touches `routes/integrations.py`,
  `routes/online_orders.py`, `routes/bill_split.py`, and
  `routes/crypto_payments.py`/`services/coinbase_commerce.py` — a
  meaningfully larger, separate change than the four fixes above, and none
  of those four are prerequisites for it. Flagged as the next highest-value
  item in this area.
- **Crypto (Coinbase) refunds don't exist at all.** Cancelling a
  crypto-paid online order has no equivalent to `refund_stripe_payment` —
  the customer's money isn't automatically returned and (unlike the Stripe
  path) there's no `refund_failed` flag raised either, since
  `routes/online_orders.py`'s cancel-refund branch only ever looks for a
  Stripe session id. Coinbase Commerce doesn't expose a refund API the way
  Stripe does (settlement is typically manual off-platform), so this may
  need a different remedy (an explicit "refund pending — process manually"
  flag and staff notification) rather than a code-level automated refund.
  Needs a product decision on what "refunded" should even mean for a
  crypto payment before it can be implemented.
- **A fully atomic online-order status transition** (no crash window
  between the status claim and the side effects being persisted). Would
  need either a single aggregation-pipeline update that computes and writes
  status + all derived fields in one operation, or the same claim-with-a-
  staleness-window pattern `routes/integrations.py`'s
  `_finalize_pos_sale_if_applicable` already uses for its own claim/finish
  split. Not attempted here given the size of `update_status` (accept alone
  touches kitchen-ticket creation, ETA recomputation, and stock) and the
  real risk of introducing a new bug while restructuring it under time
  pressure — the 409-on-conflict version implemented here closes the
  concrete double-side-effect race without that larger rewrite.
- **Offline dedup for kitchen/coursing actions** (`pending_course_actions`
  in `offlineQueue.js`). Same "no client-op-id at all" gap as the sale
  queue had, but the consequence of a duplicate `fire`/`serve` call is
  generally more benign (most coursing endpoints are closer to idempotent
  by nature — re-firing an already-fired course tends to no-op) than a
  duplicate financial transaction, so this was judged lower priority and
  left as-is.
- **Playwright offline-mode E2E tests.** The directive calls for automated
  offline tests; this pass added backend-level dedup/race tests
  (`test_financial_offline_integrity.py`) but no browser-level test that
  actually drives a POS terminal through a simulated network drop, queues a
  sale, reconnects, and confirms exactly one transaction lands server-side.
  That would be the natural next step to actually exercise the frontend
  half of the clientOpId wiring end-to-end, not just the backend's half in
  isolation.
- **`services/settings.py`'s `POST /offline/sync`** and the legacy
  `frontend/src/services/offline.js` module — both appear to be dead code
  (no current caller found for either), left untouched rather than
  deleted since removing code that might have an undiscovered caller is
  higher-risk than leaving it inert.
