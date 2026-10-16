# Backend consistency review — 16 October 2026

Draft review: [PR #26](https://github.com/Sam-NUA/NUA/pull/26).
Application revision: `cabd0c0257899d624c99e694828b8a3eab3f56c5`.

## Scope and inventory

This follows the terminal durability work in PR #24. Work is on
`fix/backend-consistency`, based on `fix/terminal-session-durability` at
`bf62dd8c1577161703a2bc90574b9c3c19a80319`; that stack descends from the
deployed `codex/owner-access` work, rather than `main`.
Branch, clean working tree, recent commits and open PRs were checked before
editing. README.md, docs/OWNER_ACCESS.md and
docs/LAUNCH_FOUNDATION_RUNBOOK.md were read. No AGENTS.md was found.

The authorized independent work is stock-transfer atomicity, appointment
concurrency, intake-reference ownership and slow-mover analytics. Claude's
PR #25 owns iOS acceptance and frontend dependency remediation. This PR does
not modify that branch or its scripts/dependencies.

No merge, deployment, Railway operation, production configuration or live
business-data mutation was performed. The only Vercel config change disables
automatic deployment for this new branch. Owner seed behavior, credentials,
permissions, MFA, tenant middleware, indexes and accepted baselines are unchanged.

## Findings and fixes

| Area | Root cause | Result |
| --- | --- | --- |
| Transfer creation | Source decrement and transfer insertion were separate writes, so an insertion failure could lose stock. | Both operations commit or abort in one Mongo transaction; the existing guarded decrement remains. |
| Receive/cancel | Each request read `in_transit` before independent stock/status writes, so competing requests could credit twice or leave a partial result. | Scoped product credit and conditional terminal-status update share one transaction; competing calls have one winner. |
| Appointment creation/rescheduling | Availability check followed by insert/update allowed concurrent requests to both see a free slot. | Every appointment mutation first writes a per-business calendar fence inside a snapshot transaction, forcing conflicting requests to retry with fresh availability. |
| Appointment reactivation | Updating a cancelled record to confirmed skipped the conflict check when time/staff/service did not change. | Reconfirmation checks the saved window as well as reschedules. Existing overlap restrictions on rescheduling inactive records are preserved. |
| No-show recording | Repeated no-show calls could increment a customer's tally repeatedly; status and tally were separate writes. | The status transition and scoped tally write are transactional; retries of an already-no-show record do not count again. This does not charge a card. |
| Appointment inputs | Invalid date/time raised an internal exception; zero/negative duration could bypass meaningful overlap checks. | Invalid local windows return 400 before insertion; valid adjacent slots remain allowed. |
| Intake/customer references | A tenant-owned intake note could retain a foreign, missing or quarantined customer/appointment ID. Appointment customer changes had the same reference gap. | Optional references must resolve within the actor's business and pass strict ownership. Invalid references return 404 without writing; walk-ins remain valid. |
| Slow-mover ranking | The query used `createdAt` and an ISO-string cutoff, while sales store `timestamp` as a BSON datetime. | Ranking uses `timestamp` and a datetime cutoff, preserving tenant filtering and the existing discount algorithm. |

## Transaction contract

`backend/services/consistency_store.py` uses Motor sessions with snapshot read
concern and majority write concern. A replica set or compatible transactional
Mongo deployment is required, as already required by POS redemption and native
reservation storage. There is no production in-memory lock or nontransactional
fallback; a session failure fails the request without the business mutation.

Appointment fence documents use the business ID as Mongo's unique `_id` and
also carry `businessId`. First-use creation happens outside the retry callback;
a duplicate-key race is accepted only when that exact tenant's fence exists.
The transaction increments the fence before reading appointments, which prevents
snapshot write skew across distinct appointment documents. The fence has no
expiry. Different businesses have independent fences. It is reconstructible
coordination state, not an appointment record or a permission grant.

The in-process suite uses a clearly marked test-only transaction double because
mongomock has no session support. It serializes callbacks and restores changed
collections on abort. It does not prove Mongo isolation. Separate tests execute
the actual handlers against CI's isolated Mongo 7 replica set without this double.

## Verification

Both workflows for application revision `cabd0c0` completed successfully:
[CI](https://github.com/Sam-NUA/NUA/actions/runs/38780620385) and
[real Mongo proofs](https://github.com/Sam-NUA/NUA/actions/runs/38780620453).
No individual test, gate or baseline was disabled in this PR.

| Final verification | Result |
| --- | --- |
| Full local backend rerun after the final code batch | **977 passed, 0 failed; 45,143 warnings; 370.61s** |
| Full backend in CI | **977 passed, 0 failed; 1,120 warnings; 318.28s** |
| Browser Playwright E2E | **15 passed; 2.4 minutes** |
| Frontend Jest | **61 passed across 11 suites** |
| React production build | **Compiled successfully** |
| Bookings service suite | **35 passed** |
| Backend real-Mongo suite | **19 passed** |
| Bookings real-Mongo suite | **7 passed** |
| Configured flake8 | **0 findings** |
| Type differential | **298 vs 814; no new codes** |
| Gitleaks secret gate | **Passed** |
| Backend pip-audit / dependency gate | **0 advisories across 0 packages** |
| Frontend npm audit | **130 findings remain; remediation not part of this patch** |

The final follow-up commit adds this report only; the application code tested is
the revision named above. No claims of native/hardware reruns are made for this
backend-only patch.

- Configured flake8: **0 findings**.
- Type differential: **298 errors vs accepted baseline 814; no new error codes**
  (15 existing categories). This is a passing differential gate, not zero-error typing.
- `git diff --check`: passed.
- Final revision frontend CI: **61 Jest tests across 11 suites passed**;
  production React build **compiled successfully**. The frontend audit reports
  **130 findings: 5 low, 41 moderate, 80 high, 4 critical**. Its existing report-only
  step succeeding is not an assertion that those findings are fixed. No dependency
  or audit baseline changes were made in this patch; remediation remains separate.
- Added **20 in-process cases** and **8 real-Mongo proofs**. The real proofs cover
  mixed receive/cancel contention, creation abort, receive abort, source oversell,
  overlapping create, competing reschedules/reactivation, no-show retries and
  failure without sessions. Existing reservation/POS proofs remain intact.

### Investigation during verification

The first full run was **965 passed, 6 failed**. Two failures were incorrect new
fault injection: patching a transient Motor/mongomock collection wrapper did not
patch the handler's later wrapper. The tests now inject at the handler database
boundary and assert that the transactional debit/credit happened before failure.

Four existing backup tests then failed because the analytics fixture left two
transactions without their normal `id` in the shared test database. Restore's
fallback business-key upsert collapsed them. A separate isolated in-memory
reproduction confirmed two such source rows restore as one. Generated fixtures
are now removed after each new test, preventing contamination; backup/restore
code and its assertions were not changed. This was a fixture defect, not a reason
to weaken the backup test. The corrected initial focused run was **14 passed**;
six additional input/reference cases were subsequently added.

The first published revision, `e9dc57b`, passed the real-Mongo job with
**18 backend tests + 7 booking tests**. Its CI run was superseded by the final
application revision; its interrupted jobs are not claimed as passes.

After correcting the fixtures and adding all 20 cases, the complete local suite
returned **977 passed, 0 failed, 45,142 warnings in 345.10 seconds**. Most warning
volume is existing Pydantic/FastAPI deprecation output; warnings were not disabled.
The final application revision's additional full run is recorded in the table above.

The final application revision's
[Mongo transaction workflow](https://github.com/Sam-NUA/NUA/actions/runs/38780620453)
passed: **19 backend real-Mongo tests, 15 warnings, 4.61 seconds** and
**7 booking real-Mongo tests, 41 warnings, 2.83 seconds**. The shared-runtime proof
also passed: five processes made 100 limit attempts with exactly 25 allowed;
a cold restart preserved the limit; 50 cross-process events were unique; tenant
isolation, cursor replay, expiry and overflow refresh checks passed. The latter
is the existing shared-runtime proof, not a separate cross-process appointment test.

## Claude coordination snapshot

PR #25 was initially checked at `b6885f9`, then rechecked before resuming on
16 October at `f07e30b8ffed242a02a55ba90c60906b8f264ade`.
Its commits address several earlier review findings: bound-token capture now uses
the real Keychain-backed plugin, revocation tests the device-bound token rather
than the registration token, replay matches the captured queue operation ID, and
tenant B's UI is checked for exposure of tenant A's pending queue. Appium and its
driver are pinned. Login automation now explicitly selects email mode and uses
password login for the refresh baseline.

All five workflows at `f07e30b` are green. The
[iOS acceptance job](https://github.com/Sam-NUA/NUA/actions/runs/38791390241)
logs prove login, binding/PIN reuse, offline sale, restart, reconnection,
operation-ID-matched replay, A/B/A isolation and bearer-token revocation. However,
**the workflow is not full refresh acceptance**: first-login and pre-revocation
refresh requests both returned 401. Commit `f07e30b` changed the required 200
baseline into a logged finding and conditionally skips refresh-after-revocation.
The job explicitly logs `SKIPPED` before its final `PASS`. This is a known product
failure plus an acceptance-gate gap; a green workflow cannot close it under the
standing rule against skipping a failing requirement. Restore the strict baseline
and post-revocation assertions when repairing the real cookie/session path. Do
not weaken HttpOnly/Secure, SameSite, tenant checks or device revocation to do so.
The logs establish missing refresh capability in that build; they do not prove
that any particular Capacitor plugin is the only correct remedy. The separately
reported PIN endpoint's refresh lifecycle also needs review.

The PR description still marks dependency remediation not started and is stale
about the iOS run. That build's install logs report **139 findings** (5 low,
41 moderate, 89 high, 4 critical), compared with **130** on this backend branch.
Those counts apply to different dependency trees and are not interchangeable.
No dependency remediation commit is present among PR #25's eight commits.

Claude also opened [PR #27](https://github.com/Sam-NUA/NUA/pull/27) and
[PR #28](https://github.com/Sam-NUA/NUA/pull/28) against `main`. PR #27 adds the
intake/customer and timestamp fixes with separate tests. PR #28 cherry-picks this
PR's two application commits onto `main`; direct comparison confirms the three
route files, consistency store, in-process regressions, real-Mongo test module
and Vercel config match this branch exactly. Its CI and Mongo workflows passed.
Its remaining tree differs because `main` lacks the native/security stack, so
these branches are not interchangeable. PR #27 also overlaps PR #28's intake
function. **Review one integration path; do not merge both implementations
independently.** This PR remains on the requested deployed-branch stack. No
retargeting, closure, merge or deployment was performed as part of this review.

## Remaining limits and next work

- Transfer creation still has no client operation key. These fixes guarantee
  atomic stock changes and one terminal outcome per existing transfer; they do
  not promise exactly-once creation if a client resubmits after losing an HTTP
  response. Add an explicit client/server idempotency contract before promising
  that behavior in an offline transfer UI.
- Appointment mutations serialize per venue. This favors correctness and is
  appropriate for current volume; high-contention venues may need measured,
  resource-level fencing later. No process-local coordination is relied on.
- Availability remains an informational snapshot with the existing 09:00–18:00
  default. The save operation is authoritative and may return 409. Opening-hours
  rules, historical missing-window repair and calendar redesign were not expanded
  into this patch.
- No historical timestamp migration or catalog-wide validation rewrite was made.
  Slow-mover ranking follows the application's actual datetime sale schema.
- Same-business customer/appointment linkage is validated for ownership, not
  forced into a new requirement that both references describe the same person.
- Physical printers, payment terminals, device-specific power loss, App Store
  distribution and live end-of-day reconciliation are not proven by these tests.
  Before launch, run an isolated venue acceptance session covering owner password/
  PIN/recovery, device revocation, offline sale/restart/reconnect, receipt printing,
  refund and end-of-day totals against known inputs, recording operation IDs and
  server totals. Production rollout remains a separate reviewed decision.
- Frontend audit remains a launch risk owned by Claude's separate work; no lockfile
  bump or baseline suppression was added here. Do not describe the complete
  product as dependency-clean or 100% launch-proven on the basis of this PR.

For earlier five-file tenant review and login/POS/booking/recovery code traces,
see [the mobile hardening report](MOBILE_HARDENING_REVIEW_2026-10-14.md).
For terminal-specific evidence and Claude's handoff, see
[the terminal durability report](TERMINAL_DURABILITY_REVIEW_2026-10-15.md) and
[the iOS/dependency handoff](CLAUDE_IOS_DEPENDENCY_HANDOFF_2026-10-15.md).
