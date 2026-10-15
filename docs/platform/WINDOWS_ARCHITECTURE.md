# Windows touchscreen and desktop

> **15 October terminal follow-up:** [TERMINAL_DURABILITY_REVIEW_2026-10-15.md](TERMINAL_DURABILITY_REVIEW_2026-10-15.md) supersedes earlier first-session, device-switching and Windows durability status below. Native sessions now bind before protected operation; Windows checkout uses the shared queue with OS-encrypted host persistence. Native cold-start offline authorisation remains disabled. Refer to the dated report for actual CI results and remaining release limits.

Started independently by Codex (ChatGPT) on `feat/windows-foundation`
(PR #21) with its own Phase 0 audit and a real, carefully-sandboxed
Electron host and offline-queue primitive; taken over and integrated
into the shared `frontend/src/platform/` abstraction layer in a later
pass of this same session, on explicit instruction. This document covers
the whole thing, crediting each part — see `COLLABORATION.md` for the
full handoff history.

## What exists

- Native host: `apps/windows/` — a standalone Electron 44.7.0 app with
  its own `package.json`/lockfile (isolated from the frontend's
  dependencies and from the older, stalled `frontend/electron/` scaffold,
  which is not used to release this). `npm run dist` (electron-builder)
  produces an unsigned Windows NSIS installer.
- A reusable, identity-scoped offline primitive: `packages/platform-core/`
  — not Windows-specific by name, but currently only consumed by
  `apps/windows`.
- Shared platform abstraction: `frontend/src/platform/electron/` — 7
  adapter files, added in the integration pass (none existed when the
  Windows host itself was first built).
- CI: `.github/workflows/windows-foundation.yml` runs on a real
  `windows-latest` GitHub Actions runner — installs both `frontend` and
  `apps/windows` dependencies, runs the Node unit tests, builds the
  shared React bundle, prepares the Electron renderer, runs
  `scripts/smoke.cjs` (launches the **real packaged app** via
  Playwright's Electron driver and checks bridge shape, sandbox flags,
  navigation/popup denial, and a live `safeStorage` encrypt/decrypt
  round-trip), then builds the unsigned installer and uploads it as an
  artifact. This is the one platform in this whole multiplatform effort
  with an automated run of the actual packaged app — Android has no
  emulator in this sandbox, iOS has no macOS runner; Windows has a real
  CI runner for its own OS, and this sandbox's own run of the same
  commands confirms that's genuinely the gate (see "What this sandbox
  itself could and couldn't verify" below).

## Native bridge (`window.nuaDesktop`)

`apps/windows/src/preload.cjs` exposes an explicit, frozen set of
methods — never `send`/`invoke`/Node/arbitrary URLs:

```text
getInfo()                    version, bridgeVersion, platform, inputMode,
                              hostname, secureAuthIntegrated,
                              offlineSyncIntegrated
setFullscreen(bool)
listPrinters()
printReceipt(receipt)         structured, escaped (receipt.cjs)
printHtml(html)                raw document, javascript:false preview window
saveFile(filename, bytes)      native Save dialog + direct write
getToken() / setToken(v) / clearToken()     OS-encrypted
getDeviceId() / setDeviceId(v)              OS-encrypted
```

The last 4 pairs (`print*`, `saveFile`, `*Token*`, `*DeviceId*`) were
added in the integration pass; `getInfo`/`setFullscreen`/`listPrinters`/
`printReceipt` are Codex's original foundation. Every one of them is
checked against the calling window/frame before running
(`assertSender` in `policy.cjs`) — a compromised or spoofed renderer
frame cannot invoke a native command, let alone target another window.

## Isolation and policy

- Renderer: `sandbox: true`, `contextIsolation: true`,
  `nodeIntegration: false`, `webSecurity: true`.
- Origin: bundled assets served over a custom `nua://app` scheme, not
  `file://` — `assetPath()` rejects path traversal, null bytes, and
  backslash tricks; the asset handler falls back to `index.html` only for
  extensionless paths (SPA routing), never for a request that actually
  named a file.
- CSP: `default-src 'none'; script-src 'self'` — no remote or inline
  script execution, enforced on every served response, keyed to the
  configured API origin so `connect-src`/`wss:` only ever point at one
  explicit HTTPS host.
- Navigation: every `will-navigate`/`will-redirect`/`will-attach-webview`
  outside `nua://app` is denied; **every** `window.open` call is denied
  outright, not just cross-origin ones (this is why the web
  `PrintService`/popup pattern cannot be reused here — see below).
- Permissions: `setPermissionCheckHandler(() => false)` and
  `setPermissionRequestHandler((...)=>callback(false))` deny everything
  by default — camera/mic/notifications/geolocation have no path to a
  grant inside this host today.
- Downloads: `will-download` is unconditionally prevented — the web
  `<a download>` pattern silently does nothing here, with no error
  surfaced; this is why `FileService.downloadFile` needed a real native
  replacement (`nua:save-file`), not just an adapter for symmetry's sake.
- Session: `session.fromPartition('nua-windows-foundation')` — no
  `persist:` prefix, so Chromium's own storage (cookies, its own
  `localStorage`, cache) is in-memory and discarded every restart by
  design. Anything that needs to survive a restart (the auth token, the
  device id) is explicitly routed around this session into the encrypted
  store below, not left to Chromium.

## Secure storage — genuinely hardened, not just relocated

`EncryptedStore` (`apps/windows/src/encrypted-store.cjs`) writes
temp-file-then-atomic-rename, encrypting via `windowsCrypto`
(`windows-crypto.cjs`), which wraps Electron's `safeStorage` — real
Windows DPAPI, tied to the logged-in OS user. It fails closed (throws)
if OS encryption is unavailable or the platform isn't `win32` — there is
no plaintext fallback path, by design, verified by
`apps/windows/test/security.test.cjs`'s "Windows crypto never falls back
to plaintext" test and `store.test.cjs`'s restart/corruption/encryption-
failure tests.

`platform/electron/SecureStorageService.js` and `DeviceIdentityService.js`
route the shared `nua_token`/device-id contract through `nua:token-*`/
`nua:device-id-*`, which this store backs. **This is the one platform in
this effort where the claim "OS-encrypted at rest" is actually true** —
Android's `@capacitor/preferences` and iOS's equivalent were both
verified (see `SECURITY_MODEL.md`) to be plain, unencrypted storage
despite earlier documentation claiming otherwise. Windows doesn't share
that gap.

## Printer and file — real native paths, not web fallbacks

Two of the directive's "platform abstraction" services needed more than
a thin wrapper here, because the web implementation would **silently
fail** inside this specific host, not just look different:

- **Print**: the web `PrintService.printHtml`'s `window.open` is denied
  unconditionally (see "Isolation" above). `platform/electron/
  PrintService.js` instead calls `nua:print-receipt` (structured fields,
  escaped server-side in `receipt.cjs` — closes the Windows audit's W07
  finding for `services/printer.js`'s receipt, which has fully structured
  data available at the call site) or `nua:print-html` (raw HTML — used
  by `services/docket.js`'s kitchen docket, which has no fixed schema:
  courses, stations, allergens, seats). Both print via a disposable,
  `javascript: false` preview `BrowserWindow`, so even a malformed or
  hostile document can distort the print preview but never execute
  anything — the control that makes the unescaped `printHtml` path safe
  for the docket case.
- **File export**: the web `<a download>` pattern is silently blocked
  (`will-download` prevented). `platform/electron/FileService.js` calls
  `nua:save-file`, which shows a real native Save dialog and writes the
  bytes directly — the ~12 existing export call sites (payroll, backups,
  audit logs, BAS worksheet) get a real file instead of nothing.

Dialog, Clipboard, and Network re-export the web implementations
unchanged — standard DOM APIs (`window.confirm`/`navigator.clipboard`/
`navigator.onLine`) that this host's sandboxing doesn't gate, so there's
nothing Electron-specific to build for them.

## Device identity

`platform/electron/DeviceIdentityService.js` registers through the same
shared backend endpoint every platform uses; `ALLOWED_PLATFORMS` already
listed `"windows"` before this integration pass, but nothing had ever
exercised that value — `backend/tests/inprocess/
test_device_identity.py::test_windows_platform_device_registers_and_
enforces_revocation_identically_to_android` now does, proving the full
register→login→revoke cycle. There's no OS-device-info API exposed by
this host (unlike `@capacitor/device` on Android/iOS), so `deviceName`
falls back to the real machine hostname (`os.hostname()`, returned by
`nua:info`) rather than anything fabricated.

## Touch and desktop input

`apps/windows/src/desktop.js`/`.css` add a small, always-visible host bar
(version, input mode, full-screen toggle, printer test) outside the
shared React root. `npm start -- --touch` sets `data-nua-input="touch"`,
which raises interactive-element minimum size to 44px and sets
`touch-action: manipulation` — a real, if minimal, concession to a
touchscreen till versus a desktop with a mouse. This is **not** Windows
kiosk mode / Assigned Access, and virtual-keyboard behavior, display
scaling (100–200%), and actual touch ergonomics have no physical-hardware
verification — only the CI smoke test's mode-flag assertion.

## Offline queue: a real, tested primitive — not wired into the app

Covered in full in `OFFLINE_SYNC_ARCHITECTURE.md`'s Windows section.
Summary: `packages/platform-core/queue.cjs`'s `CashOrderQueue` is a
separate, identity-scoped, exactly-once-tested cash-order queue, backed
by the same `EncryptedStore`. It is not what `POSTerminal.jsx` actually
calls — the shared `lib/offlineQueue.js` (IndexedDB) still runs
unmodified on every platform including Windows. Wiring the two together
needs a coordinated decision (replace vs. coexist) and a legacy-data
quarantine plan, deliberately not rushed this pass.

## What this sandbox itself could and couldn't verify

This pass ran, in this Linux sandbox:

- `node --test` across `apps/windows/test/*` and `packages/platform-
  core/test/*` — **19 passed, 0 failed** (pure logic: policy validation,
  receipt escaping, Windows-crypto fail-closed behavior, the encrypted
  store's atomicity/corruption handling, and the cash queue's identity-
  scoping/exactly-once/conflict-retention guarantees, all against real
  temporary files and real AES-GCM fixtures, not mocks of the crypto
  itself).
- The real production frontend build, with the new `platform/electron/`
  adapters included.
- Attempting `apps/windows/scripts/smoke.cjs` directly: confirmed it
  cannot run here, **by design** — `main.cjs`'s `start()` throws
  immediately on anything but `process.platform === 'win32'`, which this
  sandbox is not. This is a deliberate guard (never let a non-Windows
  build of this foundation run as if it were real), not an oversight to
  work around.

This sandbox could **not** verify, and does not claim to have verified:
an actual `windows-latest` CI run of this exact integration pass's
changes (expected to run automatically once pushed — see the PR), the
unsigned NSIS installer actually installing and launching on a real
Windows machine, or any physical hardware (printer via the Windows
spooler, keyboard-wedge scanner, touchscreen, cash drawer).

## Classification

**FOUNDATION**, ahead of Android/iOS on one specific axis (a real
automated run of the packaged app on its own target OS, via CI) and
behind them on another (the live checkout flow doesn't call this
platform's own offline primitive yet). Not ALPHA: no physical hardware,
no signed installer, no terminal-payment integration, no device-pairing
credential beyond the identity registry itself.
