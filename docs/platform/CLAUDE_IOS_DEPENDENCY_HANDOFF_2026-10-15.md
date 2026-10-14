# Claude handoff — iOS financial acceptance and frontend dependency remediation

Repository: `Sam-NUA/NUA`. Start from the latest `fix/terminal-session-durability`
review branch, including its stacked parent `fix/mobile-isolation-review`.
Read the current reports and this branch's final validation before editing.
Create a separate review branch and draft PR; do not merge, deploy, change
production configuration, or touch Railway.

## Ownership boundaries

Codex owns `backend/routes/auth.py`, `backend/routes/staff_management.py`,
`backend/services/device_auth.py`, device/session middleware and tests,
`frontend/src/contexts/AuthContext.jsx`, `frontend/src/services/api.js`,
`frontend/src/services/terminalSession.js`, device adapters, shared offline
queue/hooks and `apps/windows/**` / Windows workflow.

Claude can independently own:

1. `.github/workflows/ios.yml`, new iOS-specific acceptance scripts/tests,
   necessary iOS test-target wiring, and `docs/platform/IOS*` acceptance notes.
2. Frontend dependency/lockfile remediation and retirement of the unsupported
   legacy `frontend/electron/` build path. Do not change the supported
   `apps/windows` host or its dependencies without coordinating first.

If either task needs a Codex-owned file, report the required contract change
and keep it in a separate commit for review. Preserve unrelated edits.

## iOS task

The existing iOS job proves build, simulator install and five-second process
survival. It does not prove financial/offline behaviour. Build real iOS
simulator UI acceptance using the actual Capacitor app and real FastAPI routes
against a throwaway backend/database. WebKit/XCUITest/Appium tooling may be
needed; Android's CDP driver is not an iOS acceptance implementation.

Prove password login, PIN where policy permits, first-session device binding,
cash checkout, a real connection outage (including old keep-alive sockets),
durable pending record, process termination/restart while offline, blocked
protected screens until server re-verification, reconnection and exactly one
server transaction with the same nonempty `clientOpId` and correct `businessId`.
Also prove business A's pending records are inaccessible during business B's
session, and owner revocation rejects the existing bound session and refresh.

Current contract: native AuthContext registers/binds before queue activation;
`POST /auth/bind-device` binds the session immediately. `X-Device-Map` is a
business→device routing hint; only the server selects and verifies the owning
business after credentials/MFA. A stored revoked ID must never be discarded or
automatically replaced. Legacy sessions without a session ID require fresh
sign-in. Offline cold-start authorisation is deliberately disabled; do not
turn a cached profile into login authority to get acceptance green.

Do not relax ATS, WebView policy, CORS, tenant checks, permissions, MFA or
certificate validation. Test-only certificates/origins must be isolated and
trusted explicitly. Never target a live venue or real payment processor.
Report simulator proof separately from unavailable physical-device proof.

## Dependency task

Read `DEPENDENCY_AUDIT_2026-10-14.json` and the exposure triage in
`MOBILE_HARDENING_REVIEW_2026-10-14.md`. Re-run `npm audit`; do not assume the
historical 130-finding snapshot is current. Map each reachable advisory to
the actual deployed/runtime, packaging or developer tooling path.

Prefer removing unused legacy tooling and focused compatible upgrades.
Do not use blanket overrides, force-fix, audit suppression, baseline expansion
or unrelated framework rewrites. Keep `package-lock.json` and `yarn.lock`
consistent; verify both frozen install paths. Preserve the supported native
plugins, React behaviour and Windows renderer preparation contract.

## Required verification and return

Run the full backend suite after every code batch:
`cd backend && python -m pytest tests/inprocess -q`.
Run frontend Jest, production build, full Playwright, configured flake8 and
differential type/dependency gates. Run iOS acceptance in macOS CI; retain
Android and Windows green checks. Never skip a failing assertion/test.

Return draft PR URL, exact tested commit, pass/fail/skip counts, native run
links, advisory before/after counts with reachability and upgrade reasoning,
remaining physical/signing prerequisites, and any still-unproved behaviour.
