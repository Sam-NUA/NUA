# iOS native session durability — 16 October 2026

Review: [PR #31](https://github.com/Sam-NUA/NUA/pull/31), branch
`fix/native-session-durability`, based on Claude's PR #25 at `bb29f8b`.
Tested application revision: `c95e164f18a9dd61d3bd4c35fd547c641f46915b`.
All five application workflows succeeded on this revision: CI, iOS, Android,
Windows and Mongo proofs. The follow-up commit publishes this report only.

## What was actually broken

The latest prior simulator run did not prove cold-start refresh. It proved
password refresh and PIN refresh while running, then failed after forced
restart. Its diagnostic showed identical user, business and device claims, but
the returned refresh belonged to the earlier password session while Keychain
held the newer PIN access session. `sameSessionActor` correctly rejected it.

The failure is recorded in
[Claude's final baseline iOS run](https://github.com/Sam-NUA/NUA/actions/runs/38843004646).
A 400ms retry did not repair that mismatch. The accepted fix must make the
latest session durable, not relax the identity comparison or skip the assertion.

Offline logout had a separate gap: clearing the access token and relying on an
unreachable server's logout response left the native refresh cookie available.
The fix removes the local native refresh capability directly and waits for that
cleanup before allowing the next sign-in.

## Resulting contract

- Terminal binding must commit the matching native HttpOnly refresh cookie to
  Keychain before it acknowledges a usable bound session. The cookie is selected
  from the native jar only when its session ID matches the verified bind response;
  an absent, stale, ambiguous, expired or non-HttpOnly cookie fails sign-in closed.
- Keychain uses `WhenUnlockedThisDeviceOnly`, with one active refresh grant per
  API origin. No plaintext, preference or legacy-cookie fallback is introduced.
- The iOS refresh bridge reads only that committed grant. Its ephemeral
  URLSession has no ambient cookie store or cache, posts only to the fixed
  `/api/auth/refresh` endpoint, and refuses redirects. Release builds require
  HTTPS; debug builds additionally allow HTTP on loopback for isolated CI.
- JavaScript gets the existing access-token JSON/status, never a refresh-cookie
  value or Set-Cookie response headers. Keychain failures propagate rather than
  being mistaken for server 401/403. The server still verifies the token, account,
  password revocation, tenant membership, session and device on every refresh.
- Exact subject/business/device/session continuity remains mandatory in the
  shared client. All previous tenant/RBAC/MFA/PIN eligibility checks, cookie flags,
  owner create-once seeding and server token lifetimes are unchanged.
- Native logout clears the durable grant and API-domain URLSession/WK cookies
  locally, including while offline. Login/MFA completion waits for pending logout
  cleanup. Failed deletion is reported. An in-flight native refresh cannot return
  a credential after its generation was invalidated by a new commit or logout.
- Android retains its existing HTTP refresh path and receives local native-cookie
  cleanup on logout. Browser/Windows retain server HttpOnly-cookie deletion.

The native code is registered in both the scene controller and storyboard path.
The Xcode target explicitly includes its Swift source. There is no new package,
entitlement, network permission, private signing secret or dependency lock change.

## Implementation

`NuaRefreshSessionPlugin.swift` implements native commit/refresh/clear, Keychain
storage, origin validation and redirect refusal. `nativeRefreshSession.js`
provides the small iOS bridge wrapper. `terminalSession.js` commits before
remembering/activating the bound token; `api.js` uses the durable refresh path.
`sessionCookies.js` and AuthContext integrate local logout and serialize the next
sign-in against cleanup. Claude's latest auth changes are preserved on this base.

The earlier unpublished offline-cookie work was reconciled into this review
branch. The old workspace and its draft were preserved, not reset or overwritten.
PR #29 had already been incorporated into Claude's branch by another actor;
this task did not merge it or any other PR.

## Verification and evidence

Local frontend: **82 tests passed across 13 suites**. Tests retain the existing
account/tenant/session guards, and cover commitment failure, missing session ID,
native versus other-platform behavior, 401/403 propagation, OS storage failure,
failed purge and the prohibition on activating a token before durable commitment.
Production React build compiled successfully. Configured flake8 has zero findings;
the type gate reports **302 vs baseline 814, no new codes**. Baselines unchanged.

Full local backend: **960 passed, 0 failed, 0 skipped**, 44,753 warnings in
350.72 seconds. The warnings are pre-existing deprecations across the full suite;
CI's pinned Python runtime also passed **960 tests, 0 failed, 0 skipped**,
with 1,104 warnings in 319.60 seconds. No backend production route changed. The full suite is required after every code batch;
no test is disabled or excluded. Native compilation succeeded in both iOS jobs;
the strict simulator acceptance step also passed on the real iOS Simulator.

Completed checks on the tested revision:

- iOS simulator build/install/launch smoke and strict financial/session acceptance passed.
- Frontend Jest in fresh CI: **82 passed, 13 suites**; production build clean.
- Browser Playwright suite: **15 passed** in 3.0 minutes.
- Booking boundary/webhook recovery suite: **35 passed**, 128 warnings.
- Real Mongo: **7 booking tests and 11 backend tests passed**; cross-process
  coordination/cold-restart proof also passed (five processes, 100 concurrent
  limit attempts, exactly 25 accepted; 50 unique events and tenant isolation).
- Windows/core unit suite: **26 passed, 0 failed**.
- Android's complete workflow passed: APK build, emulator install/launch and
  offline sale -> process kill/restart -> reconnect -> exactly one server sale
  using its saved `clientOpId` (total $19.50). This Android script is the existing
  cash/offline milestone; do not mistake it for iOS's additional A/B/A and native
  refresh/revocation assertions.
- Windows cash sale, process kill, A/B/A login isolation and exactly-once replay
  passed; installer build and launch smoke passed.
- Backend pip-audit: **0 advisories**; differential dependency gate passed.
- Gitleaks passed. Fresh frontend npm audit still reports **139 findings**
  (5 low, 41 moderate, 89 high, 4 critical). No audit suppression or lock change.

Workflow links for application revision `c95e164`:
[CI](https://github.com/Sam-NUA/NUA/actions/runs/38898349366),
[iOS](https://github.com/Sam-NUA/NUA/actions/runs/38898348843),
[Android](https://github.com/Sam-NUA/NUA/actions/runs/38898349610),
[Windows](https://github.com/Sam-NUA/NUA/actions/runs/38898349008),
[Mongo](https://github.com/Sam-NUA/NUA/actions/runs/38898349228).

### Strict iOS result: PASS

The full critical acceptance job completed successfully. It exercised the real
Capacitor app through Appium/WebDriverAgent against a throwaway FastAPI process
and Mongo replica set. No live venue or processor was used.

| Proof | Observed result |
| --- | --- |
| Password login, native binding and refresh | Refresh 200, bearer `/me` 200; identical user/business/device/session |
| Offline logout | Backend stopped before logout; after reconnection the native bridge had no usable refresh grant |
| PIN login | Reused the original device; refresh 200 and bearer `/me` 200 with the new exact PIN session |
| Expired-access cold restart | Real process terminate/relaunch; UI recovered, refresh 200, bearer `/me` 200, identical PIN session |
| Cookie privacy | Refresh absent from `document.cookie` and the core cookie getter on password, PIN and restart probes |
| Offline cash sale and second process restart | Exactly one pending sale survived; protected screens stayed on the auth-error gate until server verification |
| A/B/A isolation | B had its own device and empty queue; A's pending record remained untouched; A's device was absent from B's API response |
| Reconnection and exact replay | One $19.50 server transaction, matching saved operation `8f193074-5ab5-4fe3-bb02-ef234713f1b0` and business `default`; duplicate payload returned the same transaction |
| Owner revocation | Native refresh 200 before revocation, 401 afterwards; the bound bearer failed its next request while the independent unbound session remained valid |

The expired-PIN session was `51763f6b-6036-4959-ab5f-830e2eb065c0` and
remained the same across restart, rather than silently reverting to the earlier
password session. Refresh assertions use the same native transport as the
product. The UI bootstrap also exercises the shared client, persisted access
credential and exact identity check end to end. No assertion was weakened.

This proves the tested flows, not universal cookie confidentiality or encryption
of IndexedDB offline records. B's queue isolation assertion is a routing/access
boundary, not a claim that local database bytes are unreadable.

## Integration and release limits

- No merge, deployment, Railway action, live credential/configuration change or
  production business-data mutation was performed. Automatic deployment is
  disabled for the new branch. This is a draft review, not launch approval.
- Existing expired sessions without a durable native grant require fresh login.
  A still-valid access session can obtain and commit a verified grant by binding.
  No unverified old cookie is imported to bypass that requirement.
- Native configuration/code requires rebuilding and distributing the app binary;
  backend deployment alone does not update existing installations.
- A simulator process-kill test is not a physical power-loss, locked-device,
  printer, payment-terminal or store-distribution certification.
- PR #26 has the backend consistency implementation; PRs #27/#28 overlap it on
  another base. Prepare one integration path for review rather than independently
  merging duplicate implementations. This PR remains on the native/security stack.
- Claude's PR #25 was checked again at `bb29f8b`; it has no newer commits, and
  its dependency-remediation section still says not started. Claude owns that work.
  The last audited tree had 139 findings (5 low, 41 moderate, 89 high, 4 critical), not a clean audit. Retire the
  unused legacy frontend Electron host, assess actual reachability, make targeted
  upgrades and regenerate both npm/Yarn locks without blanket overrides/ignores.
- Claude's AI PR #30 remains at `3a6c9f6`, improving unconfigured/error
  handling; it does not supply a portable configured AI provider. Keep that work separate from native auth.

## Operator pilot checklist after review gates are green

Use a dedicated test venue and record device/build IDs, operation IDs, expected
catalog/tax settings and server totals. Do not use live customer/payment data.

1. On a physical Android tablet, iPad/iPhone and Windows terminal, verify owner
   password/PIN/MFA/recovery, normal logout, offline logout and owner revocation.
2. Ring up a known cash sale, stop connectivity, terminate/restart the app,
   restore connectivity and confirm exactly one matching server transaction.
   Switch A/B/A and verify that pending records and customer data stay isolated.
3. Test configured receipt printer, cash drawer and scanner; verify physical
   output, retries, paper-out/disconnection recovery and absence of duplicate sale.
4. With the payment provider's sandbox, test approval, decline, timeout and
   ambiguous-result reconciliation before allowing a retry to charge again.
5. Verify refund permissions, receipts and end-of-day totals against the known
   inputs; independently restore a test backup and reconcile those records.
6. Complete signing/provisioning, private distribution and rollback rehearsal.
   Record a go/no-go decision. Production rollout remains separately authorized.
