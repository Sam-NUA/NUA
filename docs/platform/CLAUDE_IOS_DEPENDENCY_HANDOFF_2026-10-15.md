# Claude handoff — iOS financial acceptance and frontend dependency remediation

Repository: `Sam-NUA/NUA`. Start from the latest `fix/terminal-session-durability`
review branch, including its stacked parent `fix/mobile-isolation-review`.
Read the current reports and this branch's final validation before editing.
Create a separate review branch and draft PR; do not merge, deploy, change
production configuration, or touch Railway.

## Current review — 16 October 2026 (Melbourne)

Continue draft [PR #25](https://github.com/Sam-NUA/NUA/pull/25), branch
`claude/ios-financial-acceptance`, reviewed head `dddf413`. It starts from
our fully green `427b6da`. Preserve its five-file implementation and its
retained `serve` dependency; do not replay older foundation lockfiles.

Latest iOS failure: run `38699939779`, job `116305415225`, times out after
ten minutes creating the Appium session, before login starts. Basic iOS
build/install/launch passed. CI, Windows, Android and Mongo passed.
Investigate and retain the complete simulator/Appium/WDA startup timeline
and pin a proved compatible tooling pair. Do not weaken login or extend
timeouts without evidence.

Correct these assertions before claiming the extended milestone passed:

- Capture and verify the real UI's bound token after password and PIN login.
  A device-registry row alone does not establish session binding. Never
  print token or cookie contents.
- `ownerA.token` is the separate, unbound registration session. Use it to
  revoke the device, then require the real bound access token to fail with
  401/403. The independent unbound session should remain valid; do not
  change production security to reject it just to satisfy the script.
- Prove refresh works for the bound session before revocation, then
  require 401/403 after it. A network error, HTTP 500 or an already-missing
  refresh cookie cannot count as proof.
- Capture the queue's exact nonempty operation ID before restart and match
  the server record after replay; also prove duplicate replay is safe.
- Prove B's actual application UI/export/replay does not expose or consume
  A's sale. Reading A's IndexedDB under B proves only preservation, not
  encrypted storage or unreadability to arbitrary same-origin JavaScript.

Dependency remediation is explicitly unstarted in PR #25. Retire the
unsupported legacy frontend Electron path and audit both lockfiles,
including new WebdriverIO paths; leave supported `apps/windows` unchanged.

## Earlier foundation review (15 October)

Reviewed foundation revision `1d6e2edbc82bea78599e2f75209e3a32f353f109`.
Its five workflows passed, including the new Appium/XCUITest iOS cash sale,
offline process restart and reconnect milestone against a real temporary
Mongo replica set. Preserve that work. It has not been integrated into this
branch, and its green run exercises the older foundation implementation.

Finish these concrete gaps on a review branch containing PR #23/#24:

- Strengthen the iOS result assertion: capture the queued `payload.clientOpId`
  before termination, require it to be nonempty, require the server record's
  matching ID and business, and prove a repeated submission cannot duplicate
  the sale. The reviewed log currently reports `clientOpId=(none)` while
  still printing PASS.
- Add the first-session binding, offline protected-screen lock, A/B/A queue
  access, existing-session/device revocation and refresh checks specified
  below; add PIN login under its real business/MFA policy.
- Correct the dependency report's `serve` removal: Playwright's webServer
  command still calls `npx serve`. Restore a locked version or replace the
  caller deliberately. Passing CI via an implicit network install is not a
  reproducible dependency removal.
- Distinguish unsupported `frontend/electron` (Electron 33/builder 25) from
  supported `apps/windows` (Electron 44.7.0/builder 26.15.3). Retire the former
  in its own reviewed change; do not downgrade/change the supported host.
- Review the new WebdriverIO advisory paths specifically. CI-only tools can
  process untrusted archives/configuration; a devDependency label alone is
  not a completed exploitability assessment.
- Pin a compatible Appium server/XCUITest driver pair after proving it works;
  installing `appium@latest` plus the latest driver makes the same revision
  change its tooling over time. Generate throwaway test credentials/secrets
  per run rather than copying the older Android script's fixed fixture text.

See [the terminal review](TERMINAL_DURABILITY_REVIEW_2026-10-15.md) for exact
CI evidence, current validation counts and remaining release prerequisites.

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
