# ADR-001: Multiplatform architecture for NUA POS

Status: Accepted
Date: 2026-10-12
Supersedes: nothing (first ADR for this effort)

## Context

See `CURRENT_ARCHITECTURE_AUDIT.md` for the full factual inventory. Summary
relevant to this decision:

- The web app is React 19 + CRA/craco, with no React Native/Vite dependency
  anywhere — a straight rewrite is not justified.
- Browser-API usage is heavy but almost entirely abstractable: no
  WebUSB/Bluetooth/Serial code exists (printer I/O is already
  server-side/network, not browser-API-based), no payment SDK runs
  client-side, and a real IndexedDB-backed offline queue
  (`frontend/src/lib/offlineQueue.js`) already exists and is well-suited to
  extend rather than replace.
- `@capacitor/core`/`cli` v6 and a `capacitor.config.json` already exist for
  Android/iOS; an Electron shell and NSIS packaging config already exist for
  Windows. Both stalled at configuration — no native Android/iOS project was
  ever generated, and the Electron shell never wired up the backend/Mongo
  bundling its own packaging config implies.
- Backend tenant isolation (`tenant_scope_filter`'s fail-closed predicate)
  and RBAC (`deps.require_permission`, server-side) are already built on the
  assumption that the client is never trusted — this matches the
  directive's non-negotiable security rules without any backend change
  required for this phase.

## Decision

### Mobile (Android first, iOS same codebase later): Capacitor

Keep the existing choice. Reasoning:

- The shared React bundle runs inside Capacitor's WebView essentially
  unchanged for the ~80% of the app that's pure React/Tailwind/Radix —
  confirmed by the dependency audit (no Node-only or Electron-only code
  leaks into `src/`).
- The real work is the ~20%: `window.confirm`/`prompt`, print, file
  download, camera/mic access, and the service-worker/manifest layer need a
  platform-abstraction shim either way, under React Native or Capacitor.
  React Native would also require that work *plus* a parallel rewrite of
  every page component — Capacitor requires only the shim.
- Capacitor already has first-party plugins for every gap this audit found:
  Camera, Filesystem, Share, Clipboard, Network, Preferences (secure-ish
  key/value), Haptics, Barcode-scanning (community), Print (community). No
  exotic native module is needed for the Android-first scope.
- Rejected: React Native (would require rewriting all ~120+ page
  components against a different component model — not justified when
  the abstraction gap is this narrow), native Kotlin/Swift wrappers (loses
  all shared-code benefit, two codebases immediately), PWA-only (rejected
  per the audit: no WebUSB/Bluetooth/Serial today, but Phase 7's printer
  Bluetooth/USB adapters and Phase 4's device-identity/revocation model need
  real native capability a installable PWA can't reliably provide — notably
  background execution and secure storage guarantees).

### Windows: Electron (not Tauri) — confirmed independently twice, now implemented

The directive's preferred default is Tauri-unless-blocked. This ADR's
original reasoning (below, preserved) found a blocker specific to the
*stalled* `frontend/electron/` scaffold that existed before any Windows
work in this effort. Codex's separate, independent Windows audit
(`feat/windows-foundation`, now folded into `CURRENT_ARCHITECTURE_AUDIT.md`)
reached the same Electron-over-Tauri conclusion for an overlapping but
distinct reason — printer/driver/SDK access and an existing JavaScript
maintenance path — and then actually built it, in a clean new `apps/
windows/` package rather than reviving the stalled scaffold (whose entry
path never loaded its own preload at all — a real, separately-documented
blocker, see `CURRENT_ARCHITECTURE_AUDIT.md`'s W01).

Original reasoning for keeping Electron rather than migrating to Tauri:
- The existing packaging model bundles a full local backend (PyInstaller)
  and local MongoDB binary as installer resources, aimed at a fully
  offline-capable desktop POS. That model needs real OS process lifecycle
  management (spawn, health-check, graceful shutdown, restart-on-crash) for
  two child processes — directly supported by Electron's Node main process
  (`child_process`), not by Tauri's Rust/WebView2 model without writing
  that lifecycle management in Rust from scratch.
- Migrating to Tauri now would mean discarding already-built,
  directionally-correct work (the NSIS config, the PyInstaller backend
  build) to rebuild the same process-lifecycle logic in a language with no
  existing code in this repo, for a benefit (smaller binary, lower memory)
  that matters less for a POS terminal — a dedicated till machine, not a
  battery-constrained laptop — than reusing an 80%-solved problem does.
- Rejected: Tauri (blocker above), plain PWA (same gaps as mobile, plus no
  path to the local-backend-bundle model at all if that's kept), native
  Windows wrapper (two codebases).

**What was actually built resolves the open caveat this ADR used to
carry here**: `apps/windows/` bundles no backend or MongoDB at all — it's
a thin client against a configured HTTPS API origin, same shape as
Android/iOS. The local-backend-bundle model from the original stalled
scaffold is not what shipped; see `WINDOWS_ARCHITECTURE.md` for the full,
current account (native bridge, sandboxing, OS-encrypted storage, the
real `windows-latest` CI runner) and `MOBILE_DESKTOP_BACKLOG.md` for what
that choice still leaves open (the local-bundle option is simply not
pursued, not proven worse).

### Offline database: extend the existing IndexedDB offline queue, not a new one

- `frontend/src/lib/offlineQueue.js` already exists, is purpose-built for
  "AU regional connectivity drop-outs" per its own comments, already has
  object stores for `pending_transactions`, `pending_course_actions`, and
  `cached_reads`, and already flushes on `navigator.onLine`. IndexedDB
  works unchanged inside a Capacitor WebView.
- Do not introduce Capacitor SQLite or a second storage layer for Android
  unless a concrete limitation of IndexedDB-in-Capacitor is actually hit
  (e.g. a storage-quota wall under heavy offline use) — that's a
  Phase-3-implementation decision to make with evidence, not up front.
- Windows/Electron ended up with neither of this ADR's two predicted
  options: not the same IndexedDB queue as web, and not a bundled-Mongo
  local store. `packages/platform-core/queue.cjs`'s `CashOrderQueue` is a
  third thing — a main-process, OS-encrypted, identity-scoped primitive
  specifically for cash orders, independent of IndexedDB entirely. It's
  real and tested but not wired into the live checkout flow yet; see
  `OFFLINE_SYNC_ARCHITECTURE.md`'s Windows section for why that's a
  deliberate, not-yet-closed gap rather than an oversight.

### Secure storage / device identity

- This ADR originally recommended a dedicated Keystore/Keychain-backed
  secure-storage plugin for the JWT specifically, over plain
  `localStorage`/`Preferences`, since the access token is the one thing in
  this app's `localStorage` usage (per the browser-API audit) that's a
  real theft target, not just a UX convenience value. **What was actually
  built deviates from that recommendation**: the implementation pass used
  `@capacitor/preferences` directly and, at the time, incorrectly
  documented it as encryption-backed. Verified against the plugin's own
  native source during the iOS pass: it's plain `SharedPreferences`
  (Android) / `UserDefaults` (iOS), neither encrypted, neither
  Keystore/Keychain-backed. See `SECURITY_MODEL.md`'s corrected version.
  This ADR's original recommendation stands as the still-correct target;
  `MOBILE_DESKTOP_BACKLOG.md` tracks picking and wiring in a real
  secure-storage plugin as genuinely not done, not as optional polish.
- Device identity (business → location → device → terminal → staff
  session, per the directive's Phase 4) is a **shared backend model**, not
  platform-specific — defined in this ADR and implemented against by
  whichever platform registers a device. Schema:

  ```text
  devices collection (backend/models/device.py, new):
    id, businessId, locationId (optional), platform (android|ios|windows|web),
    deviceName, deviceModel, osVersion, appVersion,
    terminalId (optional, for POS registers specifically),
    capabilities: [str],       # e.g. ["printer.network", "camera.scan"]
    status: active|revoked,
    registeredBy (staff id), createdAt, lastSeenAt,
    revokedAt, revokedBy (optional)
  ```

  Endpoints (owner/manager-gated, tenant-scoped like everything else):
  `POST /api/devices/register`, `GET /api/devices`, `POST
  /api/devices/{id}/revoke`, `POST /api/devices/{id}/heartbeat` (updates
  `lastSeenAt`, cheap enough to call on app foreground). A revoked device's
  token is **not** retroactively invalidated by this alone — revocation
  must be checked server-side on every authenticated request from here on
  (a new, lightweight check alongside the existing JWT decode in
  `RequireAuthMiddleware`/`ActorContextMiddleware`), or a stolen device with
  a live access token keeps working for up to 8 hours after revocation.
  This is called out explicitly because it's easy to build the registry and
  forget to wire enforcement — enforcement is part of "device identity
  exists," not a follow-up.

## Platform abstraction layer

Per the directive's Phase 2, business logic depends on interfaces, not
operating systems. Given the existing repo is a single CRA app (not a
monorepo with a build system that understands workspace packages), the
`packages/` structure from the directive is adapted rather than imposed
wholesale — introducing a real monorepo tool (Nx/Turborepo/yarn workspaces)
is out of scope for this pass and would itself be a disruptive,
unrequested restructuring. Instead:

```text
frontend/src/platform/
  index.js                 # detectPlatform() → 'web' | 'android' | 'ios' | 'electron'
  types.js                 # JSDoc typedefs for each service interface (see below)
  web/                      # default/fallback implementations (today's behavior)
    DialogService.js        # confirm/prompt/alert → replaces window.confirm/prompt
    PrintService.js         # wraps today's window.open+document.write+print
    FileService.js          # wraps today's <a download> blob pattern
    ClipboardService.js
    CameraService.js        # wraps getUserMedia
    NetworkService.js       # wraps navigator.onLine + connection
  capacitor/                # Android (and later iOS) implementations
    DialogService.js        # Capacitor has no native dialog plugin need — can reuse a React modal; documented per-service below
    PrintService.js
    FileService.js
    ClipboardService.js
    CameraService.js
    NetworkService.js
    DeviceIdentityService.js
    SecureStorageService.js
  electron/                 # Windows (apps/windows/src/main.cjs's nuaDesktop
                             # bridge) implementations — Dialog/Clipboard/
                             # Network re-export the web versions (a real
                             # Chromium renderer needs no IPC for those);
                             # Print/SecureStorage/DeviceIdentity/File are
                             # real native implementations, not fallbacks —
                             # see HARDWARE_ABSTRACTION.md and SECURITY_MODEL.md
                             # for why the web fallback would silently fail
                             # for Print and File inside this specific host.
```

This sits inside the existing `frontend/src` tree (no new top-level
`packages/` or `apps/` directories), because every consumer of these
services is a page/component already living under `frontend/src` — moving
them into a separate workspace package buys nothing without a real
monorepo build tool, and the directive itself says to adapt the structure
"rather than reorganising everything unnecessarily."

Each service is a plain object with the same method signatures across
`web/` and `capacitor/` implementations; `platform/index.js` exports the
correct one for the running platform. Call sites (e.g. `GiftCards.jsx`'s
`window.print()`) are updated to call `PrintService.print(html)` instead —
the biggest line-count change in this phase is these call-site swaps, not
the service implementations themselves, per the audit's ~30
`window.confirm`/`prompt` sites and ~12 file-download sites.

## Consequences

- Android scaffolding (Phase 6) can proceed immediately: generate the
  native project, wire the real API origin, implement the Android-side
  service adapters, swap the highest-value call sites (print, file
  download, confirm/prompt central hook), prove the offline→restart→sync
  flow using the existing `offlineQueue.js`.
- The Windows local-backend-bundle vs. thin-client decision landed on
  thin-client by construction (`apps/windows` bundles no backend/Mongo) —
  this ADR's original tradeoff writeup is kept so that outcome reads as
  informed, not accidental, even though it wasn't a separate explicit
  sign-off step at the time.
- Device-identity revocation enforcement is a small, easy-to-forget
  addition to existing middleware — tracked explicitly here so it isn't
  dropped between "the registry exists" and "revocation actually works."
- No monorepo tooling migration this pass — revisit if/when `NUA Business`
  (the separate owner/manager app mentioned in the directive) is actually
  started, since that's the point three real app shells would share one
  `platform/` layer and a workspace tool starts paying for itself.
