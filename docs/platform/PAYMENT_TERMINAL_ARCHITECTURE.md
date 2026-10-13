# Payment terminal architecture

## Current state (verified by reading the code, not assumed)

No payment-terminal SDK (Stripe Terminal, Square Terminal API, Tyro,
Zeller, Worldline, or similar) is integrated anywhere in this codebase.
Payments today are either:
- **Hosted/online checkout**: Stripe (`routes/integrations.py`,
  `routes/licensing.py`), Coinbase Commerce (crypto), Square (via the
  generic `services/connect/` connector framework) — all server-initiated,
  none require in-person terminal hardware.
- **In-person, via `services/eftpos_service.py`** — exists, but this pass
  did not independently verify whether it talks to a real terminal SDK or
  is a data model for terminal *configuration* without an actual
  hardware-communication layer. Flagged for whoever picks this up next;
  not resolved here.

Windows's own foundation pass (`feat/windows-foundation`) reached the
same conclusion independently: no terminal adapter is implemented or
certified there either, and its cash-order queue (`packages/platform-
core/queue.cjs`) explicitly refuses anything but `paymentMethod: 'cash'`
— card, gift-card/customer-balance and loyalty redemption are rejected
outright by its own field validation, not merely undocumented. See
`OFFLINE_SYNC_ARCHITECTURE.md`'s Windows section.

## Why nothing was built this pass

Per the master directive: "Do NOT implement unsupported providers merely
to fill the interface." No specific terminal/provider was named as a
target, and guessing one (and building an interface against a provider's
SDK that may not match what the business actually contracts with) would
be exactly the kind of speculative, unrequested work the directive asks
to avoid.

## What the interface should look like, once a provider is chosen

A `PaymentTerminalService` under `platform/*/` following the same pattern
as every other service in this pass (`web/` = unsupported/no-op or a
clear "not available" error, `capacitor/` and `electron/` = the real SDK
integration), with a shape roughly like:

```text
connect(terminalConfig) -> Promise<ConnectionHandle>
chargeAmount(handle, amountCents) -> Promise<ChargeResult>
cancelCharge(handle) -> Promise<void>
disconnect(handle) -> Promise<void>
```

Backed by whichever provider SDK the business actually uses — Stripe
Terminal's JS SDK has a Capacitor-compatible path via its own React
Native/mobile SDKs (would need a dedicated Capacitor plugin, not the
web JS SDK, for real NFC/card-reader hardware access), Square's Terminal
API is server-mediated (no client SDK needed at all, just backend calls
the `services/connect/connectors/square.py` module could extend). This
is a real architectural fork depending on which provider is chosen — not
resolved here, intentionally, per the directive's own instruction above.
