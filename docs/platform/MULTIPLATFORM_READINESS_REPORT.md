# Multiplatform readiness report

Date: 2026-10-12. Repository: `Sam-NUA/nua`. Base branch: `main` (verified
live-deployed, not `codex/owner-access` — see `CURRENT_ARCHITECTURE_AUDIT.md`).
Base SHA: `9963583`. Working branch: `feat/multiplatform-foundation`.
Final SHA at time of this report: `8f47b42`.

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
| Full backend suite (`backend/tests/inprocess`) | **927 passed, 0 failed** (916 before this pass's own device-identity tests: 9 original + ios + windows) |
| New device-identity tests | **11 passed, 0 failed** (tenant isolation, revocation-on-next-request, revocation-survives-refresh, fail-closed on unknown/revoked device at login, full cycle for `"ios"` and `"windows"`) |
| Bookings service | **35 passed, 0 failed**, unaffected by this pass |
| Backend flake8 | **Pass**, no findings |
| Frontend production build (web target) | **Success**, zero compiler errors |
| Frontend production build (Android target, `REACT_APP_BACKEND_URL=https://app.nuapos.com.au`) | **Success**, zero compiler errors |
| Android native project generation (`npx cap add android` + `sync`) | **Success** — all 8 plugins recognized |
| Android Gradle build (`./gradlew assembleDebug`) | **BLOCKED** — sandbox network policy returns 403 for `dl.google.com` (Android Gradle Plugin fetch); Gradle itself downloads fine from the allowed `services.gradle.org`. Not a code defect — a sandbox network-egress limit. |
| iOS native project generation (`npx cap add ios` + `sync`) | **Success** — SPM-based plugin resolution needs no Xcode |
| iOS build/simulator/device run | **BLOCKED** — Xcode requires macOS, unavailable in this sandbox regardless of network policy |
| On-device/emulator run of any kind (Android, iOS) | **NOT TESTED** — no toolchain available in this sandbox |
| `apps/windows` + `packages/platform-core` unit tests (`node --test`) | **19 passed, 0 failed** |
| Windows Electron app launch in this sandbox | **BLOCKED (by design)** — `main.cjs` refuses to start on anything but `win32`, confirmed by running it here; the real equivalent is CI's `windows-latest` job |
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
above), camera QR scanning (works on web/Android/iPad, permission UX not
native; blocked outright inside the Windows host's deny-all permission
policy), secure token storage (mirrored to localStorage for compatibility
on Android/iOS; genuinely OS-encrypted on Windows).
**BLOCKED/not started** — cash drawer, USB/Bluetooth printers, payment
terminal SDKs (none implemented for any platform, per directive: don't
build against an unconfirmed provider).

## Security

Tenant isolation and RBAC: unchanged, still the backend's actual
boundary, still enforced server-side only — verified by the full existing
test suite passing unchanged (925/925) plus 9 new tests specifically for
the one new surface (device identity) this pass added, covering
cross-tenant list/revoke/heartbeat rejection and fail-closed behavior on
unknown/revoked device ids. Real revocation-enforcement gap caught and
fixed during this pass (refresh-token device binding) rather than shipped
broken. No tenant check, test, or permission was weakened, skipped, or
disabled anywhere in this pass. One named, not-yet-closed gap: biometric
reauthentication for sensitive actions (directive Phase 5) wasn't
implemented.

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
   a quick follow-up.

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
confirm/download call sites or starting iOS/Windows work.
