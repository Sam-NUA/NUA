# Hardware compatibility matrix

Legend: SUPPORTED (code path exists; physical venue acceptance still required) ·
PARTIAL (works with a caveat) · PLANNED (abstraction exists, real
implementation doesn't) · BLOCKED (no path without new work) ·
NOT APPLICABLE · NOT TESTED (code exists, never run on that platform)

This table is about client/platform capabilities specifically. The "BLOCKED"
payment-terminal row below is about the *client-side* SDK only — the
backend has tenant-scoped routes and partial, unverified provider adapters
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
| Biometric reauthentication | BLOCKED (no biometric adapter; server PIN approval gates selected sensitive actions) | BLOCKED (same) | BLOCKED (same) | BLOCKED (same) |
| Offline cash queue | SUPPORTED (tenant/user/device-scoped queue; server remains authoritative) | SUPPORTED (packaged AVD outage/restart/exactly-once replay against isolated backend passed) | SUPPORTED (live shared checkout integration with encrypted host queue; packaged Windows CI restart/account-switch/exactly-once replay passed) | SUPPORTED (packaged Simulator outage/restart/refresh/replay acceptance against isolated backend passed) |
| Secure token storage | SUPPORTED (web localStorage bearer token) | SUPPORTED (OS Keystore-backed encrypted token; legacy plaintext purged, no localStorage mirror or fallback; packaged AVD restart acceptance passed) | SUPPORTED (DPAPI through sender-validated IPC, no plaintext fallback; packaged Windows CI smoke/critical acceptance passed) | SUPPORTED (Keychain-backed token; legacy plaintext purged, no localStorage mirror; durable refresh handled by `NuaRefreshSession`; packaged Simulator restart/refresh acceptance passed) |
| Device identity / revocation | SUPPORTED (opt-in device registration) | SUPPORTED (session bound before protected checkout; device revocation enforced by backend) | SUPPORTED (session binding and encrypted host identity; packaged Windows CI account-switch checks passed) | SUPPORTED (Simulator PIN login reuses verified device binding; backend remains authoritative) |
| Auto-update | NOT APPLICABLE (web deploy) | NOT STARTED | NOT STARTED (`apps/windows`'s electron-builder config produces an unsigned NSIS installer in CI; no signing identity or auto-update mechanism wired) | NOT STARTED (App Store review process is the update channel; no in-app update mechanism applicable or built) |
| Clipboard | SUPPORTED | SUPPORTED (`@capacitor/clipboard`) | SUPPORTED (web fallback, real Chromium clipboard — the host's permission-deny-all policy has not been observed to gate user-gesture clipboard writes) | SUPPORTED (`@capacitor/clipboard`, same cross-platform plugin as Android) |
| File export/download | SUPPORTED (`<a download>`) | PARTIAL (routes to Filesystem+Share, only migrated for one call site; ~11 others still use the old web-only pattern directly — see backlog) | SUPPORTED (routes through `nua:save-file` — a native Save dialog + direct disk write; the web `<a download>` path is silently blocked by the host's own `will-download` handler, with no error surfaced, so this is a real fix, not an adapter for its own sake) | PARTIAL (same Filesystem+Share route and same partial call-site migration as Android — see backlog) |

## Verification boundaries

Android `android.yml` boots an AVD and drives the actual APK through cash sale,
outage, process restart and exactly-once replay against an isolated backend.
iOS `ios.yml` builds on macOS, launches a booted Simulator and uses Appium for
PIN/device binding, cold-restart refresh faults and replay. Windows
`windows-foundation.yml` builds the actual Electron host, checks sandbox/IPC/DPAPI
and exercises restart/account-switch/exactly-once replay against loopback.
These jobs passed on reviewed frontend commit
`f6d62d0eb64bf344b49c289b16f4997f7ba52587` before its integration into main.

No physical Android/iOS device or venue printer/drawer/scanner/EFTPOS acceptance
is established by these CI runs. Camera/share/export rows retain their specific
unverified limits; successful cash replay does not certify those capabilities.
Server-side TCP printer/terminal code also needs a verified network path from
the deployed backend to the venue; a cloud host does not implicitly reach a
private venue LAN. An interface or route is not proof of hardware support.

Native token handling is defined by `SecureStorageService`, `sessionToken.js`
and (iOS refresh) `nativeRefreshSession.js`; older claims in `SECURITY_MODEL.md`
about plaintext mirrors/migration are historical. Legacy native plaintext is
purged and users sign in afresh; OS storage errors fail closed.
See [current build guide](CURRENT_BUILD_GUIDE.md),
[release strategy](APP_RELEASE_STRATEGY.md) and
[payment terminal limits](PAYMENT_TERMINAL_ARCHITECTURE.md).
