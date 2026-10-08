# Collaboration handoff — Emergent / Codex

GitHub (branches, commits, PRs) is the coordination mechanism between the two
agents working this repo. Neither agent has a direct channel to the other;
this file plus PR descriptions are how context carries over. Keep both
sections below current when you touch this repo — do not delete the other
agent's section, and do not edit files the other agent owns without saying so
here first.

## File ownership (to avoid conflicting edits)

| Area | Owner | Notes |
|---|---|---|
| `backend/routes/auth.py` seeding/login/2FA/reset | Emergent (this pass) | Owner-recovery endpoints added 2026-10-02. Codex: coordinate before touching `seed_admin`/`_insert_seed_user`. |
| `backend/services/booking_sync.py` | Shared as of 2026-10-02 | Codex owns delivery logic (`deliver_next`/`drain`); Emergent added the `run_loop` param so Vercel can skip the perpetual loop — coordinate before changing `start_worker`'s signature again. |
| `bookings-api/*` | Codex | Untouched by this pass. |
| `backend/services/nua_scheduler.py`, `coursing_scheduler.py`, `backup_scheduler.py`, `cron_jobs.py`, `routes/cron.py` | Emergent (2026-10-02) | New Vercel-cron entry points — see this section below. |
| `docs/VERCEL_ONLY.md`, `docs/DEPLOYMENT_READINESS.md` | Shared | Append, don't rewrite — both agents have standing context in these. |
| `frontend/src/pages/OwnerRecovery.jsx`, `/owner-recovery` route | Emergent | New, not linked from Login.jsx by design. |
| `vercel.json` `crons` array | Emergent (2026-10-02) | Coordinate before adding/removing entries — paths must match `routes/cron.py`. |
| `scripts/smoke_test_live_edge.py` | Emergent (2026-10-02) | New, standalone — no dependency on either agent's in-flight work. |
| Everything else | Whoever's PR chain currently owns it | See open PR list below before editing a file already in flight. |

## Emergent section

### Branch: `emergent/owner-recovery`
Base: `codex/vercel-only` @ `9408629bf2710aa689dd4ab18394a54172c645ae` (the
last Codex commit on that branch at the time this work started — PR #5's
head, itself stacked on PR #4 → PR #3 → `main`, all still open/unmerged as of
this pass).

### What this pass found
- `backend/routes/auth.py`'s `login()` always compares on `req.email.lower()`.
  `seed_admin()` (as of `9408629`) stored `ADMIN_EMAIL` verbatim — any
  uppercase character in the Vercel value meant the seeded owner could never
  match a login attempt, independent of the password. Confirmed by
  reproduction in a local Mongo (seed with mixed-case email, login 401s;
  normalize, login succeeds) — not assumed.
- `9408629` had already fixed the separate "password gets reset on every
  cold start" bug (atomic `$setOnInsert` upsert in `_insert_seed_user`,
  replacing the old `elif not verify_password(...): update_one(...)` that
  used to silently revert a changed owner password on the next restart).
  That part did not need further changes.

### What changed
1. **`backend/routes/auth.py`** — `seed_admin()` now lowercases/strips
   `ADMIN_EMAIL` before use, and self-heals an existing owner whose stored
   email differs only in case (never touches password/role/status, never
   creates a second owner — case-insensitive match on `role: "owner"`, then
   a plain `$set` on `email`).
2. **`backend/routes/auth.py`** — new operator-only recovery flow:
   - `POST /auth/owner-recovery/initiate` `{recoveryKey, email}` → validates
     `recoveryKey` against the `OWNER_RECOVERY_KEY` env var
     (`hmac.compare_digest`), single shared lockout bucket (5 attempts / 15
     min — IP-keyed would be spoofable here, same reasoning as the existing
     login lockout's comment), rejects (409) if a different owner already
     exists under another email, bootstraps the owner if none exists yet,
     issues a 15-minute single-use token (only the sha256 hash is stored).
   - `POST /auth/owner-recovery/complete` `{token, password}` → atomic
     claim-once lookup (replay protection), sets the new password, clears any
     stale login lockout on that account.
   - Every attempt (success and failure) is written to
     `db.owner_recovery_audit` — never the token or password.
   - Both routes added to `PUBLIC_API_PATHS` in `backend/server.py` (they're
     necessarily pre-auth; gated by the recovery key inside the route, not by
     a session token).
3. **`frontend/src/pages/OwnerRecovery.jsx`** + `/owner-recovery` route in
   `App.js` + `authAPI.ownerRecoveryInitiate/Complete` in `services/api.js` —
   two-step UI (key+email → token+new password) so the new password is typed
   into a field, never pasted into a URL or chat.
4. Tests: `backend/tests/inprocess/test_owner_bootstrap.py` (+2 cases: email
   lowercasing, case self-heal without duplication) and new
   `backend/tests/inprocess/test_owner_recovery.py` (lockout, wrong-email
   rejection, full initiate→complete→login flow, single-use replay
   rejection, short-password rejection without consuming the token).
5. `backend/requirements.txt` — added `sentinels` (transitive dependency
   `mongomock` needed but the environment was missing; the in-process suite
   couldn't import `conftest.py` at all without it). Everything else in the
   diff is pip freeze noise from already-installed packages, not a version
   change I made intentionally.

### Verified
- Local reproduction: broke the owner's password hash directly in Mongo →
  confirmed `/auth/login` 401s → ran `/owner-recovery/initiate` with the
  wrong key (401, then 429 after 5 tries) → with the correct key (200, token
  issued) → `/owner-recovery/complete` (200) → login with the new password
  (200, role `owner`) → replaying the same token (400, rejected).
- Case-casing self-heal: manually renamed the seeded owner's email to mixed
  case in Mongo, restarted the backend, confirmed the log line
  `owner-bootstrap: normalized existing owner email casing to match
  ADMIN_EMAIL` and that exactly one `role: owner` document remained.
- `backend/tests/inprocess/` (830 tests, mongomock, no live DB needed): 826
  passed, 4 failed — **all 4 pre-existing and unrelated to this change**:
  `test_connect_square`/`test_crypto_payments` (status assertions that only
  hold when `STRIPE_API_KEY` is unset; this pod's `.env` has a test Stripe
  key), `test_reservations_tenant_isolation::...without_stripe_configured`
  (same cause), `test_financial_offline_integrity::...only_one_wins` (a
  mongomock-concurrency flake with no transaction support — the repo's own
  comments flag the real-Mongo-transaction suite as the authoritative check
  for that behavior). None touch `routes/auth.py`, `server.py`'s auth
  middleware, or anything this PR changed. I did not re-run the full "824
  backend tests" / CI claim from the problem statement — that was reported
  as historical and I'm not re-asserting it here without rerunning CI itself
  (see blockers below).
- Did **not** verify against the actual Vercel staging deployment or its
  real `ADMIN_EMAIL`/`ADMIN_PASSWORD`/Mongo data — I have no access to those
  values (by design) and no Vercel API token was provided this pass. The
  fix and recovery flow are verified against a local MongoDB reproducing the
  same code path, not against production state.

### Remaining blockers / not done this pass
- **Vercel env access**: no token provided — couldn't confirm whether
  `ADMIN_EMAIL`/`ADMIN_PASSWORD`/`FRONTEND_URL` are actually set on
  `nua-pos-staging`, or deploy this branch there. Operator needs to merge
  (or preview-deploy this branch), then set `OWNER_RECOVERY_KEY` in Vercel
  and run the two-step recovery flow against the real staging URL once.
- **SendGrid**: `SENDGRID_API_KEY`/`SENDGRID_FROM_EMAIL` deliberately not
  configured this pass (deferred per instruction) — `/forgot-password`
  silently no-ops without them (logs only, see `utils/notifications.py`).
  `FRONTEND_URL` save-state in Vercel was also never independently
  re-confirmed — do not assume either is set without checking Vercel
  directly.
- **PR chain**: this branch is based on `codex/vercel-only`, which is itself
  3 unmerged PRs deep (`#3 → #4 → #5`, all open). Merging mine doesn't move
  that chain forward; it's an additional PR against the same tip.
- Production readiness items from `docs/VERCEL_ONLY.md`/`DEPLOYMENT_READINESS.md`
  (durable background jobs, multi-instance realtime, distributed rate
  limiting, durable uploads/backups, live role/tenant/payment checks) are
  untouched — explicitly out of scope until owner access is confirmed
  restored on the real deployment.

### Branch: `emergent/durable-jobs-and-smoke-tests` (based on `emergent/owner-recovery`)
Second pass, same day. Scope: convert perpetual in-process schedulers to
Vercel-cron-safe endpoints, add a live multi-tenant/role/payment smoke test,
and set a working owner PIN. Follows PR #6 (owner-recovery) in the stack.

#### Durable background jobs
- New `services/cron_jobs.py`: `try_claim(job_name, ttl_seconds)` — atomic
  Mongo claim (`db.scheduler_locks`, upsert collides on `_id` if still
  locked, same pattern as `_insert_seed_user`), `release(job_name)` for jobs
  whose lock exists only to stop overlap, not to throttle cadence.
- New `routes/cron.py`: `GET/POST /api/cron/{ash-hourly,coursing-tick,
  backup-drill-check,booking-sync-drain}`. Each requires `Authorization:
  Bearer $CRON_SECRET` (the header Vercel Cron sends automatically when
  `CRON_SECRET` is set), then claims its lock and calls straight into the
  existing tick logic — `coursing_scheduler._tick_once()` and
  `backup_scheduler._maybe_run_drill()`/`drill_status()` were already
  reusable; `nua_scheduler`'s per-tick body was extracted into a new
  `run_tick_once()` so the in-process loop and the cron route share one
  implementation; `booking_sync.drain()` was already lease-based and safe
  to call concurrently.
- `server.py`: `IS_VERCEL = os.environ.get("VERCEL") == "1"` (Vercel sets
  this automatically in every deployment) gates the four perpetual
  `start_scheduler()`/`start_worker()` calls — skipped on Vercel, kept
  everywhere else (this pod's supervisor-managed process is long-lived, so
  the original design is still correct there). `repo_sync_scheduler` is
  also skipped on Vercel outright (it shells out to git against a local
  checkout — meaningless on Vercel's filesystem regardless of its own
  `REPO_SYNC_ENABLED` flag).
- `booking_sync.start_worker()` gained a `run_loop: bool = True` param —
  coordinate with Codex before changing that signature again (see
  ownership table above).
- `vercel.json`: added a `crons` array — `coursing-tick`/`booking-sync-drain`
  at `*/1 * * * *`, `ash-hourly` at `0 * * * *`, `backup-drill-check` at
  `0 3 * * *`.
- **Real, unresolved blocker — read before relying on this**: Vercel Hobby
  plan clamps cron to once a day; `*/1 * * * *` will not run as written
  unless `nua-pos-staging` is on Pro or higher. I did not verify which plan
  the project is on and would not upgrade it unilaterally even if I could —
  that's a cost decision for the operator. Until confirmed, coursing timing
  and booking-sync delivery are not actually durable on Vercel; they're
  only correctly *not crashing* (the in-process loops are safely skipped,
  cron will just run far less often than configured on Hobby).
- Tests: new `backend/tests/inprocess/test_cron_jobs.py` (5 cases — claim/
  release/race behavior, auth rejection, claimed-by-another-invocation,
  booking-sync-drain's immediate re-claimability). All passed.

#### Live smoke test
- New `scripts/smoke_test_live_edge.py` — standalone, run against any
  `SMOKE_BASE_URL` over real HTTP (not the mongomock in-process suite).
  Covers: health, owner login, manager/cashier role boundaries (owner-only
  report + staff list), a Stripe sandbox checkout session, and two-tenant
  customer-list isolation.
- **Tenant-isolation caveat, read before reusing this**: the live product
  has no self-service way to create a second, independently-owned tenant —
  `register()` always forces an enrolled staff account onto the enrolling
  owner's own `businessId` (see `routes/auth.py`), and `/business/create`
  adds a second business still owned by the *same* owner account, with no
  "switch active business" login path. The script's isolation section
  therefore needs direct Mongo access (`SMOKE_MONGO_URL`/`SMOKE_DB_NAME`) to
  flip a second staff account's `businessId` — exactly the same shortcut
  `tests/inprocess/*_tenant_isolation.py` already takes internally. Without
  Mongo access it still runs the role + payment sections, just skips
  isolation. A real operator-facing "provision a second tenant" admin
  endpoint would remove this caveat — not built this pass, noted as backlog.
- Run against the local preview edge (not yet the real Vercel URL — no
  access this pass): **19/19 checks passed**.

#### Owner PIN
- Set the owner's PIN to `0311` via the existing owner-authenticated
  `POST /auth/staff/{id}/set-pin` (no new code — this endpoint already
  existed). Verified `POST /auth/pin-login` with PIN `0311` returns the
  owner, locally. **This only touched the local pod's database** — the
  real `nua-pos-staging` owner's PIN is untouched; whoever has owner access
  there needs to set it themselves via Settings → Staff, or the same API
  call, once logged in.
- `memory/test_credentials.md` updated.

#### Not done this pass
- Re-ran `backend/tests/inprocess/` in full after all changes above: same
  4 pre-existing/environment-caused failures as the owner-recovery pass
  (Stripe-key-present assumptions, one mongomock-concurrency flake), 831
  passed (826 + the 5 new cron tests) — no regressions.
- Distributed rate limiting across multiple Vercel instances is unverified
  (this pod is one process; login/recovery lockout buckets live in Mongo
  so they're *shared* correctly in principle, but nothing here proves it
  under real concurrent cold starts).
- Multi-instance realtime fan-out (`services/realtime.py`,
  `routes/realtime.py`) untouched.
- Durable upload/backup storage (object storage vs. ephemeral function
  storage) untouched.

## Codex section

_(Codex: add your context here on your next pass — current open PRs at the
time of this handoff: #3 `platform-reliability→main`, #4
`deployment-readiness→platform-reliability`, #5 `vercel-only→deployment-readiness`,
all open/unmerged. #1 `trust-release/p0-security-foundation→main` merged
2026-09-20. #2 `vercel-staging→main` open, superseded by the #3-5 chain per
`VERCEL_ONLY.md`.)_

### Codex staging reliability pass — 2026-10-02
Working branch `codex/staging-reliability`, based on PR #7. Taking ownership
of shared rate limiting, dashboard realtime feed, private backup retention,
and upload durability audit. Also correcting PR #6's requirements freeze
regression (Vercel build cannot resolve emergentintegrations). Changes to
backup_scheduler/backup-drill cron will add durable backup retention before
restore verification; existing route names and schedules will remain.
Verified dashboard: sam-nua is Hobby. Minute AND hourly crons require Pro;
Hobby rejects these expressions at deployment, it does not clamp them.
Vercel Cron runs Production deployments only. No paid upgrade performed.

Also updating cron claim release to fence by invocation token: a slow, expired
booking-sync invocation must not release a newer invocation's lease.

Smoke script updates: read-only --health-only mode, generated test passwords,
explicit sandbox-payment prerequisite, and missing tenant coverage fails the
release gate instead of printing all checks passed. Full mutation mode still
needs a controlled staging run with cleanup verified.

Verification update: five-process real-Mongo proof passed (100 attempts, 25
allowed, cold restart preserves exhaustion, 50 unique cross-process events,
tenant isolation and cursor overflow). Full in-process suite: 843 passed and
one auth-sweep harness failure after the shared limiter correctly enforced
120/min. Fixed the sweep to reset only test counters per auth case; focused
rerun passed all 69 tests. Frontend production build passed; lint passed;
type gate remains 814/814 with no new error codes. Full Vercel cold-start,
Blob recovery and authenticated payment/role/tenant smoke remain release gates.
See `docs/STAGING_RELIABILITY_2026-10-02.md` for operational setup and limits.

The real staging CLI health smoke was attempted: all three readiness checks
failed because Vercel deployment protection returned a login redirect/HTML.
Add a securely supplied automation bypass secret for the CLI, keeping
deployment protection enabled; owner credentials alone are not sufficient.
