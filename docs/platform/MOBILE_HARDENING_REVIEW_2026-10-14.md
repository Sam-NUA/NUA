# NUA multiplatform review and hardening — 14 October 2026

Review branch: `fix/mobile-isolation-review`. Initial review: Claude's `feat/multiplatform-foundation` at `469c84099db0359ebbc92a52fd677da4d8ef29bf` (PR #22). Reconciled on 15 October with latest base `b20437e241b10e2dda1900158c82c19690b7262b`. This is a review change; no merge, deployment, Railway action or production environment change is authorised/performed.

## What Claude finished

Verified through source and GitHub Actions, rather than the stale PR description:

| Work | Evidence at reviewed Claude head | Limit |
|---|---|---|
| Android APK and emulator startup | Android run 38469307865: build and emulator smoke passed | Offline acceptance job failed; process survival alone does not prove login/sales |
| iOS native project and simulator | iOS run 38469308026 passed | No physical-device, signing or offline-sale acceptance proof |
| Windows host, adapters and installer | Windows run 38469307953 passed | CashOrderQueue still not used by POS checkout |
| Main regression checks | CI run 38469307895: backend, frontend, bookings, Playwright and gitleaks passed | Results apply to Claude's reviewed commit |
| Mongo coordination proofs | Run 38469307978 passed | Does not establish native UI/hardware parity |
| Direct token readers | `d3a384b`, plus backlog update `cb1db77` | Kept Claude's asynchronous call-site migration; adapter still mirrored plaintext |
| Android debugger connection fixes | Latest series through `469c840` | Latest acceptance log still showed WebView fetch/login failure |

**15 October update:** Claude closed the earlier Android acceptance failure. Run **38492613182** completed successfully, including the critical acceptance job; iOS **38492613224**, Windows **38492613077**, Mongo proofs **38492613086**, and main CI **38492613057** also passed. His script now uses adb reverse, stops/restarts the throwaway backend to prove the outage, restores POS/auth after restart, and exits after successful assertions. These newer fixes were retained during rebase. The proposed mixed-content workaround was removed; production WebView policy was not relaxed. This review branch's own final CI also passed, including the modified storage/queue implementation and business/client-ID assertions; exact runs are below.

## Findings and fixes

| Root cause | Change | Verification scope |
|---|---|---|
| First login claimed all legacy, unowned queued transactions | No automatic migration. New v2 business databases; both old database families preserved untouched for support reconciliation | IndexedDB regression proves foreign legacy rows are not inherited or deleted |
| `lock()` reopened the shared legacy database | Locked reads/writes reject, including asynchronous open/read callbacks | Locked-storage tests |
| Replay looked up the current login after asynchronous work, and another browser tab could replace shared credentials | Capture business, token and session epoch; bind activation to the verified login; reject a different account’s replacement token; pin bearer credentials using the fetch adapter with cookies omitted; disable cookie refresh for replay; stop on session changes. Server middleware rejects a mismatching X-Offline-Business-Id against the verified actor; this header never selects or grants a tenant | A→B switch test retains A's rows and sends no subsequent request under B |
| Cash was only saved after a network error, leaving a crash window | Persist cash intent before HTTP, reuse its `clientOpId`, remove only after acknowledged success | Persist-before-send and lost-response/replay tests |
| Rejected sales/actions were deleted | Retain review records, exclude rejected sales from automatic retry, provide active-business export in Settings | Rejection retention and no-repeat tests |
| Card/loyalty/split uncertainty could be displayed as successful offline payment | Only ordinary cash is eligible; card, split, points and voucher-code paths propagate errors | Cash eligibility negative tests |
| Kitchen action retries can repeat side effects (fire/void printing and audit) | Uncertain kitchen actions are retained for manual reconciliation, with honest UI messages; no automatic blind replay | Source walkthrough; full exactly-once KDS work remains required |
| A delayed menu read could populate B's cache with A's results | Capture scope before fetch and check it before state/cache updates | Stale-scope cache test |
| Native adapter copied bearer tokens to localStorage and accepted legacy fallback on OS errors | OS storage only, purge plaintext copies, fail closed; plaintext-only upgrades require fresh login | Native plugin mocks; native OS behaviour still needs device QA |
| Logout suppressed deletion failures, could revive an old token next launch, and waited on an unbounded remote request | Clear locally before remote logout; bound the remote request to five seconds; persist non-secret signed-out tombstone before deletion; invalidate memory immediately; surface failures | Tombstone/deletion-failure unit tests and held-response browser regression |
| Trusted-device bypass token used plaintext localStorage on native shells | Native remembered-device option disabled; browser behaviour retained | Native login source; real biometric/secure trusted-device flow remains deferred |
| Shared refresh could revive a signed-out session, replace it with the account in another tab's cookie, or replace a guest credential | Refresh only automatically injected, nonempty active staff credentials; require the refreshed subject and business to match the original token; clear only the still-current failed session | Five refresh regressions cover signed-out, changed subject/business and successful same-actor renewal; guest/auth e2e coverage retained |
| Secure-storage exception occurred outside AuthContext's try block | Catch it, gate protected screens and retry verification on connectivity recovery | Regression build; offline restart cannot authorise a new session locally |
| Native queue hook relied on browser connectivity events | Use NetworkService and retain 30-second safety poll | Unit/build; native recovery needs emulator result |
| API schema discarded `walkInName` and omitted persisted `clientOpId` from transaction responses | Add bounded optional walk-in name to request/response and save it; expose client operation ID | Real backend sale/detail/idempotent-retry regression |
| Kitchen docket interpolated untrusted text into HTML | Escape every dynamic text field; prototype-safe category grouping | DOM injection and grouping tests |
| iOS custom scheme set to unsupported `https` | Set `capacitor`; preserve Android HTTPS scheme | Capacitor configuration contract and sync |
| Missing Apple required-reason API manifest; invalid XML comment syntax | Add UserDefaults CA92.1 and FileTimestamp C617.1 reasons, include manifest in Xcode resources, fix comments | plist parsing and Capacitor sync; App Store data labels still require review |
| Android camera/microphone features lacked manifest declarations | Add permissions and optional hardware features; disable application backup | Manifest review; OS permission UX/device testing remains required |
| Native smoke builds launched against production origin | Use reserved, non-live smoke origin; financial acceptance keeps its throwaway backend | Workflow inspection |
| Native web bundle could register a web service worker | Do not register it inside Capacitor/Electron | Build/source review |
| No owner terminal/review/version surface | Add terminal list/revoke with existing PIN confirmation, build/platform/ID readout and scoped offline JSON export under Settings → Devices & printing | Browser acceptance test and screenshot |
| Stock-transfer receive/cancel updated products using ID alone | Scope both writes by verified business, reject missing owned product without finalising transfer | Dangling-transfer regression retains the unique product-ID index and proves foreign stock stays unchanged |

## Tenant spot check

Five request-handling files were chosen before edits: `routes/devices.py`, `routes/stock_transfers.py`, `routes/appointments.py`, `routes/customers.py`, `routes/channel_menus.py`.

- Devices: register stamps verified business; list/heartbeat/revoke queries scope by business; revoke also checks strict ownership.
- Stock transfers: found and fixed the two unscoped product updates described above. Other transfer reads/writes and create's stock decrement were scoped.
- Appointments/service catalog/intake: reads and updates scope by business; inserts stamp business. Client-intake creation does not validate that its optional customer reference belongs to the actor's business. It does not read/write the foreign customer, but referential validation merits follow-up. Appointment conflict check and insert remain non-atomic.
- Customers: customer/profile/feedback/wallet queries are scoped; stamped updates were traced into `services/entity_service.py`, which independently scopes queries and prevents ownership changes.
- Channel menus: product/override/heat reads, aggregates and writes are scoped. Separate correctness finding: the slow-mover aggregate filters `transactions.createdAt`, while POS sales use `timestamp`. Flagged for a pricing-specific change and regression coverage; not silently changed here.

No tenant predicate, permission, index or test was weakened. The stock fixture initially attempted simultaneous colliding product IDs and correctly hit the unique index. The final test uses a dangling transfer followed by a foreign restored product; the real index remains intact.

## Launch-critical walkthrough

- **Password login:** Login → AuthContext → `/auth/login`; two-factor challenges are not treated as tokens. Completed login stores token, activates the verified business and mounts protected routes. Native plaintext-only upgrades require fresh login. OS-storage failures are visible verification errors.
- **PIN login:** Login → `/auth/pin-login` → SecureStorageService → `checkAuth` → `/auth/me`. Server-side tenant/PIN/MFA/device checks are unchanged. No default owner PIN or fallback password introduced.
- **POS cash sale:** Product/modifier selection → checkout payload → persisted client operation → `/transactions` → catalog-derived pricing, tenant-stamped sale and existing server idempotency/side effects. Walk-in name and client ID now survive response/detail/retry. Offline cash is pending synchronisation; gateway/balance payments are not falsely acknowledged.
- **Kitchen actions:** `clientKey` exists for send/add-round, but fire/void can emit repeated print/audit side effects. Network-uncertain actions are therefore held for review. This does not establish full offline KDS exactly-once behaviour.
- **Reservations:** Existing browser path is covered by tenant-settings/reservation e2e and the separate bookings service suite. Restaurant reservations remain online mutations; no new offline reservation promise is made. Appointment-booking concurrency differs from restaurant booking coordination and is flagged above.
- **Owner recovery:** Initiate with operator-provided recovery key/email → complete using issued recovery token → password/PIN reset → secure token clearing → fresh sign-in. Existing e2e exercises recovery followed by PIN login. Create-once owner bootstrap is unchanged.
- **Native cold restart offline:** Saved queue survives in IndexedDB, but authorisation requires server verification before protected operation/replay. Reconnection triggers verification retry. Continued sales while still offline after cold restart are not enabled/proved by this pass; offline authorisation design remains a release decision.

## Dependency triage

Fresh `pip-audit` of pinned backend requirements: **0 advisories**. Differential dependency baseline also reported 0; no ignore/baseline changes.

Every returned package/advisory and suggested fix is preserved in [DEPENDENCY_AUDIT_2026-10-14.json](DEPENDENCY_AUDIT_2026-10-14.json).

Fresh frontend `npm audit`: **130 findings — 4 critical, 80 high, 41 moderate, 5 low**. Flagged direct roots are Capacitor CLI, concurrently, legacy Electron/electron-builder, ESLint, react-scripts, serve and Tailwind. They are build/dev/server tooling, not the mobile WebView's deployed static React runtime. All direct application libraries (including axios, React/Router and secure-storage plugin) were absent from the advisory list returned in this scan. This is exposure triage, not a claim of zero supply-chain/developer risk.

The critical paths include shell-quote through concurrently, proxy-addr through tooling servers, and tar through packaging tools. Tar extraction of untrusted archives and accessible development servers are real exploit preconditions; those tools must not process untrusted inputs or serve public traffic. The old `frontend/electron/` runtime also carries Electron advisories and is not the supported `apps/windows` host. Removing or upgrading that duplicate build system requires a dedicated packaging migration. No `npm audit fix --force`, blanket overrides, blind downgrades, dependency-baseline suppression or security-test skipping was performed. The old dependency-debt document's 46-finding snapshot is superseded by this dated audit.

## Remaining work / release limits

1. Android's full emulator acceptance and iOS's build/install/launch check passed on this branch. iOS still needs an equivalent full cash/offline/restart/replay test; launch survival does not establish that flow.
2. Native API origins must be explicitly authorised by the staging backend's `FRONTEND_URL` list (`https://localhost` for Android; `capacitor://localhost` for iOS). The production allowlist was not widened or changed. CORS handling differs when FRONTEND_URL is unset; do not assume a simulator launch proves API access.
3. Reconcile preserved old queue databases before rollout on existing tills. Review exports may contain customer/order information; restrict handling to authorised support/owners. No automatic claimant or destructive recovery tool is provided.
4. Device registration occurs after the first login and does not replace that already-issued token; its device claim is present only on a later device-ID login. Also, a single stored device ID can block signing into another business because login correctly rejects a foreign-business registry entry. Both need an explicit pairing/session-binding design, not relaxed ownership checks. Cryptographic terminal attestation, native biometrics, secure remembered-device credentials, offline authorisation after cold restart and at-rest protection of financial caches remain open.
5. Native printer/scanner/drawer/payment-provider integrations need selected hardware/SDKs and physical-device QA. Generic interfaces that report unsupported were left honest. Android currently permits cleartext LAN printing app-wide; narrowing that requires a real printer transport/address policy.
6. Windows CashOrderQueue integration remains Claude's work. The walk-in schema blocker is closed, but schema parity, migration, persistence and real checkout/restart/tenant acceptance still require a dedicated integration. The current Electron Chromium partition is in-memory; do not assume its shared IndexedDB queue is restart-durable.
7. Signing, store accounts, privacy data labels, release tracks and physical Android/iPhone/iPad/Windows tests require operator assets/hardware. No publication performed.
8. Follow up on stock-transfer multi-document atomicity/concurrent receive/cancel, appointment conflict atomicity, intake customer-reference validation, and the channel-menu timestamp finding. These were disclosed, not silently bundled into the tenant-scoping fix.
9. Scope-bound server reauthentication proofs for sensitive operations, production telemetry monitoring and legacy frontend dependency migration remain separate security/product work.

## Validation

Application-code validation revision: `65ec95003585cf8e03dbd3c80a600fd40803e2a9`. Final results are recorded below after the last code batch. Native CI is reported separately from local/browser checks; no physical-device result is claimed. Subsequent documentation-only commits do not change the tested application.

| Check | Final local result |
|---|---|
| `cd backend && python -m pytest tests/inprocess -q` | **949 passed, 0 failed, 0 skipped**, 37,974 deprecation warnings, **327.04 seconds**, confirmed by all 949 JUnit cases after the final code batch |
| Frontend Jest | **8 suites, 50 tests passed, 0 failed** |
| Full Playwright suite | **15 passed, 0 failed**, 2.2 minutes after the final refresh-cookie batch |
| Separate bookings service | **35 passed, 0 failed**, 127 warnings |
| Windows/platform-core Node tests | **19 passed, 0 failed, 0 skipped** |
| React production build | Success, **0 errors**, existing lint/deprecation warnings |
| Backend configured flake8 | **0 findings** |
| mypy differential gate | **298 errors vs baseline 814; no new codes**; baseline unchanged |
| Backend pip-audit/dependency gate | **0 advisories**; baseline unchanged |
| Frontend npm audit | **130 findings**, retained and triaged above |
| Capacitor iOS sync | Success, installed plugins recognised |
| Native plist/config/scripts | plist parse, scheme check and Node syntax checks passed |
| Git diff whitespace check | Passed |
| gitleaks for review branch | **Passed** on final application-code revision |
| Android CI | **Passed**: APK build, startup and full cash/offline/restart/reconnect/exactly-one-sale acceptance |
| iOS CI | **Passed**: build, simulator install and process launch/survival; financial acceptance not covered |
| Windows CI | **Passed**: packaging/build and existing host acceptance scope |
| MongoDB coordination proofs | **Passed** on final application-code revision |

### Final GitHub Actions evidence

All five workflows completed successfully for `65ec95003585cf8e03dbd3c80a600fd40803e2a9`:

| Workflow | Completed result |
|---|---|
| Backend, configured lint/type/dependency gates, frontend build/unit, bookings, Playwright and gitleaks | [CI 38608613144](https://github.com/Sam-NUA/NUA/actions/runs/38608613144) — success |
| APK, emulator startup and critical acceptance | [Android 38608613063](https://github.com/Sam-NUA/NUA/actions/runs/38608613063) — success |
| Simulator build/install/launch | [iOS 38608613292](https://github.com/Sam-NUA/NUA/actions/runs/38608613292) — success |
| Windows foundation | [Windows 38608614018](https://github.com/Sam-NUA/NUA/actions/runs/38608614018) — success |
| Real Mongo transaction coordination | [Mongo 38608613210](https://github.com/Sam-NUA/NUA/actions/runs/38608613210) — success |

Android acceptance uses the real APK/WebView and a throwaway Docker backend/Mongo. It proves one pending cash sale survives a real process restart while offline, then drains to exactly one server transaction after reconnection, with a nonempty `clientOpId` and the correct `businessId`. It does not prove continued authorisation/sales during an offline cold start, hardware integration, every payment type or iOS parity.

The browser download endpoint returned an invalid archive in this environment; a separate scratch-only Chromium binary was used. The default static server also could not enumerate network interfaces in the execution sandbox, so the same serve-handler ran on loopback alongside the test backend. No app assertions were removed or softened. One intermediate browser run failed with a 404 while the build directory was being replaced; the final full run against an unchanged bundle passed. Native OS storage tests use mocks and browser tests use the real FastAPI/mongomock harness; neither proves physical hardware behaviour.

The full backend suite was rerun after the final backend code/test batch. No test was skipped, disabled or baseline expanded to obtain these results.


## Reference contracts

- [Capacitor configuration](https://capacitorjs.com/docs/config): supported iOS custom scheme and Android mixed-content setting.
- [Preferences privacy requirements](https://github.com/ionic-team/capacitor-plugins/blob/main/preferences/README.md): UserDefaults required-reason API declaration.
- [Filesystem privacy requirements](https://github.com/ionic-team/capacitor-filesystem/blob/main/README.md): FileTimestamp required-reason API declaration.
- Secure-storage behaviour was also checked against the installed plugin's TypeScript API and native source. Unit mocks verify adapter control flow, not OS encryption itself.
