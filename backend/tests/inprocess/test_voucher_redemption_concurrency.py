"""Remediation of the final readiness audit's Medium finding: voucher
redemption was read-then-write (validate against a snapshot, then a
separate later `update_one` with a plain $set), not atomic — two concurrent
redemptions of the same one-time voucher could both pass validation before
either wrote, and both then succeed, double-spending it.

Fixed in routes/commerce_v29.py's redeem_voucher: a bounded optimistic-
concurrency loop using find_one_and_update with a filter pinned to the
exact prior status/redemptionCount/residualValue — a losing concurrent
attempt sees no match and retries against the winner's fresh state.
"""
import time
from concurrent.futures import ThreadPoolExecutor

from tests.inprocess.conftest import req


def _issue(client, headers, *, value, partial=False, max_redemptions=None):
    body = {"label": "Concurrency Test Voucher", "valueType": "amount", "value": value}
    if partial:
        body["partialRedeemable"] = True
    if max_redemptions is not None:
        body["maxRedemptions"] = max_redemptions
    r = req(client, "POST", "/api/vouchers", headers=headers, json=body)
    assert r.status_code == 200, r.text[:200]
    return r.json()


def test_two_concurrent_redemptions_of_a_one_time_voucher_only_one_succeeds(client, owner_headers):
    voucher = _issue(client, owner_headers, value=20)
    code = voucher["code"]

    def _redeem():
        return req(client, "POST", "/api/vouchers/redeem", headers=owner_headers, json={
            "code": code, "amount": 20, "transactionId": f"CONC-TXN-{time.time_ns()}",
        })

    with ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(_redeem)
        f2 = pool.submit(_redeem)
        r1, r2 = f1.result(), f2.result()

    statuses = sorted([r1.status_code, r2.status_code])
    successes = [r for r in (r1, r2) if r.status_code == 200]
    assert len(successes) == 1, (
        f"exactly one concurrent redemption of a one-time voucher must succeed — "
        f"got statuses {statuses}, bodies {[r.text[:150] for r in (r1, r2)]}"
    )
    # The loser must fail cleanly (400 rules-rejected, or 409 concurrent-retry),
    # never a 200 that actually double-spent the voucher.
    loser = r1 if r1.status_code != 200 else r2
    assert loser.status_code in (400, 409), loser.text[:200]

    final = req(client, "GET", f"/api/vouchers/lookup/{code}", headers=owner_headers).json()
    assert final["status"] == "redeemed"
    assert final["redemptionCount"] == 1, (
        f"the voucher must show exactly one redemption, not {final['redemptionCount']}"
    )
    assert len(final.get("redemptions", [])) == 1


def test_concurrent_partial_redemptions_never_overdraw_the_residual(client, owner_headers):
    """A partial-redeemable $50 voucher hit by two concurrent $30 requests
    must never pay out $60 total — the second request must only ever see
    (and be capped to) whatever residual is actually left after the first
    commits, not a stale $50 snapshot."""
    voucher = _issue(client, owner_headers, value=50, partial=True)
    code = voucher["code"]

    def _redeem(amount, txn_suffix):
        return req(client, "POST", "/api/vouchers/redeem", headers=owner_headers, json={
            "code": code, "amount": amount, "transactionId": f"CONC-PARTIAL-{txn_suffix}-{time.time_ns()}",
        })

    with ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(_redeem, 30, "a")
        f2 = pool.submit(_redeem, 30, "b")
        r1, r2 = f1.result(), f2.result()

    applied_total = sum(r.json()["amountApplied"] for r in (r1, r2) if r.status_code == 200)
    assert applied_total <= 50.0 + 1e-6, (
        f"a $50 voucher must never pay out more than $50 total across concurrent redemptions, "
        f"got {applied_total}"
    )

    final = req(client, "GET", f"/api/vouchers/lookup/{code}", headers=owner_headers).json()
    assert final["residualValue"] >= -1e-6
    assert round(50.0 - final["residualValue"], 2) == round(applied_total, 2), (
        "the voucher's own recorded residual must match the sum of what was actually applied"
    )


def test_retrying_the_same_transaction_id_after_a_lost_race_does_not_double_spend(client, owner_headers):
    """A client that legitimately retries (e.g. its first response was lost)
    with the SAME transactionId must be rejected as a duplicate, not treated
    as a fresh redemption — proves the existing duplicate-transactionId
    guard still holds under the new retry-loop structure."""
    voucher = _issue(client, owner_headers, value=10)
    code = voucher["code"]
    txn_id = "CONC-RETRY-SAME-TXN-1"

    first = req(client, "POST", "/api/vouchers/redeem", headers=owner_headers, json={
        "code": code, "amount": 10, "transactionId": txn_id,
    })
    assert first.status_code == 200, first.text[:200]

    retry = req(client, "POST", "/api/vouchers/redeem", headers=owner_headers, json={
        "code": code, "amount": 10, "transactionId": txn_id,
    })
    assert retry.status_code == 409, retry.text[:200]

    final = req(client, "GET", f"/api/vouchers/lookup/{code}", headers=owner_headers).json()
    assert final["redemptionCount"] == 1
