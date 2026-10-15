# Terminal session security and Windows durability — 15 October 2026

Review: [PR #24](https://github.com/Sam-NUA/NUA/pull/24), `fix/terminal-session-durability`, stacked on PR #23. Confirmed the review branch before resuming. The deployed `codex/owner-access` ref is `4a9f10f`; this review contains its source parent `9f60d2d`, whose tree is identical to that merge commit, then the reviewed multiplatform foundation. It does not contain the merge commit itself. Latest follow-up checked **16 October 2026, Australia/Melbourne**: Claude opened [PR #25](https://github.com/Sam-NUA/NUA/pull/25) from our tested application revision; its changes remain in their separate review branch. No PR merge, deployment, Railway action or production configuration change.

This extends [the full mobile hardening audit](MOBILE_HARDENING_REVIEW_2026-10-14.md), which records the initial inventory, five-file tenant spot check, owner password/PIN/recovery, POS sale and booking walkthroughs, dependency exposure and deliberately deferred correctness findings. Its earlier device-login ownership claim is explicitly corrected below.

## Implemented

| Actual root cause | Fix |
|---|---|
| Device login checked active status but not the signing-in business; the earlier review overstated existing login ownership enforcement | Password/MFA/PIN and manager-approved PIN now resolve the device against the verified user's business. Approval rejects a foreign device before writing a roster override. Active foreign IDs fail with 403. |
| First native registration happened after entering protected routes; the original access/refresh tokens remained unbound | New sign-ins carry a random server-issued session ID. Native AuthContext registers and binds before entering protected routes or activating offline storage. An immutable server binding also covers tokens issued before binding, including the original refresh cookie. |
| Binding could otherwise be overwritten or follow a moved account into another venue | Mongo's unique `_id` makes concurrent session binding insert-once. Rebinding to another terminal is rejected. Every access/refresh checks the stored subject, business and device against current account membership and active device ownership. |
| One stored device ID prevented legitimate multi-business use | Adapters retain a business→device map; the server selects only the authenticated business's entry. A local hint never grants membership. Revoked/unknown selected IDs are rejected rather than discarded/replaced. |
| Middleware preferred bearer but route dependencies/actor context preferred cookies | All three select an explicit bearer consistently. A different account's old cookie cannot change the route's actor after middleware verified the bearer. |
| Late sign-in/verification responses could outlive logout or account switching | Auth generation checks and native credential continuity gate queue activation and protected state updates. |
| An already-open offline session could outlive its access-token expiry | New cash operations and Windows encrypted reads/writes stop when the verified token expires. Cold-start offline authorisation remains disabled. |
| Windows Chromium storage was deliberately in-memory, so checkout's IndexedDB queue did not survive process restart | The existing shared checkout queue now uses guarded main-process IPC and the OS-encrypted atomic store on Windows, scoped by verified business and terminal. Cash payload, modifiers, discounts, walk-in name and `clientOpId` are preserved. |
| Wiring the separate narrow CashOrderQueue would reject/drop valid existing checkout fields or create two replay engines | Keep one financial queue. Its current cash eligibility, rejection retention and idempotency rules remain authoritative. The separate platform-core primitive remains unused; this is a deliberate architecture decision, not a claim it was wired in. |
| Startup smoke did not prove actual Windows checkout durability | Add real Windows Electron/React/FastAPI acceptance: cash checkout → closed connections → durable record → forced process kill/restart offline → A/B/A business switch → exactly one server transaction. |
| The fixed Windows host bar covered React's fixed POS dock; body padding did not move fixed controls | Measure the actual host bar with ResizeObserver and reserve its height beneath the dock, drawers and bottom floating actions, including touch mode. The acceptance test still uses an ordinary pointer click. |
| The forced Windows restart exposed a real safeStorage decryption failure; acknowledging encrypted files alone did not ensure Chromium's DPAPI-protected key metadata had reached disk | Gate startup storage on the protected key's actual presence in Electron's Local State and flush that metadata before accepting encrypted records. Never create a replacement key, rewrite Chromium preferences or use plaintext. The fresh-profile taskkill/reconnect/A/B/A test now passes with the same nonempty operation ID, correct business and one server sale. |

## Security boundaries

- `POST /auth/bind-device` requires a verified ordinary access session; MFA/challenge tokens cannot bind. Device ownership/status is checked server-side. Binding does not grant any role or permission.
- `terminal_sessions` uses the server-issued session ID as Mongo `_id`; TTL cleanup is eight days. Device claims remain checked even after binding metadata expires. Tokens issued before binding expire before this retention window.
- Access/refresh revocation checks reject a removed/revoked device and an account moved away from its original bound business. Browser sessions without a device retain normal login behaviour.
- Windows activation verifies the exact OS-stored bearer against the real `/auth/me`, with cookies omitted and redirects rejected. Renderer-provided business IDs must match that response; they cannot select arbitrary encrypted files or another business's scope.
- Windows keeps Chromium's partition in-memory. Only explicit guarded storage persists the cash queue, uncertain kitchen records and read cache. Records are business+device scoped, so another staff member on the same venue terminal can reconcile the shift while another venue cannot read the queue.
- Encryption or corrupted storage errors fail closed; there is no plaintext or IndexedDB fallback on Windows. Atomic writes finish in their captured old scope if logout happens mid-write, and are never acknowledged under a new session.
- Native cold restart requires online server re-verification. This pass does not turn a saved profile into offline login authority. Existing queued records remain recoverable after valid re-authentication.

## Compatibility and limits

Existing native credentials without a session ID require one fresh sign-in. Legacy single device IDs remain strict until a successful original-business sign-in records their verified business mapping. A person who no longer has that venue's account needs an explicit operator-assisted terminal reassignment; silently deleting a revoked legacy ID would bypass the control.

A device ID is a registry identity, not cryptographic hardware attestation. Someone with valid primary credentials can still use an unregistered client; this work does not claim to prevent that. Native local-cache encryption outside Windows, physical hardware, signed distribution, and full iOS financial acceptance remain separate work.

The Windows acceptance harness uses real application routes with an isolated in-memory database. Mongo replica-set coordination is still exercised by its own mandatory workflow; no transaction safety was disabled in production. Loopback HTTPS uses a temporary explicitly trusted certificate, removed in cleanup; certificate validation remains enabled. No production host/payment processor is used.

Windows financial acceptance launches the supported source Electron host with its prepared production React renderer. The unsigned NSIS installer is built by the separate packaging job; this does not claim an installed, signed binary was exercised on a physical till.

The Windows key-readiness guard follows the pinned Electron 44.7.0 implementation: [BrowserProcessImpl](https://github.com/electron/electron/blob/v44.7.0/shell/browser/browser_process_impl.cc) keeps protected cryptographic preferences in `sessionData/Local State` and commits pending preferences on normal shutdown; [safeStorage](https://github.com/electron/electron/blob/v44.7.0/shell/browser/api/electron_api_safe_storage.cc) uses OSCrypt. Forced termination bypasses normal shutdown. The guard observes and fsyncs existing DPAPI-wrapped metadata without rewriting it. An Electron upgrade must review this metadata contract and rerun the fresh-profile forced-kill test; missing metadata fails closed after 20 seconds.

## Validation

Application revision: `427b6da263356754f35be5068891cd2e5b58abce`. The full local backend suite was rerun after the final key-readiness code batch: **957 passed, 0 failed, 0 skipped**, 44,520 warnings in **327.94 seconds**, confirmed by all 957 JUnit cases. Warnings are existing Pydantic/datetime deprecations, not suppressed. Subsequent documentation-only commits do not alter the tested application.

| Check | Result |
|---|---|
| Backend full suite | Local Python 3.12: 957 passed, 0 failed, 0 skipped, 44,520 warnings / 327.94s. Final CI Python 3.11: 957 passed, 0 failed, 0 skipped, 1,101 warnings / 314.76s |
| Frontend Jest | 61 passed, 0 failed (11 suites) |
| Windows/core Node | 26 passed, 0 failed, 0 skipped |
| Full Playwright | Final CI: 15 passed, 0 failed, 2.8 minutes |
| Production frontend build | Passed, zero compile errors |
| Configured flake8 | 0 findings |
| mypy differential | Final CI: 302 errors vs 814 baseline, no new codes (15 accepted categories); baseline unchanged. Earlier local environment: 296 |
| Backend dependency audit | Final CI full requirements audit and differential gate: 0 advisories across 0 packages; baseline unchanged |
| Frontend npm audit | 130 findings (4 critical, 80 high, 41 moderate, 5 low); unchanged locks, advisory exposure triaged in the parent review; not suppressed |
| Separate bookings suite | Final CI: 35 passed, 0 failed, 128 warnings |
| Windows build/package/startup and financial acceptance | Passed: [38694415343](https://github.com/Sam-NUA/NUA/actions/runs/38694415343), critical job 116287523158; startup/package job 116287523450 |
| Secret scan | Final source revision: gitleaks passed |
| Android CI | Final source revision: APK build, emulator startup and full cash/offline/restart/reconnect milestone passed |
| Mongo transaction proofs | Final source revision: passed |
| iOS CI | Final source revision: build, simulator install and launch/survival passed; financial/security acceptance is separate |

### Final-source GitHub Actions evidence

| Workflow | Result |
|---|---|
| Full backend, lint/type/dependency gates, frontend build/unit, bookings, Playwright and gitleaks | [38694415353](https://github.com/Sam-NUA/NUA/actions/runs/38694415353) — success |
| Windows startup/package and financial acceptance | [38694415343](https://github.com/Sam-NUA/NUA/actions/runs/38694415343) — success |
| Android build/startup/financial acceptance | [38694415352](https://github.com/Sam-NUA/NUA/actions/runs/38694415352) — success |
| Mongo transaction proofs | [38694415410](https://github.com/Sam-NUA/NUA/actions/runs/38694415410) — success |
| iOS simulator build/install/launch | [38694415408](https://github.com/Sam-NUA/NUA/actions/runs/38694415408) — success |

Windows acceptance logs show the original session bound, one durable cash intent, forced termination, blocked protected screens during the offline restart, business B denied access to A's records, and A's return syncing the same nonempty operation ID to one $19.50 transaction in the correct business. Separate replica-set tests cover database coordination; this acceptance run does not replace those proofs. Android's acceptance likewise uses a throwaway venue and real APK/WebView. Neither substitutes for physical printer/payment hardware certification.

Two acceptance-fixture defects were corrected rather than weakening application validation: the product fixture omitted the API's required SKU (correctly rejected with 422), and importing the temporary TLS root into the Windows user store waited for an interactive trust dialog. The CI certificate now uses the hosted runner's machine root store and is removed in cleanup. No certificate validation, product requirement or test assertion was disabled.

## Claude's non-overlapping work

[Exact handoff](CLAUDE_IOS_DEPENDENCY_HANDOFF_2026-10-15.md): iOS financial acceptance and frontend dependency remediation. Claude owns iOS-specific CI/driver/test wiring and frontend package/lockfile/unsupported legacy Electron cleanup. Codex owns auth/device/session, shared queue and supported Windows host files. Both must preserve full backend regression checks and open draft PRs without merging or deploying.

### Latest Claude review — 16 October 2026 (Melbourne)

Draft [PR #25](https://github.com/Sam-NUA/NUA/pull/25), `claude/ios-financial-acceptance`, head `dddf41303b13c8fe7a30f13e27c710affc85a421`, starts directly from our fully green `427b6da`. Two commits add the extended iOS driver/workflow, WebdriverIO and both lockfiles; the second lets PIN login's full-page reload settle. Only five files changed. The branch retains the locked `serve` dependency, avoiding the older foundation branch's removal.

CI, Windows, Android and Mongo workflows passed. [iOS run 38699939779](https://github.com/Sam-NUA/NUA/actions/runs/38699939779) has a passing build/install/launch job but a **failing critical acceptance job** (`116305415225`). Its latest failure is a ten-minute Appium `POST /session` timeout **before password/PIN login begins**. It is not evidence that the POS login failed. Logs identify Appium 3.8.0/XCUITest 12.18.1; setup still installs moving `latest` tooling. Retain the full startup timeline and stabilise the tooling before extending timeouts again.

The new driver attempts the requested password/PIN/device, cold-restart gate, A/B/A queue and revocation flows. Static review found these defects to resolve before accepting a future green run:

1. Revocation probes `ownerA.token`, from the separate registration request. That session was never bound to the UI's terminal. Capture and verify the real WebView/Keychain access token's subject/business/session/device; use the independent owner token to revoke, then assert the actual bound session fails. The independent unbound session should remain valid. Do not change production revocation to reject unrelated sessions to satisfy this test.
2. Refresh accepts any result except HTTP 200, including network errors or HTTP 500. Prove a successful refresh for the same bound session before revocation, then require 401/403 after revocation while the backend is healthy. A missing cookie before revocation is not proof of revocation.
3. The final sale requires a nonempty operation ID but does not match it against the original queue record. Capture the exact `payload.clientOpId` before termination, compare after replay, and prove repeated submission adds no transaction.
4. Under B, the script directly reads A's IndexedDB and expects the record to remain. That proves preservation, not unreadability to arbitrary same-origin JavaScript. Prove B's actual application UI/export/replay does not expose or consume A's record. Native IndexedDB encryption remains a separate gap; the API device-list check is useful server-scoping evidence.

PR #25 explicitly says **dependency remediation has not started**. Earlier foundation audit reductions are not completed remediation on this stack. Legacy frontend Electron retirement, both lockfile audits and advisory-specific WebdriverIO triage remain assigned in the handoff. Claude's branch was not rewritten and no production security check was weakened during review.

### Earlier foundation results — historical comparison

All five workflows on Claude's `1d6e2ed` revision succeeded. [iOS run 38684689159](https://github.com/Sam-NUA/NUA/actions/runs/38684689159), job `critical-acceptance-milestone` / `116256742079`, used Appium/XCUITest with the real Capacitor WKWebView, a throwaway FastAPI process and a real single-node Mongo replica set. The logs show password sign-in, one $19.50 offline cash sale, one pending record before and after process termination, reconnect/retry, and one server transaction of the expected total. The Keychain probe succeeded with an ad-hoc signed simulator build. CORS changes are confined to the throwaway test process; production backend policies were not changed.

That is meaningful simulator proof, but it is not the full new session/security acceptance contract: the log prints `clientOpId=(none)`, the driver does not require a nonempty matching operation ID or correct business on the resulting transaction, and it does not test PIN, A/B/A queue isolation or revocation of existing access/refresh tokens. It runs on the earlier foundation implementation, which lacks PR #23/#24's queue/session changes. Port and rerun it on the combined review branch before claiming those changes are verified on iOS. Physical iPhone/iPad operation remains untested.

Claude's dependency changes touched only frontend package/lockfiles and the debt report, plus iOS driver/CI. Its recorded post-WebdriverIO totals are npm 127 (1 critical, 84 high, 37 moderate, 5 low) and yarn 182 (6 critical, 99 high, 67 moderate, 10 low). These are Claude-branch snapshots, not an audit result for this PR's unchanged locks or evidence that dependency remediation is complete. The following report claims need correction before integration:

- `serve` is still called by `frontend/playwright.config.js`. Removing its declaration leaves `npx serve` free to download an unpinned server during e2e. Restore a locked dependency or deliberately replace the caller and verify both lockfile paths.
- Frontend Electron 33/electron-builder 25 belongs to the unsupported `frontend/electron/` path. The supported Windows host uses its independent `apps/windows/package.json` with Electron 44.7.0 and electron-builder 26.15.3. Do not propose a 33→41 upgrade for the supported host based on the legacy package.
- Build/CI-only reachability lowers deployed-runtime exposure; it does not make vulnerable archive/config processors harmless. WebdriverIO's new dependency paths still require advisory-specific review. No ignores or baseline increases are authorised to hide them.

The older six-file foundation delta is historical comparison, not an instruction to replay it over PR #25. Continue from PR #25's current branch, which already retains `serve`. Avoid accepting a green run on the older implementation as proof of the combined result.

## Launch work deliberately left open

1. Combine the independently reviewed PRs on a review branch and rerun native acceptance with the current session contract. No PR is merged by this assignment.
2. Complete the iOS security assertions and dependency corrections above; retire the unsupported legacy Electron path through a reviewed change.
3. Physical Android/iPhone/iPad/Windows acceptance: receipt and kitchen printers, drawers, scanner input, payment-provider hardware, touch targets, display scaling and failure/recovery procedures. No SDK/provider is selected without the venue's actual hardware requirements.
4. Release signing, store/internal distribution identities, Windows signing/update policy, monitored staging and an operator rehearsal with a non-production venue. These need the release owner's accounts/hardware and separate deployment authorisation.

This review does not claim 100% launch readiness, live payment certification or physical-device proof.
