# Hardware compatibility matrix

Legend: SUPPORTED (verified working or unchanged-and-platform-agnostic) ·
PARTIAL (works with a caveat) · PLANNED (abstraction exists, real
implementation doesn't) · BLOCKED (no path without new work) ·
NOT APPLICABLE · NOT TESTED (code exists, never run on that platform)

| Capability | Web | Android (Capacitor) | Windows (Electron) | iPad |
|---|---|---|---|---|
| Network printer (ESC/POS) | SUPPORTED | SUPPORTED (server-side, no client dependency) | SUPPORTED | SUPPORTED |
| Browser/popup print fallback | SUPPORTED | PARTIAL (routes to native Share sheet, not real silent print) | SUPPORTED (routes through `nua:print-html` — a disposable, `javascript:false` preview window; the web `window.open` path is unconditionally denied by the host's own navigation policy, so this is a real adapter, not a fallback) | PARTIAL (same `@capacitor/share` route as Android — cross-platform plugin, never run on a device/simulator) |
| USB printer | NOT APPLICABLE (no code) | BLOCKED (no plugin installed) | BLOCKED (no plugin installed) | BLOCKED (no plugin installed) |
| Bluetooth printer | NOT APPLICABLE (no code) | BLOCKED (no plugin installed) | NOT APPLICABLE | BLOCKED (no plugin installed) |
| Cash drawer | NOT APPLICABLE (no code anywhere) | BLOCKED | BLOCKED | BLOCKED |
| QR code generation | SUPPORTED | SUPPORTED (pure rendering, no native dependency) | SUPPORTED | SUPPORTED (pure rendering, same as Android) |
| Camera QR/barcode scanning | SUPPORTED (`getUserMedia`) | PARTIAL (works via raw `getUserMedia`, permission UX not native) | BLOCKED (the host's session denies every permission check/request outright — `setPermissionCheckHandler(() => false)` — so the shared `getUserMedia` code is reachable but can never actually get a grant, not simply unused) | PARTIAL (same raw `getUserMedia` path inside WKWebView; `NSCameraUsageDescription`/`NSMicrophoneUsageDescription` added to Info.plist this pass so the OS permission prompt fires at all — never run on a device/simulator) |
| Payment terminal SDK | NOT APPLICABLE (no SDK integrated) | BLOCKED | BLOCKED | BLOCKED |
| Offline database (IndexedDB) | SUPPORTED | SUPPORTED (same API, not independently verified on-device) | SUPPORTED (real Chromium IndexedDB; not wired to the live checkout flow — see `packages/platform-core`'s separate, scoped cash queue in OFFLINE_SYNC_ARCHITECTURE.md) | SUPPORTED (same API inside WKWebView, not independently verified on-device) |
| Secure token storage | SUPPORTED (localStorage, as before) | SUPPORTED, not hardened (`@capacitor/preferences`, verified plain `SharedPreferences`/`MODE_PRIVATE` — not encrypted, not Keystore-backed, same theft-resistance as localStorage; mirrored to localStorage for compatibility — see SECURITY_MODEL.md) | SUPPORTED, hardened (`nua:token-*` IPC backed by `EncryptedStore` + real Windows DPAPI via `safeStorage` — verified encrypted-at-rest and failing closed with no plaintext fallback in `apps/windows/test/store.test.cjs` and `security.test.cjs`; genuinely stronger than Android/iOS's unhardened storage, not just parity with it) | SUPPORTED, not hardened (`@capacitor/preferences`, verified plain `UserDefaults.standard` — not encrypted, not Keychain-backed; mirrored to localStorage — see SECURITY_MODEL.md) |
| Device identity / revocation | SUPPORTED (opt-in, not auto-registered) | SUPPORTED (auto-registers on first session) | SUPPORTED (auto-registers via `platform/electron/DeviceIdentityService.js` + `nua:device-id-*` IPC; backend's `ALLOWED_PLATFORMS` already included `"windows"`, now exercised by a dedicated test — never run against a real packaged Windows build, only local unit tests and CI's `windows-latest` runner) | SUPPORTED (identical code path to Android via `platform/capacitor/DeviceIdentityService.js`; backend's `ALLOWED_PLATFORMS` already includes `"ios"` — never run on a device/simulator) |
| Auto-update | NOT APPLICABLE (web deploy) | NOT STARTED | NOT STARTED (`apps/windows`'s electron-builder config produces an unsigned NSIS installer in CI; no signing identity or auto-update mechanism wired) | NOT STARTED (App Store review process is the update channel; no in-app update mechanism applicable or built) |
| Clipboard | SUPPORTED | SUPPORTED (`@capacitor/clipboard`) | SUPPORTED (web fallback, real Chromium clipboard — the host's permission-deny-all policy has not been observed to gate user-gesture clipboard writes) | SUPPORTED (`@capacitor/clipboard`, same cross-platform plugin as Android) |
| File export/download | SUPPORTED (`<a download>`) | PARTIAL (routes to Filesystem+Share, only migrated for one call site; ~11 others still use the old web-only pattern directly — see backlog) | SUPPORTED (routes through `nua:save-file` — a native Save dialog + direct disk write; the web `<a download>` path is silently blocked by the host's own `will-download` handler, with no error surfaced, so this is a real fix, not an adapter for its own sake) | PARTIAL (same Filesystem+Share route and same partial call-site migration as Android — see backlog) |

Nothing in this table claims verification this pass didn't actually
perform. "SUPPORTED" for Android/IndexedDB, for example, means "same API,
documented as Capacitor-compatible by Capacitor's own platform support
matrix" — not "we ran it on a device and watched it work," because no
Android SDK/emulator was available in this sandbox (see
`CURRENT_ARCHITECTURE_AUDIT.md`'s toolchain section). The iPad column
carries the same caveat, with a harder underlying blocker: `npx cap add
ios` scaffolds successfully on Linux (Capacitor's iOS plugin resolution
is Swift-Package-Manager-based, not Gradle-based), but actually compiling
or running the app requires Xcode, which only runs on macOS — categorically
unavailable in this sandbox regardless of network policy, unlike
Android's `dl.google.com` block which is a policy restriction, not a
platform impossibility.

The Windows column has a real asymmetry worth stating plainly: unlike
Android and iPad, `.github/workflows/windows-foundation.yml` runs on a
real `windows-latest` GitHub Actions runner, builds an actual unsigned
NSIS installer, and launches the real packaged Electron app for
`apps/windows/scripts/smoke.cjs`'s end-to-end checks (bridge shape,
sandbox flags, navigation/popup denial, a real `safeStorage`
encrypt/decrypt round-trip) — the one platform in this table with a
genuine automated on-device-equivalent run, not just "documented as
compatible." This sandbox still can't run that job itself (`apps/windows/
src/main.cjs` refuses to start on anything but `win32`, confirmed by
running it here), so "SUPPORTED" above still means "verified by local
unit tests plus that CI job having a real Windows runner to answer to,"
not "watched by hand on a physical Windows PC with real POS hardware" —
no row in this table claims that.
