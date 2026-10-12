# Independent review of the 11 October 2026 launch audit (PR #17)

**Starting point:** `codex/launch-audit-owner-access` at `9f60d2dabe2c313e80ed2591223a47f16a52a5a8`
(PR #17's head, confirmed open/unmerged against base `codex/owner-access` at
`f150264a3b36f7e6f3aee26ecb7c6ee3f4bc66f6` before any work began). Review
branch: `codex/review-launch-audit-2026-10-11`, stacked on top, same base.
No merge, deploy, or Railway action performed. The branch disables its own
Vercel Git deployment (`vercel.json`'s `git.deploymentEnabled`).

This document is the independent-review counterpart to `REPORT.md`,
`VALIDATION.md` and `DEPENDENCIES.md` in this same directory (PR #17's own
audit). It does not repeat their content; it verifies it and extends the
work into the items PR #17 explicitly left open.

## Phase 1 — verification of PR #17's five fixes

All five were independently re-derived from the current code (not just the
PR description) and CONFIRMED FIXED, each with file:line evidence and an
existing regression test in `backend/tests/inprocess/test_launch_access_and_scope.py`:

1. **Fresh PIN tokens survive password recovery.** `staff_management.py`'s
   `_issue_staff_token` now calls the shared `create_access_token`, which
   sets `iat` — the old bespoke issuer didn't, so `_check_password_changed`
   saw every fresh PIN token as predating any `passwordChangedAt` and
   rejected it. Confirmed by `test_new_pin_token_works_after_password_change_and_old_one_is_revoked`.
2. **PIN/approval fail closed on 2FA.** `_require_pin_eligible` checks
   `two_factor.required_for(user)` before issuing a token, called from both
   `pin_login` and `approve_pin_login` (both the staff and manager side).
3. **Shared response sanitizer.** `public_user()` in `routes/auth.py`
   strips `_id`, `password_hash`, `pin`, `twoFactorSecret`,
   `twoFactorSecretPending`, `recoveryCodes` from every login/`/auth/me`
   response. One soft spot noted: the new test suite asserts this directly
   on the PIN-login path but not with an explicit field-by-field assertion
   on the password-login path — low risk since both paths share the same
   function, not zero.
4. **Tenant predicate carried into final writes.** Confirmed in
   `routes/kitchen.py`'s overnight cleanup, `routes/products.py`'s per-row
   bulk-edit/translation writes, with `test_bulk_price_write_cannot_update_another_tenants_duplicate_id`
   proving a duplicate `id` across two businesses only ever updates the
   caller's own row.
5. **Kitchen ticket creation rejects a foreign/unowned reservation.**
   `create_kitchen_order` now 404s before enrichment unless the reservation
   resolves inside `tenant_scope_filter`. Confirmed by
   `test_kitchen_rejects_foreign_and_unowned_reservations`.

## Phase 2 — tenant-isolation launch blockers (all four addressed)

### A. Kitchen docket settings (`routes/kitchen.py`)

**Root cause:** `_id: "singleton"` — one document, no `businessId`, shared
by every business on the deployment.

**Fix:** Switched to `services.tenant_settings.get_scoped_singleton`/
`set_scoped_singleton` — the exact helper `loyalty_config` and
`agent_autonomy` already use for this identical shape (a logical `match`
key plus a real `businessId` field, never the bare `_id`). The legacy
`_id: "singleton"` document is never read as a default and never written
to again; it is exposed read-only via a new
`GET /kitchen/docket-config/legacy-singleton-report` (owner/manager only)
so a human can review its contents and decide whether anything in it is
worth manually re-entering for their own business through the ordinary
`PUT`. No migration ran, dry-run or otherwise — this is a visibility tool,
not an assignment one, by design (the launch runbook's own rule: never
auto-assign an unowned legacy document to any business).

**Tests:** `test_kitchen_docket_tenant_scope.py` — two businesses get
independent configs, a fresh business gets defaults without touching the
legacy row, the legacy report surfaces it without adopting it, and both
write paths are role-gated. 6 tests, all new.

### B. Wallet vouchers (`services/wallet_service.py`)

**Root cause:** every function matched by `customerId` alone — no
`businessId` anywhere, including on the birthday-voucher documents
themselves.

**Fix:** Ownership now comes from the verified customer record's own
`businessId` (every caller already resolved `customer` from a
tenant-scoped query — this is the confirmed business, not a guess from a
potentially-ambiguous `customerId`). `ensure_birthday_voucher` stamps and
scopes its duplicate check by it; `expire_stale_vouchers`, `get_wallet`
and `redeem_wallet_voucher` all now take an explicit `business_id` and
apply `tenant_scope_filter` to every read/write, including
`redeem_wallet_voucher`'s compare-and-swap filter (defense in depth — the
caller in `transactions.py` already re-prices a foreign voucherId's
discount to $0 before redemption is ever attempted, but the function
itself had no ownership check of its own). A legacy voucher with no
`businessId` at all is left untouched by all of this rather than guessed
at; `vouchers` is already in `services/ownership_migration.py`'s
`MIGRATABLE_COLLECTIONS`, so the existing dry-run-first, evidence-based
workflow (`/api/admin/ownership-migration/{scan,run}/vouchers`) is the
correct path to resolve them — no new migration tooling was built, and
none ran.

**Tests:** `test_wallet_voucher_tenant_scope.py` — duplicate-customerId
birthday-voucher issuance (business A's voucher is never read as "already
issued" for business B's customer of the same id), an unowned customer is
skipped entirely, wallet listing ignores a stray mis-tagged voucher,
cross-tenant redemption is rejected, and expiry only ever touches the
caller's own business, never a legacy unowned row. 5 tests, all new
(plus an existing concurrency test file updated to pass the now-required
`business_id`, since it called the function directly below the HTTP layer).

### C. Related cross-tenant references

- **`routes/channel_menus.py`'s `patch` endpoint** accepted a `productId`
  with no ownership/existence check. Now 404s on a foreign or nonexistent
  product before writing the override. 2 new tests.
- **`routes/channel_menus.py`'s `ai_prep_times`** ("channel heat") counted
  `db.kds_orders` — traced and confirmed dead: nothing in the codebase
  writes that collection (`grep -rn "kds_orders"` returns exactly the one
  read site). Live tickets are `kitchen_orders` (`routes/kitchen.py`).
  Fixed to read the real collection with the same active-ticket statuses
  `kitchen.py`'s own queue-depth calculation uses. 1 new test proving heat
  now actually responds to real ticket volume.
- **`routes/reservations.py`'s create/update** accepted a client-supplied
  `customerId`/`tableId` belonging to another business, or nonexistent,
  without rejecting it — silently no-opping the bookkeeping side effect
  while still storing the raw id on the reservation. Same gap in waitlist
  entry updates for `tableId`. All four paths now validate up front and
  404 before any write; `services/floor_tables.get_table_by_id` gained an
  explicit `business_id` parameter rather than relying only on ambient
  actor context. 6 new tests across both files.

### D. Public waitlist tracking

Reviewed per the audit's own open items:
- **Code entropy:** the tracking code is the waitlist entry's own `id` —
  8 uppercase hex characters from a truncated `uuid4`, ~32 bits.
- **Exposure:** `_public_waitlist_view` already returns a redacted subset
  (no phone, no `businessId`, no notes/preferences/priority) — no change
  needed.
- **Rate limiting:** the endpoint had only the generic 120/min-per-IP
  default — not tuned for a 32-bit code's enumeration risk, unlike
  `/api/public/join-waitlist`'s own (10, 60) tier. Added the same (10, 60)
  `PREFIX_OVERRIDES` tier to `server.py` for `/api/waitlist/track`, covering
  both the point lookup and the SSE stream. 1 new rate-limit test.
- **Stream lifetime:** already capped at `WAITLIST_SSE_MAX_SECONDS` (600s)
  — no change needed.

No product-policy decision was made to change the guest contract itself
(public code-based tracking stays public, by design); the fix only
tightens the existing rate-limit posture to match a comparable endpoint
already on this tier.

## Phase 3 — financial correctness

**Traced:** the full POS sale path (`routes/transactions.py`), points
redemption, voucher/discount capping, stock/recipe deduction, GL
auto-post, and the offline-queue `clientOpId` dedup.

**Confirmed and fixed:** points redemption is an atomic decrement that
happens *before* the sale is inserted (REPORT.md's own flagged risk). If
the insert then failed for any reason, or lost a genuinely concurrent
same-`clientOpId` race, the customer had already been charged points for a
sale that was never recorded as theirs — a silently lost balance on
failure, or a silently doubled one on the losing side of a race (since
only the winner's transaction, with its own separately-accounted
redemption, survives). Added a compensating refund, tracked per
`_redeem()` call and reversed whenever the insert doesn't end up being this
attempt's own recorded transaction. This is a compensating action, not a
real multi-document ACID transaction — proving that needs a real MongoDB
replica set, which this sandbox has no access to (see below). 2 new
tests, deterministically simulating both failure modes (mongomock has no
genuine suspend point for true concurrency, same limitation the existing
`test_wallet_voucher_redemption_concurrency.py` already documents).

**Investigated, found already correct:** stock/recipe deduction happens
*after* the insert (the right order — never decrement inventory for a sale
that was never recorded), with existing best-effort error logging on
failure. This is a known, already-documented trade-off (REPORT.md: "Some
paths catch voucher/recipe/notification errors and continue"), not a new
finding.

**Not independently verifiable here, documented as a launch blocker:**

- Real multi-document transaction/rollback guarantees across the sale
  insert + its side effects. Mongomock cannot prove atomicity either way.
- Stripe webhook crash/replay and partial side-effect recovery under fault
  injection against a real provider sandbox.
- A recorded "Card" tender or QR confirmation is not provider-verified
  settlement — unchanged from the original audit's own finding.

This sandbox has no Docker daemon (`docker ps` fails: no such socket) and
no `mongod`/MongoDB packages available (not resolvable via `apt`), so
`.github/workflows/transactions.yml`'s real-replica-set suite
(`backend/tests_real`, `bookings-api/tests_real`, requiring
`docker run mongo:7 --replSet ...`) could not be run or independently
reproduced in this review. This is an environment limitation, not a
finding that the suite is broken — it is unchanged from this review's base
and needs CI (which already passed it per PR #17's description) or a
local Docker-capable environment.

## Phase 4 — authentication and operational reliability

| Item | Disposition |
|---|---|
| PIN brute-force throttling | **Fixed.** No throttling existed beyond the generic 120/min/IP default — enough headroom to sweep a meaningful slice of a 2-4 digit PIN's keyspace. Added the same account-keyed lockout shape `routes/auth.py`'s password/2FA login already uses (5 attempts, 15 min), keyed on the PIN value itself. 3 new tests. |
| Venue timezone/DST in roster checks | **Fixed.** `_is_rostered_now` compared a shift's venue-local `startTime`/`endTime` against the server's UTC wall clock directly. Now uses `services/venue_time.py`'s existing `venue_now_for_business` (already used for bookings/cancellation windows) — no new helper invented. 2 new tests, one updated existing test whose own setup assumed UTC. |
| `/auth/me` transient-failure session clearing | **Fixed.** Frontend `AuthContext` cleared the token on *any* `/auth/me` failure, including a network blip or backend 5xx. Now only a real 401/403 clears it; anything else gets one short retry and never deletes an otherwise-valid token. Verified by code review and a clean production build; no frontend unit-test harness exists in this repo to add an automated regression test cheaply (no `@testing-library/react` dependency) — noted rather than silently skipped. |
| Vercel Cron health vs. disabled local loops | **Fixed.** `check_health()` reported the local in-process scheduler's `is_running()`, which is correctly `False` on Vercel (the loop is never started there) — making `/api/health` report "degraded" permanently on Vercel regardless of whether Cron was actually firing. Now reads `cron_jobs`' own claim recency on Vercel instead. 4 new tests. |
| Global PIN namespace (two businesses can't share a PIN) | **Left open, documented.** Confirmed a correctness/UX limitation, not a security hole — `_unique_pin_user` matches globally and a collision is denied (401), never silently resolved to the wrong business; the matched user's own `businessId` always mints the token. Fixing the UX (scoping PINs per business) needs a product decision on how an unauthenticated PIN pad identifies "which business" in the first place — out of scope for a unilateral code change. |
| Plaintext PIN storage | **Left open, documented.** Confirmed: `auth_users.pin` is plaintext everywhere it's written. A hashing migration needs a compatibility strategy (existing PINs, any UI that currently assumes a readable value) — a design decision, not a mechanical fix, consistent with the original audit's own "separate authentication design review" framing. |

## Phase 5 — dependencies and static checks (all reproduced)

| Check | Result |
|---|---|
| `cd backend && python -m flake8 .` | Exit 0, no findings |
| `python scripts/check_type_baseline.py` | Pass: 289 findings vs. accepted baseline 814, no new error categories |
| `python scripts/check_dependency_baseline.py` | Pass: 0 advisories across 0 packages (resolver-based gate — same known incomplete-transitive-coverage limitation DEPENDENCIES.md already flags; not treated as a clean bill of health on its own) |
| `pip-audit -r requirements.txt --no-deps --disable-pip` | 0 advisories across 117 pinned packages — matches the original audit exactly |
| `npm audit` (frontend) | 129 affected entries: 4 critical, 81 high, 39 moderate, 5 low — matches the original audit exactly; unchanged, since no dependency version was touched in this review |
| Frontend production build (`CI=false yarn build`) | Success, zero compiler errors |
| `gitleaks detect` — full history (120 commits reachable in this checkout) | 2 matches, both the same already-documented legacy test fixture (`backend/tests/test_iteration6_features.py:179`, `TEST_API_KEY_12345`) — no live credential, no new finding |
| `gitleaks detect` — this review's own 4 commits only | 0 matches |

No dependency version was changed in this review (Axios was already
updated to 1.20.0 by PR #17). No ignore/baseline was widened in any of the
checks above.

## Phase 6 — end-to-end validation

| Suite | Command | Result |
|---|---|---|
| Backend | `cd backend && python -m pytest tests/inprocess -q` | **900 passed, 0 failed** (870 at this review's starting point) |
| Bookings | `cd bookings-api && python -m pytest tests -q` | **35 passed, 0 failed** — matches the original audit exactly |
| Playwright | `cd frontend && npx playwright test` | **9 passed, 0 failed** (5 at this review's starting point) |
| Real MongoDB replica-set suite | `python -m pytest backend/tests_real bookings-api/tests_real -q` against a `mongo:7 --replSet` container | **Not run** — no Docker daemon in this sandbox (see Phase 3) |

New Playwright coverage added beyond the existing golden-path suite
(password login/rejection, PIN recovery, POS card sale, guest order
tracking):
- **2FA enforcement** (`two-factor.spec.js`): a freshly 2FA-enrolled
  account cannot sign in on password alone, a wrong code is rejected, and
  the correct code (from a fresh TOTP step, past the enrolment code's own
  anti-replay burn) succeeds — all driven through the real `Login.jsx` UI.
- **Reservation foreign-reference rejection** (`tenant-settings-and-reservations.spec.js`):
  this review's own `routes/reservations.py` fix, exercised over the real
  HTTP stack.
- **Tenant-specific settings / wallet reachability**: the kitchen docket
  config and customer wallet endpoints, exercised through a real signed-in
  browser session. Cross-business isolation itself is left to the backend
  suite's own two-tenant fixtures — this app has no browser-reachable way
  to stand up an independent second tenant outside the authenticated
  provisioning workflow in `docs/OWNER_ACCESS.md`, so proving that
  isolation here would need a database-level shortcut no real browser
  session has.

Isolated test data throughout (fresh UUIDs, dedicated test businesses);
no production data, live credentials, real payment, or real notification
channel touched. No existing test was skipped, weakened, or had an
assertion removed — one existing concurrency test and one existing roster
test were updated to pass a parameter/use a timezone the underlying fix
now actually requires, both reviewed above.

## Deliberately untouched, and why

- **Global PIN namespace** and **plaintext PIN storage** — documented
  above; need a product/design decision, not a unilateral code change.
- **Real multi-document transaction atomicity** for the POS sale path —
  needs a real MongoDB replica set this sandbox cannot provide; the
  compensating-refund fix in Phase 3 is the independently safe part that
  could be done without one.
- **Stripe webhook fault-injection against a real provider** — needs
  Stripe sandbox/provider access this sandbox does not have.
- **Desktop/Electron tooling dependency debt** (the 129 npm audit
  entries) — all confirmed, in the original audit and re-confirmed here,
  absent from the emitted browser bundle; a desktop-release decision, not
  a web-launch blocker. Untouched, consistent with the original audit's
  own scope boundary.
- **Legacy kitchen-docket singleton and any pre-existing unowned
  vouchers** — never auto-assigned to any business, per the launch
  runbook's explicit rule. A human reviews the new legacy-docket report
  endpoint, or the existing ownership-migration workflow, and decides.

## Tasks that need Sam, provider access, or physical hardware

- Running the real-MongoDB replica-set suite (or trusting CI's own run of
  it) to actually prove the sale-insert/redemption atomicity question in
  Phase 3 beyond the compensating-refund mitigation.
- A Stripe sandbox fault-injection pass on webhook crash/replay handling.
- Deciding the product question behind the global PIN namespace (how does
  an unauthenticated terminal know "which business" before a PIN even
  matches?) and committing to a PIN-hashing migration/compatibility plan.
- Real terminal/printer/cash-drawer, card/refund, offline-reconnect, email
  delivery, and scheduled-job (Vercel Cron in production) verification —
  unchanged from the original audit's own list; nothing in this review
  changes what those still need.

## Launch recommendation

Every tenant-isolation launch blocker the original audit left open under
"Deliberately untouched / launch risks" (kitchen docket singleton, wallet
voucher ownership, the `channel_menus` productId/kds_orders findings, the
reservation/waitlist foreign-reference gap, PIN brute-force throttling,
venue-timezone roster checks, and the Vercel Cron health signal) now has a
code fix and a regression test, and the full backend, Bookings, and
Playwright suites are green. The points-redemption-before-insert risk has
an independently-safe compensating mitigation, not a full fix — real
multi-document atomicity still needs a real replica set this review could
not reach. The global PIN namespace and plaintext PIN storage are real,
previously-known gaps that remain open because closing them needs a human
product/design decision this review is not positioned to make
unilaterally, not because they were missed.

This is not a claim of launch readiness on its own: the Stripe
fault-injection, real-replica-set, and physical-hardware items above are
still outstanding, and the frontend's 129 tooling/desktop dependency
entries remain exactly as triaged by the original audit. What changed
here is that every multi-tenant data-isolation gap the original audit
explicitly flagged as a blocker is now closed, tested, and reproducible —
not merely described.
