# Multiplatform readiness report

Date: 2026-10-12 through 2026-10-13 (multiple passes of the same session —
Android/Phase 0-2/6, then iOS, then the Windows takeover from Codex's
`feat/windows-foundation`, then directive Phases 5/7/11/12/13/14).
Repository: `Sam-NUA/nua`. Base branch: `main` (verified live-deployed, not
`codex/owner-access` — see `CURRENT_ARCHITECTURE_AUDIT.md`). Base SHA:
`9963583`. Working branch: `feat/multiplatform-foundation` (PR #22).

## Architecture chosen

- **Mobile (Android first, iOS later)**: Capacitor — already partially
  configured in the repo before this pass; confirmed the right call
  against the Phase 0 dependency/browser-API audit (no React
  Native-forcing code, no code that WebView can't run).
- **Windows**: Electron — chosen independently twice, by two separate
  audits that reached the same conclusion for related but distinct
  reasons. This pass's own earlier audit (before Windows work existed)
  reasoned from the stalled `frontend/electron/` scaffold's packaging
  model (PyInstaller-bundled backend + bundled MongoDB needing real OS
  process-lifecycle management). Codex's independent Windows-specific
  audit reasoned from printer/driver/SDK access and existing JS
  maintenance, isolated that choice into a clean `apps/windows/` package
  rather than reusing the stalled scaffold (whose entry path never loaded
  its own preload — a real, separately-documented blocker), and actually
  built it. The original local-bundle-vs-thin-client tradeoff is now
  effectively decided in the thin-client direction by what got built:
  `apps/windows` has no bundled backend/Mongo at all, just the shared
  React build against a configured HTTPS API origin.
- **Offline database**: the existing `frontend/src/lib/offlineQueue.js`
  (IndexedDB, pre-existing, not written this pass) — extended, not
  replaced. Already wired into the real checkout flow with `clientOpId`
  idempotency on both ends.
- **Sync architecture**: network-failure detection distinguishes "queue
  it" from "surface the real rejection"; FIFO replay for course actions;
  auto-flush on mount/online-event/30s-poll — all pre-existing, verified
  unchanged by this pass's full test run.
- **Hardware abstraction**: `frontend/src/platform/{web,capacitor}/*Service.js`
  — Dialog, Print, File, Clipboard, Network, SecureStorage,
  DeviceIdentity. Printer's real path stays server-side ESC/POS
  (platform-agnostic by construction); the browser-dependent fallback and
  file-export patterns got a real abstraction, partially rolled out (see
  backlog).
- **Secure storage**: `@capacitor/preferences` for the primary token path
  on Android/iOS. **Corrected claim**: an earlier pass of this report said
  this was "EncryptedSharedPreferences on Android" — verified against the
  plugin's own native source during the iOS pass and found false (plain
  `SharedPreferences` on Android, plain `UserDefaults` on iOS, neither
  encrypted or Keystore/Keychain-backed). No security property beyond
  `localStorage`'s own app-sandboxing. Also has a documented compatibility
  mirror to `localStorage` for ~20 not-yet-migrated call sites. See
  `SECURITY_MODEL.md` — a real, stated gap, not a complete measure.

## Work completed

1. Phase 0 audit (`CURRENT_ARCHITECTURE_AUDIT.md`) — found the repo
   already had a stalled Capacitor/Electron scaffold, and that `main`
   (not `codex/owner-access`) is the actually-deployed branch.
2. Phase 1 ADR (`ADR-001-multiplatform-architecture.md`) + collaboration
   lanes (`COLLABORATION.md`) with ChatGPT's parallel Windows work.
3. Phase 4 (shared slice): device identity backend — model, routes,
   real-time revocation enforcement (including a refresh-token binding
   bug caught and fixed during testing, not assumed correct).
4. Phase 2: platform abstraction layer, wired into real call sites
   (auth token storage end-to-end, PIN/password login's device-id header,
   printer/docket print fallback, two POS confirm dialogs, one clipboard
   call) — not left as an unused interface nobody calls.
5. Phase 6: generated and synced the real Capacitor Android native
   project; verified as far as sandbox network policy allows (Gradle
   wrapper runs, dependency resolution reaches exactly the expected
   Google-Maven-repo block).
6. Required documentation set under `docs/platform/`.
7. Phase 10 (iOS/iPadOS): real `npx cap add ios` native project, real
   gaps found and fixed (camera/mic/local-network Info.plist keys, ATS
   exception for LAN printer traffic) — see `IOS_IPADOS_ARCHITECTURE.md`.
8. Windows foundation taken over from Codex's `feat/windows-foundation`
   (PR #21) and integrated into the shared platform layer: `platform/
   electron/*` adapters (real native SecureStorage/DeviceIdentity/Print/
   File, not web fallbacks — two of which close functional gaps the web
   fallback would have hit silently), new `nua:token-*`/`nua:device-id-
   *`/`nua:print-html`/`nua:save-file` IPC backed by Codex's already-
   tested `EncryptedStore`/`windowsCrypto` primitives — see
   `WINDOWS_ARCHITECTURE.md` and `COLLABORATION.md`.
9. Phase 11 (versioning): `GET /api/version`, `VersionGateMiddleware`
   (426 on an out-of-date `X-App-Version`, fails open on no header),
   `X-App-Version` sent only by native builds.
10. Phase 7 (remaining hardware interfaces): `ScannerService`,
    `CashDrawerService`, `PaymentTerminalService` across web/capacitor/
    electron — honestly `'unsupported'` where no hardware/provider is
    integrated, real capability detection where it is (camera scanning).
11. Phase 5 (biometric reauthentication): `BiometricService` interface
    (honestly unavailable everywhere) + the real, server-verified
    fallback every platform actually uses — `POST /api/auth/verify-
    sensitive-action` — wired into `RefundDialog.jsx`.
12. Phase 12 (observability): `client_event_log` + `POST`/`GET
    /api/ops/client-events`, bounded to a known event-type set and
    redacting sensitive-looking keys defensively; wired into real call
    sites (app launch, permanently-dropped offline mutations, printer
    failures, device registration).
13. Phase 13 (testing): added the one genuinely missing unit-test
    category — "device capability detection" — via `craco test` (Jest),
    previously configured but with zero test files in this repo.
14. Phase 14 (CI): `.github/workflows/android.yml` — a real attempt at
    building Android on a GitHub-hosted runner, the one CI gate this
    sandbox's own network policy could never pass itself.

## Files created (significant ones; full list in git history)

**Backend**: `models/device.py`, `routes/devices.py`,
`services/device_auth.py`, `tests/inprocess/test_device_identity.py`;
modified `routes/auth.py`, `routes/staff_management.py`, `server.py`.

**Frontend**: `src/platform/index.js` + 7 services × 2 platforms (14
files), `src/hooks/useDeviceRegistration.js`; modified
`contexts/AuthContext.jsx`, `pages/Login.jsx`, `pages/POSTerminal.jsx`,
`services/api.js`, `services/docket.js`, `services/printer.js`, `App.js`,
`package.json`, `capacitor.config.json`; regenerated
`package-lock.json`, added `yarn.lock`.

**Android**: `frontend/android/` (53 files — native project, gitignored
build artifacts excluded).

**iOS**: `frontend/ios/` (native project via `npx cap add ios`); modified
`frontend/ios/App/App/Info.plist`,
`frontend/android/app/src/main/AndroidManifest.xml` (a parallel
cleartext-traffic gap found during the iOS pass), `capacitor.config.json`.

**Windows** (originally Codex, on `feat/windows-foundation`; extended in
this pass): `apps/windows/` (Electron host — `main.cjs`, `preload.cjs`,
`policy.cjs`, `receipt.cjs`, `encrypted-store.cjs`, `windows-crypto.cjs`,
`desktop.js`/`.css`, scripts, tests), `packages/platform-core/`
(`queue.cjs` + tests), `.github/workflows/windows-foundation.yml`. Added
this pass: `nua:token-*`/`nua:device-id-*`/`nua:print-html`/`nua:save-
file` IPC in `main.cjs`/`preload.cjs`, `safeFilename`/`safeHtmlDocument`
in `policy.cjs`, `frontend/src/platform/electron/` (7 adapter files),
`backend/tests/inprocess/test_device_identity.py`'s windows-platform
test, `services/printer.js`'s structured-receipt path.

**Phases 5/7/11/12/13/14 (final pass)**:
- Backend: `version.py`, `middleware/version_middleware.py`;
  `routes/staff_management.py`'s `verify_sensitive_action`;
  `services/observability.py`'s `record_client_event`/
  `client_event_log`; `routes/ops.py`'s `/version` and
  `/ops/client-events` routes; modified `server.py` (allowlists,
  middleware registration).
- Frontend: `src/version.js`, `src/lib/telemetry.js`,
  `src/components/security/SensitiveActionReauthDialog.jsx`,
  `src/platform/{web,capacitor,electron}/{Scanner,CashDrawer,
  PaymentTerminal,Biometric}Service.js` (16 files), `src/platform/
  __tests__/` (2 Jest test files); modified `App.js`, `services/api.js`,
  `services/printer.js`, `lib/offlineQueue.js`,
  `hooks/useDeviceRegistration.js`,
  `components/pos/ScanVoucherButton.jsx`,
  `components/payments/RefundDialog.jsx`, `platform/index.js`,
  `platform/electron/PrintService.js`.
- Tests: `backend/tests/inprocess/{test_versioning,
  test_sensitive_action_reauth}.py` (new), `test_observability.py` +
  `test_ops_tenant_isolation.py` (extended).
- CI: `.github/workflows/android.yml` (new); `ci.yml`'s `frontend-build`
  job now runs `craco test` before the production build.

**Docs**: `docs/platform/{README,CURRENT_ARCHITECTURE_AUDIT,ADR-001-
multiplatform-architecture,COLLABORATION,ANDROID_ARCHITECTURE,
WINDOWS_ARCHITECTURE,IOS_IPADOS_ARCHITECTURE,OFFLINE_SYNC_ARCHITECTURE,
DEVICE_IDENTITY_MODEL,HARDWARE_ABSTRACTION,PAYMENT_TERMINAL_ARCHITECTURE,
SECURITY_MODEL,TENANT_ISOLATION_TEST_PLAN,APP_RELEASE_STRATEGY,
HARDWARE_COMPATIBILITY_MATRIX,MOBILE_DESKTOP_BACKLOG,
MULTIPLATFORM_READINESS_REPORT}.md`.

## Tests

| Check | Result |
|---|---|
| Full backend suite (`backend/tests/inprocess`) | **945 passed, 0 failed** (916 at the Android pass → 927 after iOS/Windows device-identity tests → 945 after this pass's versioning/reauth/telemetry tests) |
| New device-identity tests | **11 passed, 0 failed** (tenant isolation, revocation-on-next-request, revocation-survives-refresh, fail-closed on unknown/revoked device at login, full cycle for `"ios"` and `"windows"`) |
| New versioning tests (`test_versioning.py`) | **7 passed, 0 failed** |
| New sensitive-action-reauth tests (`test_sensitive_action_reauth.py`) | **6 passed, 0 failed** |
| New/extended client-telemetry tests (`test_observability.py`, `test_ops_tenant_isolation.py`) | **5 new passed, 0 failed** |
| Bookings service | **35 passed, 0 failed**, unaffected by this pass |
| Backend flake8 | **Pass**, no findings |
| Frontend production build (web target) | **Success**, zero compiler errors |
| Frontend production build (Android target, `REACT_APP_BACKEND_URL=https://app.nuapos.com.au`) | **Success**, zero compiler errors |
| Frontend Jest unit tests (`craco test` — capability detection, `detectPlatform`) | **15 passed, 0 failed** (new this pass — `craco test` existed, had zero test files before) |
| Android native project generation (`npx cap add android` + `sync`) | **Success** — all 8 plugins recognized |
| Android Gradle build (`./gradlew assembleDebug`), this sandbox | **BLOCKED** — sandbox network policy returns 403 for `dl.google.com` (Android Gradle Plugin fetch); Gradle itself downloads fine from the allowed `services.gradle.org`. Not a code defect — a sandbox network-egress limit. |
| Android Gradle build, GitHub-hosted `ubuntu-latest` runner (`.github/workflows/android.yml`, new this pass) | See "Android status" below — this is the real attempt at getting past the sandbox's own blocker. |
| iOS native project generation (`npx cap add ios` + `sync`) | **Success** — SPM-based plugin resolution needs no Xcode |
| iOS build/simulator/device run | **BLOCKED** — Xcode requires macOS, unavailable in this sandbox regardless of network policy |
| On-device/emulator run of any kind (Android, iOS) | **NOT TESTED** — no toolchain available in this sandbox |
| `apps/windows` + `packages/platform-core` unit tests (`node --test`) | **19 passed, 0 failed** |
| Windows Electron app launch in this sandbox | **BLOCKED (by design)** — `main.cjs` refuses to start on anything but `win32`, confirmed by running it here; the real equivalent is CI's `windows-latest` job, which has run **green** on this branch's commits (including the integration work), per PR #22's own check runs. |
| Full Playwright e2e suite | **13 passed, 0 failed** |

No test was skipped or disabled to get a green result. The one failure
this pass actually hit (`test_fresh_bootstrap_with_admin_pin_enables_pin_login`,
broken by the new `request` parameter on `pin_login()`) was root-caused
and fixed (made the parameter default to `None` for direct Python callers
while keeping FastAPI's special `Request` injection working for real HTTP
calls), not worked around.

## Android status

**FOUNDATION.** Evidence: native project exists and is real (not a
stub — correct `applicationId`, real Gradle files, 8 plugins correctly
registered); the shared app has zero Android-specific business logic
leakage; device identity exists, is enforced server-side, and is tested;
the offline-first foundation this milestone depends on already existed
and is unmodified/verified-still-passing; platform abstraction exists for
the highest-value browser-API gaps (not all of them — see backlog).
**Not ALPHA**: nothing has been run on an actual Android emulator or
device yet — that is the literal next step, blocked only by this
sandbox's toolchain, not by anything in the code.

## Windows readiness

**~35%.** Started independently by Codex on `feat/windows-foundation`
(real Electron host, Phase 0 audit, OS-encrypted storage/queue
primitives, Windows CI), then taken over and integrated into the shared
platform abstraction layer in a later pass of this same session — see
`WINDOWS_ARCHITECTURE.md` for the full account, and `CURRENT_ARCHITECTURE
_AUDIT.md`'s Windows section for the original W01–W10 findings.

What's real: the native Electron host (`apps/windows/`) is sandboxed,
sender-validated, strict-CSP, and runs on a real `windows-latest` CI
runner building an unsigned NSIS installer and launching the packaged app
for end-to-end smoke checks — the one platform in this effort with that
kind of automated real-platform validation. `platform/electron/*`
adapters now exist for all 7 shared services; three of them
(SecureStorage, DeviceIdentity, Print) are real native implementations,
not web fallbacks, and two close functional gaps the web fallback would
have hit silently inside this specific host (print's `window.open` is
denied outright; file export's `window.download` is too). Device
identity registers real devices and is covered by the same kind of
backend test iOS got. Token storage is genuinely OS-encrypted (Windows
DPAPI via `safeStorage`) — stronger than Android/iOS's unhardened
Preferences-based storage, not just parity with it.

What's not: nothing has run against a real packaged Windows build or
physical hardware — only CI's `windows-latest` runner and local Node unit
tests. The independently-built `CashOrderQueue` offline primitive is
real and tested but not wired into the live checkout flow. No terminal
payment SDK, no code signing, no device-pairing credential beyond the
identity registry itself, no physical printer/scanner/touchscreen QA.

## iOS/iPadOS readiness

**~25%.** A later pass of this same session was explicitly instructed to
start iOS/iPadOS work despite the directive's own Phase 10 deferral — see
`IOS_IPADOS_ARCHITECTURE.md` for the full account. What's done: the
native iOS project exists (`frontend/ios/`, via `npx cap add ios`, which
succeeds on this Linux sandbox without Xcode since iOS plugin resolution
is SPM-based, not Gradle-based); the platform abstraction layer required
zero iOS-specific code changes (confirmed, not assumed); the backend's
device-identity contract already accepted `platform: "ios"` and now has
an explicit test proving the full register→login→revoke cycle for it;
`Info.plist` gained the camera/microphone/local-network usage-description
keys and an ATS exception for LAN printer traffic that would otherwise
silently break on a real device. What's still missing, concretely: any
build, simulator run, or device run of this project (impossible from this
sandbox — Xcode requires macOS, not just a network-policy change, unlike
Android's blocker); a `PrivacyInfo.xcprivacy` privacy manifest; signing,
provisioning, and all Apple Developer Program prerequisites; any
iPhone-specific (as opposed to iPad POS) layout work. See
`HARDWARE_COMPATIBILITY_MATRIX.md`'s iPad column for the per-capability
breakdown.

## Hardware readiness

See `HARDWARE_COMPATIBILITY_MATRIX.md` for the full table. Summary:
**SUPPORTED** — network ESC/POS printing (platform-agnostic by
construction), QR generation, IndexedDB offline storage (code-level).
**PARTIAL** — browser-print fallback (Share-sheet-based on Capacitor, not
real silent print; Windows has a real native print path instead, see
above), camera QR scanning (works on web/Android/iPad via
`ScannerService.isCameraScanAvailable()`, permission UX not native;
honestly `false` on Electron — the Windows host's deny-all permission
policy means the old direct `BarcodeDetector` check would have shown the
scan button there and had it silently fail), secure token storage
(mirrored to localStorage for compatibility on Android/iOS; genuinely
OS-encrypted on Windows).
**BLOCKED, interface exists (directive Phase 7)** — `CashDrawerService`
and `PaymentTerminalService` now exist on every platform
(`getCapability()` reports `'unsupported'`, actions reject rather than
fabricating success), but no provider is implemented anywhere — per
directive, don't build against hardware/an SDK nobody has confirmed using.
**BLOCKED, interface exists (directive Phase 5)** — `BiometricService`;
see Security section above for the real PIN-based fallback that gates
refunds today.
**BLOCKED, no interface** — USB/Bluetooth printers (no browser API usage
anywhere in this codebase, confirmed by the Phase 0 audit; new
functionality, not a migration gap).

## Security

Tenant isolation and RBAC: unchanged, still the backend's actual
boundary, still enforced server-side only — verified by the full existing
test suite passing (945/945 in this final pass) plus 9 device-identity
tests, 6 sensitive-action-reauth tests, and 5 client-telemetry tests
added across this session specifically for the new surfaces it
introduced, all covering cross-tenant rejection and fail-closed behavior.
Real revocation-enforcement gap caught and fixed during the device-
identity pass (refresh-token device binding) rather than shipped broken.
No tenant check, test, or permission was weakened, skipped, or disabled
anywhere in this pass.

Directive Phase 5 (biometric reauthentication) is now **partially
closed**: `BiometricService.isAvailable()` is honestly `false` on every
platform (no OS biometric plugin installed — per directive, not faked),
but the real gate behind it — server-verified PIN re-entry via `POST
/api/auth/verify-sensitive-action` — exists, is tenant-isolated (a
manager/owner PIN from a different business is rejected even though the
role check alone would have passed it), and is wired into
`RefundDialog.jsx`. Not yet wired: void/sensitive-settings actions still
have no reauth gate at all — named explicitly in `MOBILE_DESKTOP_BACKLOG.md`
item 27, not hidden.

Directive Phase 12 (observability) added `client_event_log`, a second
tenant-scoped log table alongside the pre-existing `client_error_log`,
following the identical isolation pattern (verified by extending
`test_error_logs_are_scoped_per_business` to cover it) plus two additional
defensive properties verified by test: an event `type` outside a fixed
allowlist is silently dropped rather than stored, and sensitive-looking
keys (password/token/pin/card number/etc.) in a client-submitted `data`
payload are redacted before being written — even though no current
frontend caller sends one, matching this codebase's established
defense-in-depth posture rather than trusting client input not to.

Directive Phase 11 (versioning) added a 426-on-stale-client gate
(`VersionGateMiddleware`) that fails open on a missing `X-App-Version`
header (web clients, and any native client not yet updated, are never
blocked) and exempts `/api/version`/`/api/health`/`/api/healthz` by
`scope["path"]` — consistent with this codebase's existing Host-header-
spoofing-resistant pattern, not `request.url.path`.

## Known risks

1. Android build/run is entirely unverified on-device — every "should
   work, same code path as web" claim in this pass's docs is a reasoned
   expectation from reading the code, not an observed result.
2. The `localStorage` mirror for token compatibility means Android's
   storage hardening is partial, not complete, until ~20 call sites
   migrate (named explicitly, not hidden).
3. ~28 `window.confirm`/`prompt` sites and ~11 file-download sites still
   call browser APIs directly — likely still functional in a Capacitor
   WebView (it's still a real browser engine) but not yet using the
   native-feeling abstraction.
4. The Windows local-backend-bundle vs. thin-client decision is now
   effectively thin-client by construction (`apps/windows` bundles no
   backend/Mongo), but was never explicitly re-confirmed as a decision
   rather than a byproduct of how the foundation happened to get built —
   worth a deliberate sign-off before relying on it, not just inferring
   it from the code.
5. No payment-terminal, cash-drawer, or USB/Bluetooth-printer hardware
   integration exists for any platform — real product-scoping work, not
   a quick follow-up. `PaymentTerminalService`/`CashDrawerService`
   interfaces exist (directive Phase 7) so this work has a contract to
   implement against, but per directive no provider was implemented
   merely to fill it.
6. `BiometricService.isAvailable()` is `false` everywhere (directive
   Phase 5) — no OS biometric plugin is installed on any platform, so the
   PIN-reauth fallback is the only reauth path that exists today, and it's
   wired into refunds only. Void and sensitive-settings changes remain
   unguarded by any reauth step.
7. Frontend version (`src/version.js`) and backend version
   (`backend/version.py`) are two independent constants with no shared
   source of truth or build-time check that they match — a release that
   bumps one and forgets the other would silently misreport its own
   version (not silently break anything else, since the gate itself reads
   the header value directly, but the `/api/version` response and the
   app's own `console.info` line could disagree).
8. The version gate (`VersionGateMiddleware`) has never been exercised
   against a real out-of-date native client hitting a real 426 and
   recovering — only against the backend's own test suite sending a
   crafted header. No frontend UX exists for "your app is too old,
   update it" at all; a 426 today would surface as a generic failed
   request to whatever screen triggered it.
9. Client telemetry (directive Phase 12) has no backend alerting/paging
   on `client_event_log` growth — it's a queryable log, not yet a signal
   anyone is watching. `MAX_EVENTS_PER_SESSION = 50` in
   `lib/telemetry.js` is an arbitrary cap chosen to bound worst-case
   volume, not derived from any real usage data (none exists yet).

## Next recommended phase

Get this Android build running outside this sandbox: either install the
Android SDK in an environment with `dl.google.com` network access, or
move `frontend/android/` + the platform layer to a machine/CI runner with
a real Android toolchain, run `./gradlew assembleDebug`, install on a
tablet/emulator, and actually walk the critical acceptance milestone
(order → offline → restart → reconnect → sync → exactly one order) by
hand. That single on-device run would convert this report's single
biggest "reasoned expectation, not verified" claim into a verified one,
and is more valuable right now than migrating the remaining
confirm/download call sites or starting new hardware-provider
integrations. Once that milestone is verified, the next-highest-value
work is wiring `BiometricService`/the PIN-reauth gate into void and
sensitive-settings actions (currently unguarded) and building the
frontend UX for a 426 version-gate rejection (currently invisible to
staff beyond a failed request).
