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
| `backend/services/booking_sync.py`, `bookings-api/*` | Codex | Untouched by this pass. |
| `docs/VERCEL_ONLY.md`, `docs/DEPLOYMENT_READINESS.md` | Shared | Append, don't rewrite — both agents have standing context in these. |
| `frontend/src/pages/OwnerRecovery.jsx`, `/owner-recovery` route | Emergent | New, not linked from Login.jsx by design. |
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

## Codex section

_(Codex: add your context here on your next pass — current open PRs at the
time of this handoff: #3 `platform-reliability→main`, #4
`deployment-readiness→platform-reliability`, #5 `vercel-only→deployment-readiness`,
all open/unmerged. #1 `trust-release/p0-security-foundation→main` merged
2026-09-20. #2 `vercel-staging→main` open, superseded by the #3-5 chain per
`VERCEL_ONLY.md`.)_
