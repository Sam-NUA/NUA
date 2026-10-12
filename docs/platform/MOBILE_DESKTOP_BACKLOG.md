# Mobile/desktop backlog

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

2. **~28 of ~30 `window.confirm`/`prompt` sites** still call the browser
   API directly rather than `DialogService`. Two were swapped in
   `POSTerminal.jsx` (held-sale resume/cancel) to prove the pattern.
   Full list from the Phase 0 browser-API audit: `SecurityCompliance.jsx`,
   `SocialMedia.jsx`, `InventoryAccounting.jsx`, `CoursingAnalytics.jsx`,
   `Products.jsx`, `LicensePage.jsx`, `v26/VoucherManager.jsx`,
   `AutomationTriggers.jsx`, `finance/Budgets.jsx`, `StockTransfers.jsx`,
   `Categories.jsx`, `finance/Deposits.jsx`, `finance/Journals.jsx`,
   `finance/ChartOfAccounts.jsx`, `BookingExperience.jsx`,
   `AuditLogUniversal.jsx`, `components/payments/RefundDialog.jsx`,
   `StaffRoster.jsx`, `Reservations.jsx`, `v25/Subscriptions.jsx`,
   `Vouchers.jsx`, `Today.jsx`, `Appointments.jsx`, `AshMemory.jsx`,
   `LoyaltyProgress.jsx`, `Temperature.jsx`, `ImageLibrary.jsx`,
   `Settings.jsx`, `social/SocialCalendar.jsx`, `Clubmember.jsx`,
   `floor/TableInfoDrawer.jsx`, `AshPermissions.jsx`,
   `IdentitySettings.jsx`, `EFTPOSTerminals.jsx`,
   `products/ProductVariants.jsx`. Each is a mechanical
   `window.confirm(...)` → `await DialogService.confirm(...)` swap inside
   an already-async handler in most cases — low risk, high count, exactly
   the kind of change worth doing as its own focused pass rather than
   mixed into this one.
3. **~11 of ~12 blob-download sites** still build `<a download>` inline
   rather than calling `FileService.downloadFile`. List:
   `Payroll.jsx`, `MultiBusiness.jsx`, `Temperature.jsx`,
   `SecurityCompliance.jsx`, `InventoryAccounting.jsx`, `Products.jsx`,
   `PaymentLinks.jsx`, `AuditLogUniversal.jsx`, `BookingAnalytics.jsx`,
   `settings/BackupPanel.jsx`, `customers/GuestWalletDialog.jsx`,
   `bas/BasWorksheetPanel.jsx`.
4. **~20 pages read `localStorage.getItem('nua_token')` directly**
   instead of `SecureStorageService.getToken()` — currently safe on
   Android only because the Capacitor adapter mirrors into `localStorage`
   (see `SECURITY_MODEL.md`), but that mirror caps how much the
   Preferences-based hardening actually buys until these are migrated.
   List: `NotificationBell.jsx`, `AshChat.jsx`, `hooks/useLiveFeed.js`,
   `AshCommandCenter.jsx`, `Approvals.jsx`, `AIPantry.jsx`,
   `EmailMarketing.jsx`, `AshPermissions.jsx`, `StaffManagement.jsx`,
   `StaffRoster.jsx`, `AuditLogUniversal.jsx`, `AutomationTriggers.jsx`,
   `Products.jsx`, `AshDashboard.jsx`, `LoyaltyProgress.jsx`,
   `MeasuredStock.jsx`, `Settings.jsx`, `AshMemory.jsx`, `ShiftSwaps.jsx`,
   `Dashboard.jsx`, `HQDashboard.jsx`, `v26/StaffAvailability.jsx`,
   `AshPlans.jsx`.

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

9. Keystore-hardware-backed secure storage (beyond
   EncryptedSharedPreferences) — see `SECURITY_MODEL.md`.
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
17. Windows/iOS implementation — Windows is ChatGPT's lane this pass; iOS
    has no `@capacitor/ios` dependency installed and no native project
    generated, matching the directive's "no Apple-specific implementation
    required yet."
