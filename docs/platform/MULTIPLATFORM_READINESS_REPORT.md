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
- **Windows**: Electron — already partially scaffolded before this pass;
  kept over Tauri because the existing packaging model
  (PyInstaller-bundled backend + bundled MongoDB) needs real OS
  process-lifecycle management Electron's Node main process gives for
  free and Tauri would require rebuilding in Rust from nothing. One
  tradeoff left open on purpose: finish that local-bundle model, or switch
  to a thin client sharing Android's offline queue — ChatGPT's call, not
  pre-decided here.
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
- **Secure storage**: `@capacitor/preferences` (EncryptedSharedPreferences
  on Android) for the primary token path, with a documented
  compatibility mirror to `localStorage` for ~20 not-yet-migrated call
  sites — a real, stated partial measure, not a complete one.

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
| Full backend suite (`backend/tests/inprocess`) | **925 passed, 0 failed** (916 before this pass's own 9 new tests) |
| New device-identity tests | **9 passed, 0 failed** (tenant isolation, revocation-on-next-request, revocation-survives-refresh, fail-closed on unknown/revoked device at login) |
| Bookings service | **35 passed, 0 failed**, unaffected by this pass |
| Backend flake8 | **Pass**, no findings |
| Frontend production build (web target) | **Success**, zero compiler errors |
| Frontend production build (Android target, `REACT_APP_BACKEND_URL=https://app.nuapos.com.au`) | **Success**, zero compiler errors |
| Android native project generation (`npx cap add android` + `sync`) | **Success** — all 8 plugins recognized |
| Android Gradle build (`./gradlew assembleDebug`) | **BLOCKED** — sandbox network policy returns 403 for `dl.google.com` (Android Gradle Plugin fetch); Gradle itself downloads fine from the allowed `services.gradle.org`. Not a code defect — a sandbox network-egress limit. |
| On-device/emulator run of any kind | **NOT TESTED** — no Android SDK/emulator available in this sandbox |

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

Explicitly ChatGPT's lane this pass (per user direction). What Claude's
work leaves available to it: the backend device-identity contract already
accepts `platform: "windows"`; `platform/index.js` already detects
`'electron'` and falls back correctly to web-equivalent behavior for
every service not yet given an Electron-specific implementation.
**Percentage: not assessed by this pass** — assessing someone else's
in-progress parallel work isn't this pass's job; see
`WINDOWS_ARCHITECTURE.md` for what's handed off and why.

## iOS/iPadOS readiness

**~5%.** Nothing iOS-specific was built (correctly, per the directive's
own Phase 10 deferral and because Android validation isn't done yet).
Every Capacitor plugin installed this pass already supports iOS without
further work; no `@capacitor/ios` dependency or native project exists.
Blockers: no Xcode/macOS runner anywhere in this pass's environment
either way.

## Hardware readiness

See `HARDWARE_COMPATIBILITY_MATRIX.md` for the full table. Summary:
**SUPPORTED** — network ESC/POS printing (platform-agnostic by
construction), QR generation, IndexedDB offline storage (code-level).
**PARTIAL** — browser-print fallback (Share-sheet-based on Capacitor, not
real silent print), camera QR scanning (works, permission UX not native),
secure token storage (mirrored to localStorage for compatibility), device
identity (Android done, Windows contract-ready-not-implemented).
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
4. The Windows local-backend-bundle vs. thin-client decision is
   unresolved — whoever builds it needs to actually choose, not
   accidentally default into whichever half the current stalled scaffold
   leans toward.
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
