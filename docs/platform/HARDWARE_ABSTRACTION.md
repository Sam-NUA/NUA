# Hardware abstraction

## Printer

**Primary path, unchanged by this work**: `backend/services/escpos.py`
sends raw ESC/POS bytes over TCP port 9100 directly to a network-connected
thermal printer. This is server-side, has no browser/WebView dependency
at all, and works identically on every platform — the single biggest
reason the mobile-portability story here is better than it would be for a
POS that printed via WebUSB/WebBluetooth from the client.

**Fallback path** (used only when the network printer call fails, or for
on-screen documents with no ESC/POS equivalent — gift card detail, 2FA
recovery codes): `frontend/src/platform/*/PrintService.js`.
- Web: unchanged `window.open` + `document.write` + `window.print()`
  popup, exactly as before this pass.
- Capacitor: no print plugin is installed (none exists in `package.json`,
  and the directive is explicit — "do not implement unsupported providers
  merely to fill the interface"). Instead, hands the receipt as plain
  text to the native Share sheet (`@capacitor/share`), so staff can still
  save/print it via any app that accepts shared text. A dedicated print
  plugin (e.g. `@capacitor-community/printer` or similar) is backlog, not
  faked here.
- Electron: **correction** — the web adapter does NOT work as a fallback
  here: `apps/windows/src/main.cjs`'s `restrict()` denies every
  `window.open` call unconditionally (not just cross-origin ones), so the
  web `PrintService.printHtml`'s popup would silently fail to even open.
  `platform/electron/PrintService.js` instead calls `window.nuaDesktop
  .printHtml()`/`.printReceipt()`, which print via `webContents.print()`
  in a disposable, `javascript:false` preview window — a real native
  path, not a fallback. `printReceipt` additionally builds and escapes
  the receipt natively from structured fields
  (`apps/windows/src/receipt.cjs`) rather than interpolating transaction
  data into an HTML string, closing the Windows audit's W07 finding for
  the one call site (`services/printer.js`) that has fully structured
  data to give it; the kitchen docket (`services/docket.js`) still uses
  arbitrary HTML via `printHtml`, mitigated by that same `javascript:
  false` sandboxing rather than field-level escaping.

No USB, Bluetooth, or Serial printer code exists anywhere in this
codebase (confirmed by the Phase 0 browser-API audit — zero
`navigator.usb`/`.bluetooth`/`.serial` hits). That's not a migration gap,
it's new functionality if a venue needs a USB/Bluetooth-only printer with
no network interface — out of scope for this pass.

## Cash drawer

No cash-drawer integration exists anywhere in this codebase today — not a
browser API, not a backend service. `frontend/src/platform/*/
CashDrawerService.js` now formalizes this as a real interface (directive
Phase 7: "model cash drawer control independently" of any printer) —
`getCapability()` reports `'unsupported'` on every platform and `open()`
rejects rather than fabricating success, matching the payment-offline
rule's "never a fake successful state" discipline. This is new work, not
porting work, for whichever platform needs it first (typically a printer
kick-pulse command sent alongside a receipt print, or a direct USB/serial
trigger) — the interface exists so that work has a contract to implement
against, nothing more was attempted.

## Barcode / QR scanner

- **QR generation** (not scanning) exists client-side: `qrcode.react`,
  used for vouchers/payment links/gift cards — renders a code, doesn't
  read one.
- **Camera-based scanning**: `components/pos/ScanVoucherButton.jsx` now
  delegates its support check to `platform/*/ScannerService.js`'s
  `isCameraScanAvailable()` instead of checking `'BarcodeDetector' in
  window` directly — the underlying `getUserMedia`/`BarcodeDetector`
  logic is unchanged, only the capability check moved behind the
  abstraction. This is more than cosmetic: web/Capacitor both still
  feature-detect the same way (a real Chromium/WKWebView engine either
  has `BarcodeDetector` or doesn't), but Electron's implementation
  honestly hardcodes `false` — the Windows host's session denies every
  camera permission request outright (`setPermissionCheckHandler(() =>
  false)`), so the raw feature-detection the old code did would have
  shown the scan button there and had it silently fail the moment
  someone tapped it. Permission-flow hardening (a Capacitor barcode-
  scanning plugin, for a native-feeling prompt on Android/iOS) is still
  backlog, not done this pass.
- No physical/dedicated barcode scanner (keyboard-emulation USB/Bluetooth
  scanner) integration exists; those typically just emit keystrokes and
  would work with any focused text input already, untested explicitly.

## Payment terminals

The backend has tenant-scoped EFTPOS routes and partial provider classes for
Linkly/Tyro/Smartpay (TCP purchase attempts) and Windcave (HTTP purchase attempt),
plus a test-only simulator. This corrects the old claim that no communication
code exists, but does not establish vendor compatibility or merchant support.

The four non-simulator classes inherit unimplemented refund/cancel/settlement
methods. Tyro/Smartpay/Windcave also inherit an unimplemented disconnect;
a successful purchase followed by that failure can be reported as an error.
The shared settings UI exposes configuration/diagnostics, not an integrated
POS purchase call. A cloud backend's ability to reach a venue LAN must also be
proved. See [payment terminal architecture](PAYMENT_TERMINAL_ARCHITECTURE.md)
for the exact limits and remaining vendor/topology/reconciliation work.

`frontend/src/platform/*/PaymentTerminalService.js` reports `unsupported` on
all platforms. No client terminal SDK or new guessed protocol is added here.
Choose the actual venue hardware and approved specification before completing
that integration; do not treat the simulator as evidence of a card charge.

## Biometric reauthentication (directive Phase 5)

Not a hardware capability in the printer/scanner/drawer sense, but the
same "interface exists, honestly unsupported" pattern applies:
`frontend/src/platform/*/BiometricService.js`'s `isAvailable()` is
`false` on every platform (no Face ID/Touch ID/BiometricPrompt/Windows
Hello plugin installed). What actually gates a sensitive action today
— wired into refund, void, and three sensitive-settings call sites —
is `POST /api/auth/verify-sensitive-action`'s server-verified PIN
re-entry. See `SECURITY_MODEL.md` for the full account, including which
call sites are covered and which settings pages were deliberately not
reviewed.

## Summary — what's real vs. what's a documented gap

| Capability | Status |
|---|---|
| Network ESC/POS printing | **Works unchanged on every platform** — no abstraction needed, already platform-agnostic. |
| Browser/popup print fallback | Abstracted this pass (PrintService); Capacitor uses Share-based export, not real native printing; Electron (Windows) has a real native print path via `webContents.print()`, not a fallback at all — the web popup path is actively denied inside that host. |
| Cash drawer | Interface exists (`CashDrawerService`), reports `'unsupported'` everywhere — not implemented anywhere, new work. |
| QR generation | Works unchanged (pure rendering). |
| Camera QR/barcode scanning | Works via `getUserMedia`, now behind `ScannerService.isCameraScanAvailable()`; honestly `false` on Electron (host denies camera permission outright) where the old direct check would have lied. Permission-flow hardening is still backlog. |
| Payment terminal SDKs | Server-side tenant-scoped routes and partial, unverified adapters exist; not merchant-ready. Client `PaymentTerminalService` reports `unsupported` everywhere. See provider/lifecycle/topology limits above. |
| Biometric reauthentication | Interface exists (`BiometricService`), reports unavailable everywhere; PIN-based server-verified reauth is the real gate, wired into refunds only so far. |
