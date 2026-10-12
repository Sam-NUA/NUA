# Hardware compatibility matrix

Legend: SUPPORTED (verified working or unchanged-and-platform-agnostic) ·
PARTIAL (works with a caveat) · PLANNED (abstraction exists, real
implementation doesn't) · BLOCKED (no path without new work) ·
NOT APPLICABLE · NOT TESTED (code exists, never run on that platform)

| Capability | Web | Android (Capacitor) | Windows (Electron) | iPad |
|---|---|---|---|---|
| Network printer (ESC/POS) | SUPPORTED | SUPPORTED (server-side, no client dependency) | SUPPORTED | SUPPORTED |
| Browser/popup print fallback | SUPPORTED | PARTIAL (routes to native Share sheet, not real silent print) | SUPPORTED (Chromium webview) | NOT TESTED |
| USB printer | NOT APPLICABLE (no code) | BLOCKED (no plugin installed) | BLOCKED (no plugin installed) | NOT APPLICABLE |
| Bluetooth printer | NOT APPLICABLE (no code) | BLOCKED (no plugin installed) | NOT APPLICABLE | NOT APPLICABLE |
| Cash drawer | NOT APPLICABLE (no code anywhere) | BLOCKED | BLOCKED | NOT APPLICABLE |
| QR code generation | SUPPORTED | SUPPORTED (pure rendering, no native dependency) | SUPPORTED | NOT TESTED |
| Camera QR/barcode scanning | SUPPORTED (`getUserMedia`) | PARTIAL (works via raw `getUserMedia`, permission UX not native) | NOT APPLICABLE (no camera use case) | NOT TESTED |
| Payment terminal SDK | NOT APPLICABLE (no SDK integrated) | BLOCKED | BLOCKED | NOT APPLICABLE |
| Offline database (IndexedDB) | SUPPORTED | SUPPORTED (same API, not independently verified on-device) | SUPPORTED | NOT TESTED |
| Secure token storage | SUPPORTED (localStorage, as before) | PARTIAL (`@capacitor/preferences`, but mirrored to localStorage for compatibility — see SECURITY_MODEL.md) | SUPPORTED (localStorage, unchanged) | NOT APPLICABLE |
| Device identity / revocation | SUPPORTED (opt-in, not auto-registered) | SUPPORTED (auto-registers on first session) | PLANNED (backend contract supports `platform: "windows"`, Electron-side registration not built — ChatGPT's lane) | NOT APPLICABLE |
| Auto-update | NOT APPLICABLE (web deploy) | NOT STARTED | NOT STARTED (electron-builder NSIS config exists, no auto-update mechanism wired) | NOT APPLICABLE |
| Clipboard | SUPPORTED | SUPPORTED (`@capacitor/clipboard`) | SUPPORTED (web fallback, real Chromium clipboard) | NOT TESTED |
| File export/download | SUPPORTED (`<a download>`) | PARTIAL (routes to Filesystem+Share, only migrated for one call site; ~11 others still use the old web-only pattern directly — see backlog) | SUPPORTED (web fallback works in Electron's renderer) | NOT TESTED |

Nothing in this table claims verification this pass didn't actually
perform. "SUPPORTED" for Android/IndexedDB, for example, means "same API,
documented as Capacitor-compatible by Capacitor's own platform support
matrix" — not "we ran it on a device and watched it work," because no
Android SDK/emulator was available in this sandbox (see
`CURRENT_ARCHITECTURE_AUDIT.md`'s toolchain section).
