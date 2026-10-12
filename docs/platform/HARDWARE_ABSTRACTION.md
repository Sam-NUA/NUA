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
- Electron: not implemented — falls back to the web adapter (correct,
  since an Electron renderer is a real Chromium context where
  `window.print()` opens the OS print dialog), but a silent/direct print
  via Electron's own `webContents.print()` IPC would be better and is
  ChatGPT's lane to build if wanted.

No USB, Bluetooth, or Serial printer code exists anywhere in this
codebase (confirmed by the Phase 0 browser-API audit — zero
`navigator.usb`/`.bluetooth`/`.serial` hits). That's not a migration gap,
it's new functionality if a venue needs a USB/Bluetooth-only printer with
no network interface — out of scope for this pass.

## Cash drawer

No cash-drawer integration exists anywhere in this codebase today — not a
browser API, not a backend service. This is new work, not porting work,
for whichever platform needs it first (typically a printer kick-pulse
command sent alongside a receipt print, or a direct USB/serial trigger).
Not attempted this pass.

## Barcode / QR scanner

- **QR generation** (not scanning) exists client-side: `qrcode.react`,
  used for vouchers/payment links/gift cards — renders a code, doesn't
  read one.
- **Camera-based scanning** exists via `components/pos/ScanVoucherButton.jsx`'s
  raw `getUserMedia({ video: ... })` call — works in any WebView including
  Capacitor's, but raw `getUserMedia` means the app handles camera
  permission prompting itself rather than through Capacitor's native
  permission flow, which is worse UX and less reliable permission state on
  Android specifically. A proper fix (swap to a Capacitor barcode-scanning
  community plugin) is backlog, not done this pass — the existing
  `getUserMedia` path should still function as-is in the Capacitor WebView
  without code changes, just with the permission-flow caveat above.
- No physical/dedicated barcode scanner (keyboard-emulation USB/Bluetooth
  scanner) integration exists; those typically just emit keystrokes and
  would work with any focused text input already, untested explicitly.

## Payment terminals

No payment-terminal SDK (Stripe Terminal, Square, Tyro, Zeller, Worldline,
etc.) is integrated anywhere in this codebase — payments today are
hosted-checkout/online (Stripe, Coinbase Commerce, Square via the Connect
framework) plus a separate `services/eftpos_service.py` model for
in-person terminals that doesn't appear to talk to a real terminal SDK
(not independently verified in depth this pass — flagged for whoever picks
up `PAYMENT_TERMINAL_ARCHITECTURE.md`'s actual implementation). Per the
master directive: do not implement an unsupported provider merely to fill
the interface — no terminal SDK work was done this pass.

## Summary — what's real vs. what's a documented gap

| Capability | Status |
|---|---|
| Network ESC/POS printing | **Works unchanged on every platform** — no abstraction needed, already platform-agnostic. |
| Browser/popup print fallback | Abstracted this pass (PrintService); Capacitor uses Share-based export, not real native printing. |
| Cash drawer | Not implemented anywhere — new work. |
| QR generation | Works unchanged (pure rendering). |
| Camera QR/barcode scanning | Works via raw `getUserMedia` as-is; permission-flow hardening is backlog. |
| Payment terminal SDKs | Not implemented — explicitly out of scope per directive (no unsupported-provider stubs). |
