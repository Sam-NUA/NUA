# Windows architecture

Per `docs/platform/COLLABORATION.md`, Windows implementation is ChatGPT's
lane this pass — Claude did not touch `frontend/electron/`,
`frontend/electron-package.json`, or `build-windows.bat`.

What Claude's work leaves in place for that implementation to build on:

- `platform/index.js`'s `detectPlatform()` already returns `'electron'`
  when `window.electronAPI?.isElectron` is set (the existing
  `electron/preload.js` already exposes that flag) — an Electron-specific
  service implementation just needs to be added under
  `platform/electron/*` and wired into `platform/index.js`'s
  `isCapacitor` branch logic (currently Electron falls through to the
  `web/` adapters, which is correct behavior for an unimplemented
  Electron-specific service, not a bug).
- The backend device-identity contract (`DEVICE_IDENTITY_MODEL.md`)
  already accepts `platform: "windows"` — no backend change needed to
  register a Windows device once an Electron-side
  `DeviceIdentityService.register()` exists.
- `ADR-001`'s open decision (finish wiring the existing
  PyInstaller-backend + bundled-MongoDB local packaging model, or switch
  to a thin client reusing `lib/offlineQueue.js` against the hosted API)
  is unresolved on purpose — that choice belongs to whoever implements it,
  informed by the tradeoff written up there, not pre-decided by this pass.

See `CURRENT_ARCHITECTURE_AUDIT.md`'s "already-existing multiplatform
groundwork" section for the concrete gaps found in the current Electron
scaffold (unregistered IPC handlers, no actual backend/Mongo process
spawning despite the packaging config implying one) — those are real,
verified-by-reading-the-code findings, not guesses, and are exactly what
this Windows implementation pass needs to resolve.
