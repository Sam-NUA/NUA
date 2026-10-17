# Mobile/desktop backlog

> **14 October 2026 review update:** See [MOBILE_HARDENING_REVIEW_2026-10-14.md](MOBILE_HARDENING_REVIEW_2026-10-14.md) for current fixes, validation and release limits. Earlier status/count/migration claims below are historical. The review removes native plaintext token fallback, quarantines legacy queues, retains rejected records, adds terminal management/export, and fixes scoped stock-transfer writes. Native cold-restart authorisation, hardware, signing and Windows checkout integration remain open.


Things identified this pass as real, named gaps — not silently dropped,
not pretended done. Ordered roughly by what blocks the Android critical
acceptance milestone first.

## Blocks real on-device verification

1. **No Android SDK in this sandbox.** `npx cap add android` succeeded,
   the Gradle wrapper runs, dependency resolution reaches exactly the
   expected failure (fetching the Android Gradle Plugin from
   `dl.google.com`, blocked by this sandbox's network policy — confirmed
   via a real `./gradlew assembleDebug` run, not assumed). Needs either
   SDK installation in a sandbox with broader network egress, or a
   toolchain outside this environment. Until then, nothing Android-side
   has been run on an emulator or device — every claim in this pass's docs
   that says "not independently verified on-device" means exactly that.

## Call-site migrations (abstraction exists, not every site swapped)

2. **Done.** All remaining `window.confirm`/`prompt` sites now go through
   `DialogService` — 49 occurrences across 32 files, migrated as their
   own focused pass. Three were deliberately left as direct
   `window.confirm` calls: `EFTPOSTerminals.jsx` and
   `SecurityCompliance.jsx` use it as a cheap pre-validation step before
   the real `SensitiveActionReauthDialog` gate (see item 27), and
   `components/payments/RefundDialog.jsx` the same way before its own
   reauth step — none of the three is the actual confirming action a
   user relies on.
3. **Done.** All blob-download sites now go through
   `FileService.downloadFile` — 13 occurrences across 12 files (there
   turned out to be zero pre-existing call sites, not the ~1-already-done
   this item originally assumed). Same Blob contents/MIME types/filenames
   throughout; a real functional fix on Windows specifically, where the
   web `<a download>` path is silently blocked with no error surfaced.
4. **Done.** All 26 call sites that read `localStorage.getItem('nua_token')`
   directly now go through the async `SecureStorageService.getToken()`/
   `clearToken()` instead — real Keystore/Keychain/DPAPI, not just the
   `localStorage` mirror those methods still write for backward
   compatibility. One deliberate exception: `services/api.js`'s
   `coursingAPI.streamUrl()` reads the mirror directly and always will —
   `EventSource` has no async construction path or custom-header support,
   so the token has to go in the URL synchronously. Verified: a clean
   grep for stray direct reads, `craco build` green, the full Jest suite
   (29 tests) green, and a manual re-read of every converted call site to
   confirm no missing `await` (which a build/test run would not catch —
   it would silently send `Bearer [object Promise]`).

## Hardware (new work, not porting)

5. No cash-drawer integration anywhere (browser or native).
6. No native barcode-scanner plugin (QR scanning works via raw
   `getUserMedia`, but permission UX isn't native-feeling on Android).
7. No real native print plugin for Capacitor — current fallback routes to
   the Share sheet, which works but isn't "press print, it prints."
8. No payment-terminal SDK integrated for any platform (Stripe Terminal,
   Square, Tyro, Zeller, Worldline) — `services/eftpos_service.py` exists
   but its actual terminal-SDK integration wasn't independently verified
   this pass.

## Security hardening

9. **Done.** Real Keystore (Android) / Keychain (iOS)-backed secure
   storage: `capacitor-secure-storage-plugin` replaces `@capacitor/
   preferences` for the token, verified against its own native source
   (real `AndroidKeyStore` RSA encryption before the `SharedPreferences`
   write on Android, real Keychain via `SwiftKeychainWrapper` on iOS) —
   see `SECURITY_MODEL.md` item 2. `SecureStorageService.getToken()`
   migrates an existing `@capacitor/preferences` token in rather than
   signing an upgraded install out; 5 Jest tests cover that migration
   logic with the native plugins mocked. Still not run on a real device
   or emulator — only against mocked tests and a successful compile.
10. Biometric reauthentication for refunds/voids/sensitive settings
    (directive Phase 5) — not implemented at all this pass.

## Offline/sync

11. Reservations/customers/loyalty have no offline read cache (menu and
    open tickets do) — those screens go blank rather than stale-but-usable
    during a dropout.
12. `useOfflineQueue` still triggers on the web `online`/`offline` events
    + a 30s poll rather than Capacitor's `Network` plugin (the adapter
    exists in `platform/capacitor/NetworkService.js`, just not wired into
    this specific hook yet).
13. No local-storage tenant partitioning — a single device used across
    two different businesses would share one offline queue/cache. See
    `TENANT_ISOLATION_TEST_PLAN.md`.

## Not started (per the master directive's own phasing, correctly deferred)

14. `NUA Business` (the separate owner/manager app) — directive says not
    to build it yet unless needed for architectural separation; nothing
    in this pass's work prevents it later (see ADR-001's consequences).
15. Device management UI (Settings page listing/revoking devices) — the
    API exists, no frontend page calls it yet.
16. Release channels (internal/staging/production tracks, Play Store
    listing, signing/keystore setup) — explicitly out of scope: "Do not
    publish anything during this assignment."
17. Windows implementation — started independently by Codex on
    `feat/windows-foundation` (real `apps/windows` Electron host,
    `packages/platform-core`'s cash queue), then taken over and wired into
    the shared `platform/electron/*` adapters in a later pass of this
    session — see `WINDOWS_ARCHITECTURE.md` for the full account. (iOS
    scaffolding — `@capacitor/ios`, the native `frontend/ios/` project,
    Info.plist permission/ATS fixes — was done in a separate later pass;
    see `IOS_IPADOS_ARCHITECTURE.md` for what's real there. A later pass
    added `.github/workflows/ios.yml` on a real `macos-latest` CI
    runner: real build, real Simulator boot, install and launch all
    pass for real now — the "no macOS build environment" gap is closed
    for CI purposes; a physical iPhone/iPad and the full offline
    critical-acceptance milestone remain unattempted on iOS.)

## Windows-specific (see WINDOWS_ARCHITECTURE.md and
## OFFLINE_SYNC_ARCHITECTURE.md's Windows section for the full detail)

18. `CashOrderQueue` (`packages/platform-core/queue.cjs`) is built and
    independently tested but not wired into the real checkout flow —
    `POSTerminal.jsx` still goes through `lib/offlineQueue.js` on every
    platform, Windows included. Needs a coordinated integration: decide
    how/whether it replaces the shared queue for cash orders specifically,
    quarantine whatever's already in a Windows install's existing
    IndexedDB store, and prove the full restart/reconnect/exactly-one/
    foreign-tenant milestone against it for real. Re-examined this pass
    (still deliberately not wired, same conclusion, now with a concrete
    reason beyond "needs coordination"): the queue's own allowlist permits
    `walkInName` on an order, but `backend/routes/transactions.py`'s
    `TransactionCreate` schema (the only server endpoint this queue could
    realistically call) has no `walkInName` field at all — it would
    silently pass pydantic's default extra-field handling and the name
    would never reach the stored order. Routing real cash sales through
    this queue today means either accepting that silent data loss or
    widening the backend schema first; building the IPC/electron wiring
    around either choice without first resolving which (and without a real
    backend to prove the exactly-once/foreign-tenant milestone against) is
    exactly the kind of risky, unaudited change to a live POS flow this
    project avoids making unilaterally. Left for a dedicated pass with the
    schema question decided up front.
19. Kitchen docket printing on Windows (`services/docket.js` via
    `nua:print-html`) relies on the preview window's `javascript: false`
    sandboxing rather than field-level HTML escaping the way the
    structured receipt path (`nua:print-receipt`) does — safe against
    script execution, not against a malformed docket visually distorting
    the print preview. A structured, escaped docket schema (mirroring
    `receipt.cjs` but for kitchen tickets — course/station/allergen
    fields, no totals) would close this properly; not attempted this pass
    since it would mean redesigning `generateDocketHTML`'s actual
    structure, not just its print transport.
20. No real device-pairing credential exists for Windows (or any
    platform) beyond the device-identity registry itself — per
    `CURRENT_ARCHITECTURE_AUDIT.md`'s W09 finding (carried over from the
    Windows Phase 0 audit), a revoked device's *registry entry* is
    rejected, but there's no cryptographic per-request terminal
    attestation distinct from the staff member's own bearer token.
    Tracked as a real gap, not resolved by device identity existing.
21. No code-signing certificate, controlled auto-update mechanism, or
    minimum-supported-version gate for the Windows installer — CI
    produces an unsigned NSIS artifact for review only; see
    `APP_RELEASE_STRATEGY.md`.
22. `apps/windows`'s `npm audit` reports 8 moderate findings (0 high/
    critical), all tracing to one advisory (GHSA-hp3w-g68c-fv3c,
    sprintf-js, via `electron-builder`'s build toolchain — no patched
    sprintf-js version exists upstream) in a build-only dependency path,
    not a packaged runtime one (`npm audit --omit=dev` reports 0). Not
    ignored or suppressed; reassess when an upstream fix exists. The
    pre-existing, much larger frontend dependency debt (129 findings —
    Capacitor CLI, old Electron/electron-builder, CRA, serve, Tailwind,
    ESLint toolchain paths) is unrelated and already tracked as its own
    gap, not expanded or shrunk by this item.
23. No physical Windows hardware QA — touchscreen (44px targets, touch
    mode), a real thermal printer via the Windows spooler, keyboard-wedge
    barcode scanners, and 100–200% display scaling have none of their
    behavior verified on an actual device, only in CI's `windows-latest`
    runner (which proves the app launches and the bridge/sandbox/crypto
    behave correctly, not that physical hardware behaves correctly).

## Directive Phase 11 (versioning) and Phase 5 (biometric) — what's not done

24. No on-screen version/device readout — `App.js` logs
    `App: ${APP_VERSION} · Platform: ...` to the console on launch
    instead of rendering it anywhere visible. A persistent on-screen
    badge was built, then deliberately not shipped: this pass never
    audited every POS screen (toasts, an Ash FAB, modal chains) for a
    fixed-position collision, and a regression on a live, heavily-used
    till screen is a worse outcome than a missing "what version is this"
    readout a support call can still get from devtools. A real UI surface
    (likely inside Settings, or a dedicated small About section) is
    real, named work for whoever picks this up, not optional polish.
25. **Done.** `GET /api/version` and `VersionGateMiddleware` (426 on an
    under-`MIN_SUPPORTED_APP_VERSION` `X-App-Version` header) exist and
    are tested, and the "update required" UX now exists too:
    `VersionGateLockScreen.jsx`, a full-screen overlay mounted globally
    in `App.js`, trips on any 426 the `api.js` response interceptor sees
    (`lib/versionGate.js`'s tiny external store). Still true: no native
    build actually SENDS a version below the current one yet, so this
    has never been exercised against a real request from a genuinely
    out-of-date app in the field — only against a crafted 426 in Jest
    tests and by reasoning through the middleware's own existing tests.
26. `BiometricService` is a real interface across every platform but
    `isAvailable()` is hardcoded `false` everywhere — no Face ID/Touch
    ID (iOS), BiometricPrompt (Android), or Windows Hello integration
    exists. `POST /api/auth/verify-sensitive-action`'s PIN-based fallback
    is what actually gates `RefundDialog.jsx` today. Wiring a real
    biometric plugin in later should need no call-site changes beyond
    `BiometricService.isAvailable()` starting to return `true` — that's
    the point of building the interface now rather than skipping it.
27. **Updated — no longer accurate as written.** `SensitiveActionReauthDialog`
    is now wired into `RefundDialog.jsx`, `CompVoid.jsx`/`POSTerminal.jsx`'s
    comp/void dialog (void), and three sensitive-settings actions:
    `SecurityCompliance.jsx`'s 2FA-disable and GDPR customer erasure, and
    `EFTPOSTerminals.jsx`'s terminal removal. This is a deliberately
    bounded set — actions matching the refund precedent (a real financial
    or irreversible consequence from one action), not every settings
    toggle in the app — not an exhaustive audit of every page. Real,
    still-unstarted follow-on work: role/permission changes, staff PIN
    resets, and tax/payment-provider configuration changes were not
    reviewed for whether they belong on this same gate.

## Directive Phase 7 (remaining hardware) and Phase 12 (telemetry) — what's not done

28. `CashDrawerService`/`PaymentTerminalService` exist on every platform
    and honestly report `'unsupported'` — no real provider (a cash-drawer
    kick-pulse command, a Stripe Terminal/Square/Tyro/Zeller SDK) is
    integrated anywhere. Per directive, this is deliberate: don't build
    against hardware/an SDK nobody has confirmed the business needs.
    Whoever picks a real provider implements it against these interfaces
    rather than inventing a new contract.
29. `ScannerService`'s Electron answer (`isCameraScanAvailable() =>
    false`) is honest but not improved — the underlying blocker (the
    Windows host's `setPermissionCheckHandler(() => false)` denying every
    camera permission request) was not relaxed, since loosening it is a
    security-relevant host-policy change outside this pass's scope, not
    a platform-layer fix. A native Capacitor barcode-scanning plugin (for
    a better permission UX on Android/iOS, where the raw `getUserMedia`
    prompt is functional but not native-feeling) is still backlog too.
30. Client telemetry (`client_event_log`, `lib/telemetry.js`) has no
    consumer yet beyond the raw `GET /api/ops/client-events` read — no
    dashboard, alerting, or paging is wired to it. It's a queryable
    record of app launches/sync failures/printer failures/device
    registrations, not yet a signal anyone is watching in real time.
31. The known-event-type allowlist (`KNOWN_TYPES` in `lib/telemetry.js`,
    `CLIENT_EVENT_TYPES` in `services/observability.py`) only covers the
    five event kinds this pass actually wired up (`app_launch`,
    `sync_failure`, `printer_failure`, `hardware_error`,
    `device_registered`) — `hardware_error` itself has no caller yet; it
    was added to the allowlist for the cash-drawer/payment-terminal/
    scanner interfaces' future real implementations to use without a
    backend change, not because anything emits it today.
