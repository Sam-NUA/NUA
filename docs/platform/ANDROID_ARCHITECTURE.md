# Android architecture

## What exists

- Native project: `frontend/android/` — generated via `npx cap add android`
  against `frontend/capacitor.config.json` (`appId: com.nua.pos`). Real
  Gradle project, real `applicationId "com.nua.pos"`, Gradle wrapper
  present and runnable.
- 8 Capacitor plugins wired: `@capacitor/app`, `clipboard`, `device`,
  `dialog`, `filesystem`, `network`, `preferences`, `share` — each backing
  one of the services in `frontend/src/platform/capacitor/`.
- The shared React app (`frontend/src`) is unchanged in its page/component
  structure — no Android-specific business logic exists anywhere; every
  Android-specific thing is confined to `platform/capacitor/*` and the one
  `isNative()` check in `hooks/useDeviceRegistration.js`.

## Build configuration

The production web build sets `REACT_APP_BACKEND_URL=` empty (same-origin
via Vercel's rewrite). The Android build **must** set it to the real
absolute origin instead — there is no "same origin" from inside a
Capacitor WebView:

```bash
PUBLIC_URL=/ REACT_APP_BACKEND_URL=https://app.nuapos.com.au npx craco build
npx cap sync android
```

This was done this pass; the committed `android/` project reflects assets
synced from that build. Re-run both commands (build, then sync) before any
future Android build — `android/app/src/main/assets/public` is
gitignored by Capacitor's own generated `.gitignore` and must be
regenerated, not hand-edited.

## Device/terminal model

Covered in full in `DEVICE_IDENTITY_MODEL.md`. Summary: on first
authenticated session, the app registers itself with real OS-reported info
(`@capacitor/device`'s `Device.getInfo()`), persists the returned device
id via `@capacitor/preferences`, and sends it as `X-Device-Id` on every
future login — a revoked device is rejected at login and has its
already-issued token rejected on its very next API call either way.

## Secure local authentication

`platform/capacitor/SecureStorageService.js` — `@capacitor/preferences`
for the access token. **Corrected claim**: an earlier pass of this doc
said this was "EncryptedSharedPreferences-backed on Android" — checked
against the plugin's own native source during the iOS pass and found
false. It's plain `context.getSharedPreferences(group, MODE_PRIVATE)`,
not encrypted, not Keystore-backed — no meaningfully different
theft-resistance from `localStorage`. Also mirrored to `localStorage` for
backward compatibility with ~20 not-yet-migrated pages (see
`MOBILE_DESKTOP_BACKLOG.md` and `SECURITY_MODEL.md` for the full
correction).

## Priority workflows — status against the directive's own list

| # | Workflow | Status |
|---|---|---|
| 1 | Login | Code path unchanged + device-id header added; not run on-device |
| 2 | Staff PIN login | Same — `X-Device-Id` wired via `staffMgmtAPI.pinLogin`; not run on-device |
| 3 | Pre-shift screen | Unchanged, not platform-specific; not run on-device |
| 4-20 | Floor plan → EOD reporting | Unchanged shared React code; no Android-specific blocker identified in the Phase 0 browser-API audit beyond the general `window.confirm`/print/download items tracked in the backlog; none independently run on-device |

"Not run on-device" is stated for every row because this sandbox has no
Android SDK/emulator (see `CURRENT_ARCHITECTURE_AUDIT.md`). This document
does not claim otherwise for any of them.

## Critical acceptance milestone — honest status

> Android tablet → take order → lose internet → continue operating →
> restart app → order survives → internet returns → synchronise →
> exactly one order appears in NUA → correct businessId → no duplicated
> payment/order/KDS event.

- The **code path** this depends on (`lib/offlineQueue.js`,
  `hooks/useOfflineQueue.js`, `clientOpId` dedup on both ends) already
  exists, is wired into the real checkout flow, and is unchanged by this
  pass — see `OFFLINE_SYNC_ARCHITECTURE.md`.
- The **backend half** of exactly-once delivery (tenant-scoped
  `clientOpId` dedup, atomic points/ledger/sale transaction) was
  independently audited and fixed in this session's earlier launch-audit
  work (PR #18/#19), re-confirmed passing in this pass's full test run.
- **What this pass did NOT do**: actually run this flow on an Android
  emulator or device. There is no code-level reason to expect a
  difference from the web behavior (same IndexedDB API, same fetch/axios
  calls, same clientOpId contract) — but that is a reasoned expectation,
  not a verified result. The milestone is **not** claimed complete; it is
  claimed **ready to attempt** the moment a toolchain with Android
  SDK/emulator access is available.

## Classification

**FOUNDATION.** Per the directive's own definitions: the native project
builds (as far as this sandbox's network policy allows — Gradle
dependency resolution reaches exactly the expected Google-Maven-repo
block, not a code defect), the shared app is unmodified in structure,
device identity exists and is tested, offline-queue infrastructure exists
and is unmodified/extended, platform abstraction exists for the
highest-value gaps. Not ALPHA: no on-device run has happened at all.
