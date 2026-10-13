# Hardware compatibility matrix

Legend: SUPPORTED (verified working or unchanged-and-platform-agnostic) ·
PARTIAL (works with a caveat) · PLANNED (abstraction exists, real
implementation doesn't) · BLOCKED (no path without new work) ·
NOT APPLICABLE · NOT TESTED (code exists, never run on that platform)

| Capability | Web | Android (Capacitor) | Windows (Electron) | iPad |
|---|---|---|---|---|
| Network printer (ESC/POS) | SUPPORTED | SUPPORTED (server-side, no client dependency) | SUPPORTED | SUPPORTED |
| Browser/popup print fallback | SUPPORTED | PARTIAL (routes to native Share sheet, not real silent print) | SUPPORTED (Chromium webview) | PARTIAL (same `@capacitor/share` route as Android — cross-platform plugin, never run on a device/simulator) |
| USB printer | NOT APPLICABLE (no code) | BLOCKED (no plugin installed) | BLOCKED (no plugin installed) | BLOCKED (no plugin installed) |
| Bluetooth printer | NOT APPLICABLE (no code) | BLOCKED (no plugin installed) | NOT APPLICABLE | BLOCKED (no plugin installed) |
| Cash drawer | NOT APPLICABLE (no code anywhere) | BLOCKED | BLOCKED | BLOCKED |
| QR code generation | SUPPORTED | SUPPORTED (pure rendering, no native dependency) | SUPPORTED | SUPPORTED (pure rendering, same as Android) |
| Camera QR/barcode scanning | SUPPORTED (`getUserMedia`) | PARTIAL (works via raw `getUserMedia`, permission UX not native) | NOT APPLICABLE (no camera use case) | PARTIAL (same raw `getUserMedia` path inside WKWebView; `NSCameraUsageDescription`/`NSMicrophoneUsageDescription` added to Info.plist this pass so the OS permission prompt fires at all — never run on a device/simulator) |
| Payment terminal SDK | NOT APPLICABLE (no SDK integrated) | BLOCKED | BLOCKED | BLOCKED |
| Offline database (IndexedDB) | SUPPORTED | SUPPORTED (same API, not independently verified on-device) | SUPPORTED | SUPPORTED (same API inside WKWebView, not independently verified on-device) |
| Secure token storage | SUPPORTED (localStorage, as before) | SUPPORTED, not hardened (`@capacitor/preferences`, verified plain `SharedPreferences`/`MODE_PRIVATE` — not encrypted, not Keystore-backed, same theft-resistance as localStorage; mirrored to localStorage for compatibility — see SECURITY_MODEL.md) | SUPPORTED (localStorage, unchanged) | SUPPORTED, not hardened (`@capacitor/preferences`, verified plain `UserDefaults.standard` — not encrypted, not Keychain-backed; mirrored to localStorage — see SECURITY_MODEL.md) |
| Device identity / revocation | SUPPORTED (opt-in, not auto-registered) | SUPPORTED (auto-registers on first session) | PLANNED (backend contract supports `platform: "windows"`, Electron-side registration not built — ChatGPT's lane) | SUPPORTED (identical code path to Android via `platform/capacitor/DeviceIdentityService.js`; backend's `ALLOWED_PLATFORMS` already includes `"ios"` — never run on a device/simulator) |
| Auto-update | NOT APPLICABLE (web deploy) | NOT STARTED | NOT STARTED (electron-builder NSIS config exists, no auto-update mechanism wired) | NOT STARTED (App Store review process is the update channel; no in-app update mechanism applicable or built) |
| Clipboard | SUPPORTED | SUPPORTED (`@capacitor/clipboard`) | SUPPORTED (web fallback, real Chromium clipboard) | SUPPORTED (`@capacitor/clipboard`, same cross-platform plugin as Android) |
| File export/download | SUPPORTED (`<a download>`) | PARTIAL (routes to Filesystem+Share, only migrated for one call site; ~11 others still use the old web-only pattern directly — see backlog) | SUPPORTED (web fallback works in Electron's renderer) | PARTIAL (same Filesystem+Share route and same partial call-site migration as Android — see backlog) |

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
