# Payment terminal architecture

Reviewed 19 October 2026 against `backend/services/eftpos_service.py`,
`backend/routes/settings.py`, `frontend/src/services/api.js` and
`frontend/src/pages/EFTPOSTerminals.jsx`. Existing code is not proof of a
working or certified merchant integration.

## Implemented API surface

Tenant-owned terminal/configuration/history reads and updates in these routes
use `tenant_scope_filter`; inserts stamp the authenticated `businessId`.
Configuration changes, connection tests, history and settlement require
owner/manager access. Signed-in staff can list terminals (provider secrets are
redacted for other roles) and request a transaction for their own terminal.

- `POST /api/eftpos/terminals/{id}/test` attempts connection and logs the result.
- `POST /api/eftpos/transaction` dispatches purchase/refund/cancel and records
  an approved/declined/error result in tenant-scoped `eftpos_transactions`.
- `POST /api/eftpos/terminals/{id}/settlement`, `GET /api/eftpos/transactions`
  and `GET /api/eftpos/terminals/{id}/test-history` also exist.

## Provider implementation limits

| Provider | Code present | Unresolved limits |
| --- | --- | --- |
| Linkly | TCP connection and JSON purchase attempt; disconnect implemented | Refund, cancel, settlement and status inherit `NotImplementedError`; framing and actual vendor compatibility unverified. |
| Tyro | TCP connection and pipe-delimited purchase attempt | Disconnect, refund, cancel, settlement and status inherit `NotImplementedError`; framing and vendor compatibility unverified. |
| Smartpay | TCP connection and purchase attempt | Disconnect, refund, cancel, settlement and status inherit `NotImplementedError`; framing and vendor compatibility unverified. |
| Windcave | HTTP purchase attempt, defaulting to `https://sec.windcave.com/api/v1/transactions`; connect returns true without a network probe | Disconnect, refund, cancel, settlement and status inherit `NotImplementedError`; endpoint, authentication and response shape have not been validated against vendor documentation/account. |
| Simulator | Deterministic purchase/decline/timeout, refund, cancel, status and settlement behavior | Test-only in-memory ledger, not durable across cold starts; never evidence of a real card charge or certified refund accounting. |

`EFTPOSService.process_transaction()` calls `disconnect()` before returning a
purchase result. An inherited `NotImplementedError` there is caught as an error:
a provider might have accepted a purchase before the API reports failure.
That creates payment ambiguity and makes blind retry unsafe. Do not use these
partial adapters for live payments before completing and validating the chosen
vendor's lifecycle, reconciliation and idempotency behavior. A successful
connection test alone proves neither purchase support nor settlement.

The existing `test_eftpos.py` and `test_eftpos_test_history.py` use the simulator;
they do not verify the four vendor protocols. Westpac Presto, ANZ Worldline,
NAB Transact, CBA Albert and Square Terminal have no provider class or registry
entry here. No new provider or guessed protocol is introduced by this review.

## Frontend and network topology

The shared EFTPOS settings page configures terminals and shows diagnostics.
`eftposAPI` currently wraps those management/read endpoints; it does not expose
a purchase or settlement call. No call to `/eftpos/transaction` was found in
the shared POS checkout. Therefore an existing backend route must not be
presented as an end-to-end integrated card checkout on any platform.

The TCP code runs on the backend, not on the venue tablet or Windows host.
A cloud backend cannot be assumed to reach a venue's private LAN address;
`127.0.0.1` refers to that backend, not the venue's middleware. A selected
provider needs an explicitly validated network/bridge topology as well as its
approved specification, merchant account and physical terminal.

`frontend/src/platform/*/PaymentTerminalService.js` reports `unsupported`
on every platform. A client SDK or local bridge remains a separate decision
based on the actual venue hardware. Never fabricate successful terminal states
or weaken tenant/RBAC checks to make a provider appear supported.

Hosted/online checkout (Stripe, Coinbase Commerce and the Square connector)
is separate from this terminal layer. The Windows/native offline cash queues
also do not provide offline card authorization; they reject unsupported payment
methods. Real terminal acceptance, signing and distribution remain launch gates.
