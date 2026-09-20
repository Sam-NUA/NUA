"""services/wallet_service.py's redeem_wallet_voucher — called from every
POS checkout that applies a wallet-voucher discount (routes/transactions.py,
right after the sale itself is recorded) — used a compare-and-swap filter
pinned only to `status`, not `residualValue`/`redemptionCount`: the same
lost-update race already fixed in routes/commerce_v29.py's redeem_voucher
(see test_voucher_redemption_concurrency.py), just reachable from this
sibling entry point too. Two concurrent checkouts applying the same
partial-redeemable voucher could both read the same stale residual, both
compute a new residual from it, and both "succeed" — but only one write's
effect actually survives, silently granting more discount than the voucher
was ever worth while the voucher's own ledger shows less than that consumed.

Found during the Trust Release final readiness audit (the audit report
mislabeled this function "redeem_voucher_line" and called it dead code —
independently verified false: it's called live from
routes/transactions.py:341-344 in every POS checkout with a wallet-voucher
discount).

mongomock-motor's operations resolve too fast, with no genuine internal
suspend point, for wall-clock thread timing to reliably force two calls
into the same read-then-write window (the same limitation already found
this session testing services/booking_rules_engine.py's capacity_lock).
So instead of racing real threads and hoping, this deterministically forces
the exact interleave that used to be unsafe: swap services.wallet_service's
own module-level `db` reference for a thin proxy whose `.vouchers.find_one`
holds each caller at an asyncio.Event until BOTH concurrent calls have
completed their read — then run them concurrently with asyncio.gather on
the SAME event loop. That's the literal race window the fix's CAS filter
has to survive; everything else passes straight through to the real
collection.
"""
import asyncio

from database import db
import services.wallet_service as wallet_service


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _insert_voucher(voucher_id, **fields):
    doc = {
        "id": voucher_id, "code": voucher_id, "valueType": "amount",
        "redemptionCount": 0, "status": "active", "businessId": "default",
        **fields,
    }
    _run(db.vouchers.insert_one(doc))


class _GatedVouchers:
    """Proxies the real db.vouchers collection, except find_one for our
    target voucher_id blocks until a second caller has also reached it."""

    def __init__(self, real_vouchers, voucher_id, reached, release):
        self._real = real_vouchers
        self._voucher_id = voucher_id
        self._reached = reached
        self._release = release

    async def find_one(self, *args, **kwargs):
        result = await self._real.find_one(*args, **kwargs)
        if args and args[0].get("id") == self._voucher_id:
            self._reached.append(1)
            if len(self._reached) >= 2:
                self._release.set()
            else:
                await self._release.wait()
        return result

    def __getattr__(self, name):
        return getattr(self._real, name)


class _GatedDB:
    def __init__(self, real_db, voucher_id, reached, release):
        self._real_db = real_db
        self._voucher_id = voucher_id
        self._reached = reached
        self._release = release

    @property
    def vouchers(self):
        return _GatedVouchers(self._real_db.vouchers, self._voucher_id, self._reached, self._release)

    def __getattr__(self, name):
        return getattr(self._real_db, name)


async def _redeem_both_after_both_have_read(voucher_id, amount_a, amount_b):
    """Runs the two redemptions concurrently on this event loop, forcing
    both calls' CAS read to complete before either call's CAS write can
    proceed — the exact interleave a lost-update bug needs, and a correct
    CAS filter must reject the loser under."""
    real_db = wallet_service.db
    wallet_service.db = _GatedDB(real_db, voucher_id, reached=[], release=asyncio.Event())
    try:
        return await asyncio.gather(
            wallet_service.redeem_wallet_voucher(voucher_id, "wallet-conc-txn-a", amount_a),
            wallet_service.redeem_wallet_voucher(voucher_id, "wallet-conc-txn-b", amount_b),
        )
    finally:
        wallet_service.db = real_db


def test_two_concurrent_partial_redemptions_of_a_wallet_voucher_never_overdraw_the_residual():
    """The voucher starts already status="partial" (as it would be after any
    prior partial redemption), not "active" — this matters: this codebase's
    CAS write always changes `status` on a plain "active"->"partial"
    transition, so a filter pinned only to `status` would incidentally still
    catch a race starting from "active" (the loser's stale "active" no
    longer matches once the winner has already flipped it to "partial").
    Starting from "partial" removes that incidental protection: two
    concurrent partial redemptions of an already-partial voucher both leave
    `status` as "partial" no matter which one *should* have lost, so
    `status` alone can never distinguish winner from loser — only pinning
    `residualValue` (what this fix actually pins) closes the race."""
    voucher_id = "WALLET-CONC-TEST-1"
    _insert_voucher(voucher_id, value=100.0, residualValue=90.0, status="partial",
                     partialRedeemable=True, usageType="multi_use")
    try:
        applied_a, applied_b = _run(_redeem_both_after_both_have_read(voucher_id, 30.0, 30.0))

        total_applied = applied_a + applied_b
        assert total_applied <= 90.0 + 1e-6, (
            f"a voucher with a $90 residual must never grant more than $90 of discount across "
            f"concurrent redemptions that both read before either wrote, got "
            f"{applied_a} + {applied_b} = {total_applied}"
        )

        final = _run(db.vouchers.find_one({"id": voucher_id}, {"_id": 0}))
        assert final["residualValue"] >= -1e-6
        assert round(90.0 - final["residualValue"], 2) == round(total_applied, 2), (
            "the voucher's own recorded residual must match the sum of what was actually "
            "applied — a lost update here means the voucher granted more discount than it "
            "ever actually debited from its own ledger"
        )
    finally:
        _run(db.vouchers.delete_many({"id": voucher_id}))


def test_a_one_time_wallet_voucher_cannot_be_redeemed_twice_concurrently():
    voucher_id = "WALLET-CONC-TEST-2"
    _insert_voucher(voucher_id, value=20.0, residualValue=0.0, partialRedeemable=False, usageType="one_time")
    try:
        applied_a, applied_b = _run(_redeem_both_after_both_have_read(voucher_id, 20.0, 20.0))

        successes = [a for a in (applied_a, applied_b) if a > 0]
        assert len(successes) == 1, (
            f"exactly one concurrent redemption of a one-time voucher — read before either wrote — "
            f"must actually apply, got {applied_a} and {applied_b}"
        )
        assert sum(successes) == 20.0

        final = _run(db.vouchers.find_one({"id": voucher_id}, {"_id": 0}))
        assert final["status"] == "redeemed"
        assert final["redemptionCount"] == 1, (
            f"redemptionCount must reflect exactly one successful redemption, got {final['redemptionCount']}"
        )
    finally:
        _run(db.vouchers.delete_many({"id": voucher_id}))
