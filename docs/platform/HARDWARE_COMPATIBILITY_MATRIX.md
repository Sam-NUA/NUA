# Hardware compatibility matrix

Legend: SUPPORTED (verified working or unchanged-and-platform-agnostic) ·
PARTIAL (works with a caveat) · PLANNED (abstraction exists, real
implementation doesn't) · BLOCKED (no path without new work) ·
NOT APPLICABLE · NOT TESTED (code exists, never run on that platform)

This table is about client/platform capabilities specifically. The "BLOCKED"
payment-terminal row below is about the *client-side* SDK only — the
backend already has a real, tenant-scoped terminal integration
(`backend/services/eftpos_service.py`, routes under `/api/eftpos/*`) that
every platform's frontend can already call; see
`PAYMENT_TERMINAL_ARCHITECTURE.md` for what that covers and what's still
unverified about it.

| Capability | Web | Android (Capacitor) | Windows (Electron) | iPad |
|---|---|---|---|---|
| Network printer (ESC/POS) | SUPPORTED | SUPPORTED (server-side, no client dependency) | SUPPORTED | SUPPORTED |
| Browser/popup print fallback | SUPPORTED | PARTIAL (routes to native Share sheet, not real silent print) | SUPPORTED (routes through `nua:print-html` — a disposable, `javascript:false` preview window; the web `window.open` path is unconditionally denied by the host's own navigation policy, so this is a real adapter, not a fallback) | PARTIAL (same `@capacitor/share` route as Android — cross-platform plugin, never run on a device/simulator) |
| USB printer | NOT APPLICABLE (no code) | BLOCKED (no plugin installed) | BLOCKED (no plugin installed) | BLOCKED (no plugin installed) |
| Bluetooth printer | NOT APPLICABLE (no code) | BLOCKED (no plugin installed) | NOT APPLICABLE | BLOCKED (no plugin installed) |
| Cash drawer | BLOCKED (`CashDrawerService` interface exists, reports `'unsupported'`) | BLOCKED (same interface, same answer) | BLOCKED (same interface, same answer) | BLOCKED (same interface, same answer) |
| QR code generation | SUPPORTED | SUPPORTED (pure rendering, no native dependency) | SUPPORTED | SUPPORTED (pure rendering, same as Android) |
| Camera QR/barcode scanning | SUPPORTED (`getUserMedia`) | PARTIAL (works via raw `getUserMedia`, permission UX not native) | BLOCKED (the host's session denies every permission check/request outright — `setPermissionCheckHandler(() => false)` — so the shared `getUserMedia` code is reachable but can never actually get a grant, not simply unused) | PARTIAL (same raw `getUserMedia` path inside WKWebView; `NSCameraUsageDescription`/`NSMicrophoneUsageDescription` added to Info.plist this pass so the OS permission prompt fires at all — never run on a device/simulator) |
| Payment terminal SDK (client-side, for a tablet-attached card reader) | BLOCKED (`PaymentTerminalService` interface exists, reports `'unsupported'`) | BLOCKED (same interface, same answer) | BLOCKED (same interface, same answer) | BLOCKED (same interface, same answer) |
| Biometric reauthentication | BLOCKED (`BiometricService` interface exists; `isAvailable()` is `false` — PIN re-entry via `POST /api/auth/verify-sensitive-action` is the real gate, wired into refunds only) | BLOCKED (same interface, same answer) | BLOCKED (same interface, same answer) | BLOCKED (same interface, same answer) |
| Offline database (IndexedDB) | SUPPORTED | SUPPORTED (same API, not independently verified on-device) | SUPPORTED (real Chromium IndexedDB; not wired to the live checkout flow — see `packages/platform-core`'s separate, scoped cash queue in OFFLINE_SYNC_ARCHITECTURE.md) | SUPPORTED (same API inside WKWebView, not independently verified on-device) |
| Secure token storage | SUPPORTED (localStorage, as before) | SUPPORTED, hardened (`capacitor-secure-storage-plugin`, verified against its own native source: a real `AndroidKeyStore` RSA keypair encrypts the value before it's written to `SharedPreferences` — ciphertext at rest, decrypting key never leaves the Keystore; mirrored to localStorage for ~20 legacy call sites — see SECURITY_MODEL.md. **Now run for real, not just mocked**: `android.yml`'s `critical-acceptance-milestone` job force-stops and relaunches the real packaged app on a real AVD mid-session (`android-critical-milestone.cjs`), and the stored session survives that restart) | SUPPORTED, hardened (`nua:token-*` IPC backed by `EncryptedStore` + real Windows DPAPI via `safeStorage` — verified encrypted-at-rest and failing closed with no plaintext fallback in `apps/windows/test/store.test.cjs` and `security.test.cjs`) | SUPPORTED, hardened (same `capacitor-secure-storage-plugin`, verified against its iOS native source: real system Keychain via `SwiftKeychainWrapper`, not `UserDefaults`; mirrored to localStorage — see SECURITY_MODEL.md. **Now run for real**: `ios.yml`'s `critical-acceptance-milestone` drives the real packaged app on a real booted iOS Simulator through PIN login, device binding, and a cold-restart fault-injection test that specifically exercises this exact storage/refresh path) |
| Device identity / revocation | SUPPORTED (opt-in, not auto-registered) | SUPPORTED (auto-registers on first session) | SUPPORTED (auto-registers via `platform/electron/DeviceIdentityService.js` + `nua:device-id-*` IPC; backend's `ALLOWED_PLATFORMS` already included `"windows"`, now exercised by a dedicated test — never run against a real packaged Windows build on physical hardware, but a real `windows-latest` CI runner does launch the packaged app itself, see the Windows note below) | SUPPORTED (identical code path to Android via `platform/capacitor/DeviceIdentityService.js`; backend's `ALLOWED_PLATFORMS` already includes `"ios"`. **Now run for real**: `ios.yml`'s `critical-acceptance-milestone` registers a real device binding on a real booted Simulator and asserts PIN login reuses that same binding rather than creating a duplicate — not just a code-path claim) |
| Auto-update | NOT APPLICABLE (web deploy) | NOT STARTED | NOT STARTED (`apps/windows`'s electron-builder config produces an unsigned NSIS installer in CI; no signing identity or auto-update mechanism wired) | NOT STARTED (App Store review process is the update channel; no in-app update mechanism applicable or built) |
| Clipboard | SUPPORTED | SUPPORTED (`@capacitor/clipboard`) | SUPPORTED (web fallback, real Chromium clipboard — the host's permission-deny-all policy has not been observed to gate user-gesture clipboard writes) | SUPPORTED (`@capacitor/clipboard`, same cross-platform plugin as Android) |
| File export/download | SUPPORTED (`<a download>`) | PARTIAL (routes to Filesystem+Share, only migrated for one call site; ~11 others still use the old web-only pattern directly — see backlog) | SUPPORTED (routes through `nua:save-file` — a native Save dialog + direct disk write; the web `<a download>` path is silently blocked by the host's own `will-download` handler, with no error surfaced, so this is a real fix, not an adapter for its own sake) | PARTIAL (same Filesystem+Share route and same partial call-site migration as Android — see backlog) |

Nothing in this table claims verification this pass didn't actually
perform. Where a cell says "SUPPORTED" with no further note (IndexedDB,
clipboard, QR generation, ...), that still means "same API, documented as
Capacitor-compatible by Capacitor's own platform support matrix" — this
authoring sandbox has no Android SDK/emulator, and Xcode only runs on
macOS, so neither was ever run by hand here. **That is a statement about
this sandbox, not about whether the capability has been run on a real
device anywhere** — it hasn't been, across the whole deployment, only for
rows explicitly marked otherwise below.

Every row marked "**Now run for real**" above has since been exercised by
GitHub Actions on a real emulator or simulator, not just claimed
compatible: `android.yml`'s `emulator-smoke-test` boots a real AVD,
installs the actual built APK, launches it, and checks the process
survives with a clean logcat; its `critical-acceptance-milestone` goes
further, driving a real order→offline→restart→reconnect→sync round trip
against a throwaway backend on that same real AVD. `ios.yml` has the
equivalent pair: a plain launch-and-survive job on a real booted iOS
Simulator, and its own `critical-acceptance-milestone` driving PIN login,
device binding, and a cold-restart fault-injection test through Appium
against a real booted Simulator. Both are real, automated, CI-verified
runs — this authoring sandbox still can't run either of them itself (no
emulator/Xcode here), but "never run on a device/simulator" is no longer
true of the deployment as a whole for the specific capabilities called
out above. What's still genuinely untested anywhere: a *physical* Android
tablet/phone or iPhone/iPad, and any real printer/drawer/scanner/EFTPOS
hardware — an emulator or simulator is not a substitute for either, and
no row in this table claims it is.

The Windows column has had a head start on this: `.github/workflows/
windows-foundation.yml` runs on a real `windows-latest` GitHub Actions
runner, builds an actual unsigned NSIS installer, and launches the real
packaged Electron app for `apps/windows/scripts/smoke.cjs`'s end-to-end
checks (bridge shape, sandbox flags, navigation/popup denial, a real
`safeStorage` encrypt/decrypt round-trip). This sandbox still can't run
that job itself (`apps/windows/src/main.cjs` refuses to start on anything
but `win32`, confirmed by running it here), so "SUPPORTED" for Windows
still means "verified by local unit tests plus that CI job having a real
Windows runner to answer to," not "watched by hand on a physical Windows
PC with real POS hardware" — no row in this table claims that, for any
platform.
