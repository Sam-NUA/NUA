# Payment terminal architecture

## Current state — corrected after actually reading `eftpos_service.py`

An earlier version of this doc said "no payment-terminal SDK is
integrated anywhere in this codebase." That was wrong — reading
`backend/services/eftpos_service.py` and `backend/routes/settings.py`
directly shows a real, tenant-scoped, multi-provider in-person terminal
integration already exists and is wired to live API routes:

- `POST /api/eftpos/terminals/{id}/test` — test a configured terminal's
  connection.
- `POST /api/eftpos/transaction` — run a purchase/refund/cancel, recording
  the result (approved/declined/error) against `db.eftpos_transactions`,
  tenant-scoped.
- `POST /api/eftpos/terminals/{id}/settlement`, `GET /api/eftpos/
  transactions`, `GET /api/eftpos/terminals/{id}/test-history`.

`EFTPOSService.PROVIDERS` actually wires up four real protocol attempts —
**Linkly, Tyro, Smartpay** (each a raw TCP socket with its own
request/response framing) and **Windcave** (a real HTTPS POST to its
documented `sec.windcave.com/api/v1/transactions` endpoint) — plus
**`simulator`**, a well-built deterministic fake terminal (documented
test-amount conventions for approve/decline/timeout, a per-terminal
in-memory ledger so refunds match their original purchase) that exists
specifically so the rest of this flow can be tested without needing real
hardware or a vendor account.

**What's genuinely unverified, and why**: none of Linkly's, Tyro's,
Smartpay's or Windcave's wire protocols have been checked against that
vendor's actual certified spec — `backend/tests/inprocess/test_eftpos.py`
and `test_eftpos_test_history.py` only exercise `simulator`, because
verifying the other four needs either real terminal hardware or a live
vendor merchant account, neither available here. That's the real
remaining driver work: get one of these four in front of its actual
terminal/sandbox account and fix whatever the real protocol doesn't
match, or confirm it already does. **Westpac Presto, ANZ Worldline, NAB
Transact, CBA Albert and Square Terminal have no code at all** — no
class, no `PROVIDERS` entry — despite an earlier version of this doc's
own module docstring listing them as supported; that line has been
corrected in `eftpos_service.py` itself.

Hosted/online checkout is separate from all of the above and unaffected:
Stripe (`routes/integrations.py`, `routes/licensing.py`), Coinbase
Commerce (crypto), Square (via the generic `services/connect/` connector
framework) — all server-initiated, none require in-person terminal
hardware.

Windows's own foundation pass (`feat/windows-foundation`) reached a
narrower version of the old conclusion independently, and it's still
accurate for Windows specifically: no terminal adapter is implemented or
certified there, and its cash-order queue (`packages/platform-
core/queue.cjs`) explicitly refuses anything but `paymentMethod: 'cash'`
— card, gift-card/customer-balance and loyalty redemption are rejected
outright by its own field validation, not merely undocumented. See
`OFFLINE_SYNC_ARCHITECTURE.md`'s Windows section. The backend-side
`eftpos_service.py` integration above is platform-agnostic (it's a
server-side socket/HTTP client, not a browser/native plugin), so it's
reachable from any platform's frontend the moment a route calls it —
Windows's gap is specifically that nothing in `apps/windows` calls those
routes yet, not that the backend has no terminal integration to call.

## What's not here: a client-side terminal SDK

No *client-side* payment-terminal SDK (Stripe Terminal's JS SDK, Square's
in-person Reader SDK, or similar, for NFC/card-reader hardware physically
attached to a tablet/phone) is integrated, and
`frontend/src/platform/*/PaymentTerminalService.js` still correctly
reports `'unsupported'` everywhere — per the master directive, "do not
implement an unsupported provider merely to fill the interface," no
specific client SDK was named as a target, so none was built. This is a
different, still-open gap from the backend-side socket/HTTP integration
above: `eftpos_service.py` talks to a terminal *itself* (over the
network, from the server), the way Linkly/Tyro/Smartpay/Windcave terminals
are actually deployed in Australian venues — it's not a stand-in for a
tablet-attached card reader, which would need the client-side SDK this
section describes if a venue ever needs one.
