# NUA POS — Current Architecture Audit (Phase 0)

Date: 2026-10-12
Branch: `feat/multiplatform-foundation`
Baseline: `main` @ `9963583` (see "Baseline verification" below — this differs
from the directive's assumption)

This is a factual inventory of what exists today, gathered by direct
repository inspection (not from memory or the directive's assumptions).
Opinions and recommendations are deferred to `ADR-001-multiplatform-architecture.md`.

---

## Baseline verification

The directive states the production/deployed branch "has previously been"
`codex/owner-access`. That is now stale:

- `codex/owner-access`'s last own deployment (via Vercel's deployment
  history, project `nua-pos-staging`, `prj_QhddJTj9toxACgdy613aXKvAcJQ0`) was
  commit `b6be4b9` ("Make owner access and password recovery clear and
  durable").
- Every production deployment since (`b547ec7` / PR #14 onward, including
  `36bebec` / PR #16 and the current one) has tracked **`main`**, confirmed
  directly from Vercel's deployment metadata (`githubCommitRef: "main"`).
- The current live production deployment (`dpl_EVSivgancxuwFVebQHsDYgjyZpoF`,
  state `READY`) is `main` @ `9963583` — the merge of PR #20 (the launch-audit
  stack: PR #17 + #18 + #19) completed earlier in this session. It serves
  `app.nuapos.com.au`.
- `codex/owner-access` is therefore an ancestor of `main`, not a sibling or
  a more-current branch. `main` is authoritative.

**`feat/multiplatform-foundation` was branched from `main` @ `9963583`**, not
from `codex/owner-access`, per the directive's own instruction to verify
rather than assume.

---

## Already-existing multiplatform groundwork

Before auditing from scratch, it's worth stating plainly: **this is not a
greenfield start.** Someone already began exactly the work this directive
describes, and left it partially done:

| Artifact | State |
|---|---|
| `frontend/capacitor.config.json` | Present, configured (`appId: com.nua.pos`, `webDir: build`) |
| `@capacitor/core`, `@capacitor/cli` v6 | Installed in `frontend/package.json` |
| `frontend/android/` (native project) | **Does not exist.** `npx cap add android` has never been run/committed. |
| `frontend/ios/` | Does not exist. No `@capacitor/ios` dependency either. |
| `frontend/electron/main.js`, `preload.js` | Present, minimal (48 + 11 lines) |
| `frontend/electron-package.json` (electron-builder config) | Present — NSIS installer + portable target, bundles `../backend/dist` and `../mongodb` as `extraResources` |
| `frontend/build-android.sh`, `build-windows.bat`, root `build_windows_exe.bat`, `backend/build_backend.py` (PyInstaller) | Present |
| Root `WINDOWS_BUILD_GUIDE.md`, `BUILD_CHECKLIST.md`, `QUICK_BUILD_GUIDE.md`, `WINDOWS_EXE_GUIDE.md`, `WINDOWS_SETUP_GUIDE.md`, `DIRECT_DOWNLOAD_GUIDE.md`, `WHERE_IS_EXE_FILE.md`, `PACKAGE_README.md` | Present, reference an `/app/...` path convention (this repo's earlier home under the Emergent build platform) rather than this checkout's actual paths — likely stale instructions, not verified working from this repo layout |

**Concrete gaps found in the existing scaffold (not assumptions — read the code):**

1. **`electron/main.js` never spawns the bundled backend or MongoDB.** It
   just loads a URL (`ELECTRON_START_URL` in dev, or the built
   `index.html` in prod). The elaborate NSIS packaging config
   (`extraResources: ../backend/dist, ../mongodb`) bundles a PyInstaller'd
   backend executable and a MongoDB binary into the installer, but nothing
   in the app's lifecycle (`app.on('ready')`, etc.) ever launches them as
   child processes. As shipped, the Electron shell is a thin wrapper
   around whatever `REACT_APP_BACKEND_URL` was baked in at build time — it
   is **not** currently a self-contained offline desktop app, despite the
   packaging config implying one.
2. **`preload.js` exposes two IPC methods** (`getBackendUrl`,
   `getAppVersion`) that **main.js never registers handlers for**
   (`ipcMain.handle('get-backend-url', ...)` / `'app-version'` do not
   exist in `main.js`). Calling either from the renderer today would hang
   or reject.
3. **`build-android.sh` / `build-windows.bat` both hardcode
   `REACT_APP_BACKEND_URL="https://your-production-api.com"`** — an
   unfilled placeholder, never pointed at the real API. Neither script has
   been run to produce a working artifact as far as this repo shows (no
   `android/`, no committed `dist/`).
4. No native project (`android/`, `ios/`) has ever actually been generated
   — `capacitor.config.json` exists but `npx cap add android` has never
   been run/committed.

**Conclusion: the prior attempt stalled at configuration, before any of it
was wired together or tested.** This audit treats it as a real starting
point to build on (the dependency choices — Capacitor for mobile, Electron
for Windows — are sound and match the directive's own preferred direction),
not as working code to preserve as-is.

---

## Frontend architecture

- **React 19.0.0**, `createRoot` API (`frontend/src/index.js`).
- **Build tooling**: Create React App (`react-scripts` 5.0.1) wrapped by
  **craco** (`frontend/craco.config.js` — webpack `@` alias, optional
  hot-reload disabling, optional babel/webpack plugins via env flags). Not
  Vite.
- **Router**: `react-router-dom` 7.5.1 (`BrowserRouter`/`Routes`/`Route`).
- **State management**: no Redux/Zustand/MobX — plain React Context
  (`AuthContext`, `BusinessContext`, `LicenseContext`, `POSContext`,
  `ThemeContext`) plus local `useState`/`useEffect`. Forms via
  `react-hook-form` + `zod`.
- **Styling**: Tailwind CSS + CSS variables, `darkMode: ["class"]`.
- **Component library**: shadcn/ui (`components.json`, style "new-york") on
  Radix UI primitives (~25 `@radix-ui/react-*` packages), `lucide-react`
  icons, `cmdk`, `vaul`, `sonner`.
- **PWA / service worker**: `frontend/public/sw.js` + `service-worker.js`
  (cache name `nua-pos-v1`, network-first with cache fallback, explicitly
  skips `/api/`). Three manifest variants (`manifest.json`,
  `manifest.owner.json`, `manifest.staff.json`) swapped at runtime by
  `frontend/src/lib/appShell.js` based on hostname/query param — i.e. the
  same build already serves two different "apps" (owner vs staff shell)
  from one bundle today. `index.html` registers the service worker and
  swaps the manifest `<link>` before first paint.
- **API client**: one axios instance in `frontend/src/services/api.js`
  (`baseURL: ${REACT_APP_BACKEND_URL}/api`), request interceptor injects
  `Authorization: Bearer <nua_token>` from `localStorage`, response
  interceptor does silent refresh-on-401 (shared in-flight promise, retries
  once). **`AuthContext.jsx` uses a separate raw `axios` call**, not this
  shared instance, for login/checkAuth/logout/2FA — two HTTP client
  configurations to keep in sync for any platform-specific base-URL change.
  ~50 grouped API objects mirror every backend route module.
- **Realtime**: primarily **SSE via `EventSource`**, not WebSocket —
  `frontend/src/lib/ticketStream.js` (kitchen coursing tickets), plus SSE
  for online-order tracking and waitlist position. Two call sites use a
  raw `WebSocket` directly for live bill-splitting
  (`hooks/useSplitWebSocket.js`, `pages/SplitBillStaff.jsx`), building the
  `ws://`/`wss://` URL from `window.location` — will need to point at the
  configured backend origin instead once the app isn't served from the
  same host as the API (true for every native target).
- **Entry/routing**: `App.js` nests `ThemeProvider > POSProvider >
  AuthProvider > BusinessProvider > BrowserRouter`. ~120+ pages are
  `React.lazy`-loaded under one `Suspense` boundary. A single
  `ProtectedRoutes` component is the auth/role gate for everything under
  `/*` (public routes — booking portal, table QR ordering, split-bill
  guest links, order tracking, waitlist tracking, rewards, password
  reset/owner-recovery — are listed explicitly before it). It reads
  `authError` (not just `user`/`loading`) to show a "couldn't verify
  session, try again" retry gate rather than forcing logout on a
  transient failure (see PR #20's merge note — this behavior was itself
  the subject of a conflict resolved earlier this session).

## Backend architecture

- **FastAPI**, single composition root `backend/server.py` (775 lines):
  imports and mounts **68 route modules** from `backend/routes/*.py` under
  one `/api`-prefixed router.
- **Middleware stack** (outermost to innermost, as added): observability
  (`services/observability.py`'s `ObservabilityMiddleware`, logs every
  request/exception) → `ActorContextMiddleware` → `LicenseEnforcementMiddleware`
  → `RateLimitMiddleware` (per-tenant+identity, with path/prefix overrides
  for anonymous-but-sensitive endpoints) → `RequireAuthMiddleware` (global
  default-deny on `/api/*` unless explicitly allowlisted — this is the
  layer this session's earlier audit work (PR #17-#19) repeatedly touched).
- **MongoDB**: Motor (`AsyncIOMotorClient`), fully async, singleton
  `client`/`db` in `backend/database.py`. Connection string from
  `MONGO_URL`/`MONGO_MONGODB_URI`/`MONGODB_URI`, `DB_NAME` for the database
  name, both via `backend/.env` (`python-dotenv`). Index management
  centralized in `services/db_indexes.py` plus per-feature
  `ensure_indexes()` calls from the app's startup event.
- **Auth**: JWT (HS256, `JWT_SECRET`). 8-hour access token (embeds `sub`,
  `email`, `role`, `businessId` — no DB round-trip needed for tenant
  context), 7-day refresh token. Hybrid delivery: bearer header, httpOnly
  cookie, **and** query-param (for `EventSource`, which can't set headers).
  bcrypt password hashing. Supports PIN login (manager-approved for
  off-roster staff), TOTP 2FA + trusted-device + recovery codes, owner
  recovery flow, password-change token invalidation.
- **RBAC**: four roles (`owner`/`manager`/`cashier`/`kitchen`),
  `effective_permissions()` resolution order: owner→`["*"]` always; else
  per-user `customPermissions`; else per-business DB override
  (`db.role_permissions`); else code defaults
  (`services/permission_catalog.py` → `ROLE_PERMISSIONS`).
  `deps.require_permission(perm_id)` enforces server-side;
  `AuthContext.hasPermission()` mirrors it client-side for UI visibility
  only — **the directive's rule that mobile/desktop clients are never
  trusted is already the existing model**: the frontend check is UX only,
  the backend dependency is the real gate.
- **Tenant/business model**: `middleware/actor_context.py` is the central
  helper. `tenant_scope_filter(business_id)` returns a real filter when a
  tenant is present, or a **deliberately impossible predicate**
  (`{"$expr": {"$eq": [1, 0]}}`) when it's missing — fail-closed by
  construction, not by convention. `tenant_owns_strict()` for exact-match
  ownership checks before mutating a specific doc. `ActorContextMiddleware`
  populates a `contextvars.ContextVar` per request so services without
  direct request access can still stamp writes correctly.
  `services/ownership_migration.py` exists specifically to repair
  historically mis-scoped/unowned records (`_ownershipQuarantined` flag).
- **Background jobs**: dual implementation keyed on `VERCEL` env var —
  real in-process `while True: sleep()` loops off Vercel
  (`nua_scheduler.py`, `coursing_scheduler.py`, `backup_scheduler.py`,
  `booking_sync.py`, `repo_sync_scheduler.py`), vs. `/api/cron/*` endpoints
  on Vercel (gated by `CRON_SECRET`, leased via `services/cron_jobs.py`'s
  `try_claim`/`finish` so overlapping invocations don't double-run — this
  session's earlier audit work added the running/succeeded/failed outcome
  tracking on top of the claim).
- **Payments**: Stripe (checkout + billing, two separate webhooks),
  Coinbase Commerce (crypto), Square (via a generic `services/connect/`
  connector framework also used for a CDR/open-banking bank-feed
  connector), plus a separate EFTPOS-terminal model
  (`services/eftpos_service.py`) for in-person card terminals — distinct
  from the online/hosted-checkout providers above.
- **Printing**: `services/escpos.py` — dependency-free ESC/POS byte
  generator, sends raw bytes over **TCP port 9100** directly to
  network-connected thermal printers (no USB/Bluetooth driver layer
  exists server-side either). `services/print_routing.py` routes
  tickets/items to the correct station (kitchen/bar/receipt).
- **KDS**: `backend/routes/kitchen.py` (646 lines) for order lifecycle +
  per-course fire/hold/serve/ready; a related but separate "coursing"
  subsystem (`coursing.py`, `coursing_scheduler.py`, `course_events.py`,
  `table_pacing.py`) drives pacing/auto-fire and feeds the SSE ticket
  stream.
- **Reservations**: `backend/routes/reservations.py` (1322 lines) is the
  core, plus `reservation_features.py`, `booking_analytics.py`,
  `bookings_inbox.py`. **Reservations/bookings span two deployable
  backends**: this FastAPI app, and a wholly separate FastAPI service at
  `/home/user/nua/bookings-api` (its own Vercel "service", synced via
  `services/booking_sync.py`) — a real architectural detail any
  offline-sync design needs to account for.
- **Loyalty**: three layered route modules (`loyalty.py`, `loyalty_v2.py`
  — includes a public phone-lookup guest portal, `loyalty_engine.py`),
  suggesting organic growth rather than a single designed system.
- **AI ("Ash"/"NUA")**: `services/nua_agent.py` and siblings, via
  `emergentintegrations`'s `LlmChat` wrapper
  (`.with_model("openai", "gpt-5.2")`), keyed by `EMERGENT_LLM_KEY`. One
  feature path (social-media content generation, per README) is
  documented as using "Claude Sonnet 4.6" directly rather than the generic
  wrapper — not independently verified in source this pass.

## Deployment / environment

- **`vercel.json`** defines a **three-service monorepo**: `web`
  (`frontend`, CRA), `pos` (`backend`, FastAPI, entrypoint `server:app`),
  `bookings` (`bookings-api`, FastAPI, entrypoint `vercel_app:app`), with
  path-based rewrites (`/api/*`→pos, `/bookings-api/*`→bookings, everything
  else→web) so **all three are served from one origin in production**
  (`app.nuapos.com.au`).
- The `web` service's build command sets `REACT_APP_BACKEND_URL=` **empty**
  — i.e. in production the frontend calls `/api/...` same-origin, relying
  entirely on the rewrite. **This is a real blocker for every native
  target**: Capacitor serves from a custom scheme
  (`capacitor://localhost` or similar), and Electron loads from `file://`
  — neither is "the same origin" as `app.nuapos.com.au`. Every native build
  must set `REACT_APP_BACKEND_URL` to the real absolute API origin at
  build time, and both HTTP client configurations (`services/api.js` and
  `AuthContext.jsx`'s separate axios usage) need to honor it consistently.
- `regions: ["syd1"]`, `crons` as described above, `git.deploymentEnabled`
  disables auto-deploy for specific in-flight branches (not a general
  mechanism — each branch must be named explicitly).
- No `.env`/`.env.example` committed; canonical env var list lives in root
  `README.md`. Confirmed present: `MONGO_URL`/`DB_NAME`, `JWT_SECRET`,
  `EMERGENT_LLM_KEY`, `STRIPE_API_KEY`/`STRIPE_WEBHOOK_SECRET`,
  `SENDGRID_API_KEY`, `TWILIO_ACCOUNT_SID`, `ABR_GUID`, `VERCEL`,
  `CRON_SECRET`, `COINBASE_COMMERCE_API_KEY`.

---

## Dependency compatibility matrix (frontend)

Full per-package table gathered; summarized here — see git history of this
file's authoring session for the exhaustive version if needed.

**Clean / no action needed**: React, React DOM, react-hook-form, zod,
date-fns, class-variance-authority, clsx, tailwind-merge, lucide-react,
most Radix primitives (portal/focus-trap quirks aside), `@capacitor/core`
and `@capacitor/cli` (correctly dev/runtime split already).

**Flagged — real action needed before/while porting**:

| Package | Issue |
|---|---|
| `axios` | Pinned to `1.20.0` in this repo (a PR #17-introduced deliberate upgrade per its PR description, not a typo) — no action needed, just noting it's intentional. |
| `cmdk` | Keyboard-shortcut command palette — meaningless on touch-only mobile, needs a conditional/alternate UI. |
| `react-resizable-panels` | Mouse-drag desktop pattern, low value on phone-sized screens — consider conditional rendering. |
| `react-router-dom` | History API routing — verify behavior under Capacitor's custom scheme explicitly; don't assume. |
| `electron` + `electron-builder` (devDependencies) | Correctly isolated from the web bundle today (zero `require('electron')` hits in `src/`) — keep that separation. `electron-builder`'s NSIS/code-signing toolchain is the single biggest Windows-packaging risk if anything changes shells later. |

**No existing mobile-portability code for these capabilities — not a
"replace X" problem, a "build new" one**: no WebUSB/WebBluetooth/WebSerial
anywhere (printer I/O is 100% network/TCP from the backend, which is
actually favorable — no browser-API peripheral code to migrate), no
Geolocation usage, no Notification API usage, no payment SDK embedded
client-side (Stripe/Square etc. are server-side only, confirmed).

---

## Browser-API usage inventory (frontend/src)

By category, with portability risk:

| Category | Found | Risk | Note |
|---|---|---|---|
| `window.confirm`/`window.prompt` | ~30 call sites across nearly every page | **High** | The app's entire destructive-action confirmation UX. Needs one central `useConfirm()`/`usePrompt()` dialog abstraction — the single biggest UI refactor for porting, done once and it fixes every call site. |
| `window.open` + `document.write` + `window.print()` | `services/docket.js`, `services/printer.js` (browser-print fallback), `pages/Dashboard.jsx`, `pages/Accounting.jsx`, `pages/StaffRoster.jsx`, `components/settings/SecurityPanel.jsx`, `pages/v25/GiftCards.jsx` | **High** | Real receipt/docket/report printing, not incidental. None of this works in a Capacitor WebView; different IPC on Electron/Tauri. Network ESC/POS (`services/printer.js`) is already the *primary* path with browser-print as *fallback only* — keep that priority, swap just the fallback's platform implementation. |
| `document.createElement('a')` + blob URL download | ~12 export features (Payroll, exports, backups, audit logs, BAS worksheet, etc.) | **High** | One shared pattern — build one `downloadFile(blob, filename)` utility now, implement per-platform (native Share/Save) once. |
| `navigator.connection` (Network Information API) | `components/pos/POSHeaderBar.jsx` | **High** | Chromium-only, absent in iOS WebKit entirely — needs a native-bridge fallback or must degrade to optional/best-effort. |
| `getUserMedia` (camera) | `components/pos/ScanVoucherButton.jsx` (QR scan) | **High** | Needs a native Capacitor camera/barcode-scanner plugin, not raw `getUserMedia`, for reliable permission handling. |
| `getUserMedia` (microphone) | `VoiceCommandButton.jsx`, `VoiceOrderButton.jsx`, `pages/VoiceRecipe.jsx` | **High** | Same — needs native mic-permission handling per platform. |
| `navigator.clipboard` | ~10 "copy link/code" call sites | Medium | Wrap in one `copyToClipboard()` helper; Capacitor/Tauri/Electron each have their own clipboard API. |
| Raw `WebSocket` | `useSplitWebSocket.js`, `SplitBillStaff.jsx` | Medium | Works unchanged in any webview; just stop deriving the URL from `window.location` (breaks once the app isn't same-origin with the API). |
| `navigator.onLine` | `Login.jsx`, `services/offline.js`, `POSHeaderBar.jsx` | Low-medium | Supported everywhere; supplement with Capacitor's `Network` plugin for connectivity-change events specifically. |
| `localStorage`/`sessionStorage` | Pervasive — auth token, device token, theme, login-mode, app-shell selection, accessibility prefs | Low-medium | Works as-is everywhere; for a POS storing auth tokens, consider migrating the auth-critical keys to native secure storage rather than leaving a hard rewrite for later. |
| `indexedDB` | Two independent layers: `services/offline.js` (`SquarePOSDB`) and `lib/offlineQueue.js` (`nua-offline` — the real offline sales queue, `pending_transactions`/`pending_course_actions`/`cached_reads`) | Low | **Best-positioned existing subsystem for porting as-is** — IndexedDB works natively in Capacitor/Electron/Tauri. This is very good news for Phase 3 (offline-first foundation): a real offline queue already exists; audit it before building a new one. |
| Service worker / manifest | `public/sw.js`, three manifest variants, runtime manifest-swap in `index.html` | Medium | Meaningless inside Capacitor/Electron/Tauri app shells (no browser nav context to intercept) — must be disabled for native builds; reconcile anything it silently cached with the existing IndexedDB offline queue so native builds don't lose functionality. |
| `navigator.bluetooth` / `.usb` / `.serial` | **None found** | — | Not a migration problem — there's no existing WebUSB/WebBluetooth/WebSerial code. But it also means no existing Bluetooth-printer/cash-drawer/scale integration exists at all; that's new work, not porting work. |
| Geolocation, Notification API | **None found** | — | Not in use anywhere in `src`. |

---

## Toolchain availability (this sandbox, for context on what could be verified this pass)

- Node 22, npm 10.9, Java (OpenJDK) 21, Gradle, Capacitor CLI 6.2.2: **available**.
- `ANDROID_HOME`/`ANDROID_SDK_ROOT`: **not set, no Android SDK installed**.
  `npx cap add android` can generate the native project and its Gradle
  wrapper, but **an actual `./gradlew assembleDebug` build, APK output, or
  emulator launch is not possible in this container** without installing
  the Android SDK platform/build-tools (several GB; not attempted without
  confirming it's wanted and that network egress to Google's SDK
  repositories is permitted here).
- No Xcode/macOS runner — iOS build/compile-check is categorically not
  possible from this environment, consistent with the directive's own
  Phase 10 guidance ("no Apple-specific implementation is required until
  the architecture has been validated").
- Windows build/compile-check (Electron NSIS) isn't possible *from this
  Linux container itself* — `apps/windows/src/main.cjs` refuses to start
  on anything but `win32`, confirmed by actually running it here, not
  assumed. Unlike iOS, though, a real Windows runner *is* reachable: CI
  (`.github/workflows/windows-foundation.yml`) runs on GitHub's
  `windows-latest`, builds the actual unsigned NSIS installer, and
  launches the real packaged app for an end-to-end smoke test — see
  `WINDOWS_ARCHITECTURE.md`. This sandbox's own Node unit tests
  (`node --test` across `apps/windows`/`packages/platform-core`) still
  ran fine here, since pure JS logic needs no Windows API.

This means: this pass can scaffold the Capacitor Android project, write
and unit-test the shared platform-abstraction/offline/sync code, and prove
it in the existing Playwright/pytest suites — but **cannot** itself produce
a signed/running APK, launch an emulator, or validate on physical hardware.
Those require a toolchain this sandbox doesn't have.

---

## Windows Phase 0 audit (Codex, `feat/windows-foundation` — PR #21)

Run independently of the Android/iOS audit above, before any Windows
source changes, then folded into this canonical document when that work
was taken over and integrated. Preserved close to verbatim; only the
framing above this line is new.

Audit date: 2026-10-12. Scope: Windows touchscreen POS (target 3) and
Windows desktop (target 4). Base: `origin/main`,
`99635835b841b1516b9eeb4e394faf29f3a90d2d` — same baseline as the
Android/iOS audit above, independently re-verified rather than assumed
(`codex/owner-access` exists but lacks the later merged launch
corrections; main contains PRs 17–20).

**Findings and root causes:**

| ID | Severity | Evidence / root cause | Disposition |
|---|---|---|---|
| W01 | Blocker | `frontend/electron/main.js` never loads its preload; advertised IPC methods have no handlers. | Replaced the Windows entry path with the isolated, tested `apps/windows/` shell — the old scaffold is not used to release this. |
| W02 | Blocker | Electron 33 and an alternate Electron 28 manifest competed; the alternate packaged backend/Mongo paths. | New Windows-only locked manifest (`apps/windows/package.json`, Electron 44.7.0); old launch commands must not be treated as supported. |
| W03 | Blocker | `BrowserRouter` used paths while the shell loaded `file://`; API env was baked at build, not read from a bridge. | Bundled custom secure origin (`nua://app`) with SPA fallback and an explicit build-time API origin (`NUA_WINDOWS_API_ORIGIN`). |
| W04 | Critical | The active IndexedDB `nua-offline` queue is global; records/cache lack account/business partition. Replay uses the current account's token. | Built a reusable scoped queue foundation (`packages/platform-core`) as a shared integration blocker to coordinate before release — does not silently migrate or declare the existing queue safe. |
| W05 | Critical | `offlineQueue.js` drops server-rejected records; KDS actions lack stable initial mutation IDs; offline card returns synthetic success. | `CashOrderQueue`'s durable failure/unknown states and idempotent, cash-only contract — current POS caller migration is still required, not done. |
| W06 | High | Auth access/trusted-device tokens reside in `localStorage`; multiple direct consumers. | OS-encrypted storage foundation (`EncryptedStore` + `windowsCrypto`) — now actually wired to the shared `SecureStorageService` contract in the integration pass; was a foundation primitive only at audit time. |
| W07 | High | `printer.js` POSTs HTTP to a raw TCP port; receipt HTML interpolated business/item data unescaped. | Native spooler path + escaped, structured receipt builder (`receipt.cjs`) — now actually called from `services/printer.js` for the Windows platform in the integration pass; the kitchen docket (`services/docket.js`) still prints unescaped HTML, mitigated by the print preview window's `javascript: false` sandboxing rather than field-level escaping (see `MOBILE_DESKTOP_BACKLOG.md`). |
| W08 | High | The active service worker excludes `/api/` but not `/bookings-api/`; generic GET caching and forced activation can retain data/reload mid-sale. | Windows has bundled assets and runs no service worker at all — not applicable to this host; the shared PWA correction remains outstanding for web/Android/iOS. |
| W09 | Blocker | No device-pairing credential bound to every native request; license revocation (`routes/licensing.py`) doesn't itself revoke a staff token. | Documented as a real server-side extension still needed; device identity (this effort's shared `backend/routes/devices.py`) closes part of this — revoking a *device* works in real time — but a device's own request isn't additionally cryptographically attested beyond the staff member's bearer token. Not fabricated here. |
| W10 | Blocker | No signing identity, controlled updater, minimum-client-version endpoint, or physical hardware matrix evidence. | CI produces an unsigned artifact only; release gates remain closed — see `APP_RELEASE_STRATEGY.md`. |

(M01/I01 from the original table — Capacitor version drift and no Apple
project — are the Android/iOS audit's own findings above, cross-
referenced rather than duplicated.)

**Compatibility note**: DOM, keyboard/touch, and IndexedDB all work
inside Electron; availability alone doesn't establish security or
offline correctness — camera, microphone, USB/serial/Bluetooth,
notifications, and geolocation all require explicit grants or adapters
that this host's own policy (see `WINDOWS_ARCHITECTURE.md`) denies by
default. WebSockets must use the configured backend origin rather than
`window.location.host`, since there's no meaningful browser-nav host on
a custom `nua://` origin.
