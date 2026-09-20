# Ash tool-execution safety — remaining work

Tracks progress against P0.5 of the Trust Release directive ("Complete Ash
safety") against the gaps a read-only exploration found in
`services/nua_tools.py` and its call sites before this pass.

## Fixed in this pass

| Gap | Fix |
|---|---|
| No global kill switch | `nua_tools.get_kill_switch()`/`set_kill_switch()`, backed by `db.settings` (key `ash_kill_switch`). Enforced inside `execute_tool()` — the single funnel the chat agent, planner, and direct API all route through — and separately inside `routes/approvals.py`'s `_execute_action()`, which bypasses `execute_tool()` by design (an approval already represents a human sign-off) and so needed its own check. Owner-only (`POST /api/nua/kill-switch`, `require_owner`), every toggle audited. |
| High/critical-risk tools could be set to auto | Two layers: `PUT /tools/{name}/permission` now rejects `auto` for `risk in (high, critical)` with a 400 (write-time), and `resolve_permission()` itself refuses to return `auto` for those tools regardless of what's stored in `db.ash_tool_config` (read-time floor — holds even if bad data gets in some other way). `nua_trust.promote()` already had the equivalent check for the trust-ladder path; this closes the same gap for the manual permission-toggle path. |
| Blocked/rejected attempts weren't audited | `execute_tool()` now logs an `action="blocked"` audit event for: unknown tool, kill-switch-engaged, and disabled-by-policy. The persona-guard block in `nua_agent.py` (a tool outside the active persona's remit) is now audited too. Approval-execute-path blocks (kill switch / since-disabled, see below) are also audited. |
| No idempotency protection | `execute_tool()` takes an optional `idempotency_key`; when supplied, a duplicate/replayed/racing call with the same key returns the first call's result instead of re-running a mutating tool (via `db.ash_tool_idempotency`, claimed atomically with `find_one_and_update`, with a short poll for a concurrent in-flight duplicate). Wired through: direct API (`POST /tools/{name}/execute` accepts `idempotencyKey` in the body), the chat agent (derived from `session_id:turn:tool`), and the planner (`plan_id:stepIndex:tool`). |
| Approval-execute path bypassed every check in `execute_tool()` | `routes/approvals.py`'s `_execute_action()` now re-checks the kill switch and `resolve_permission()` immediately before calling `tool.execute()` — closes the specific gap where an approval queued before a tool was disabled (or before the kill switch was engaged) could still run once approved, because approving never re-validated either. |
| Only 1 of 23 tools had a rollback function | Added rollback for the 7 action types the directive names explicitly: `add_wallet_credit` (compensating negative ledger entry), `mark_waste` (restores stock, flags the waste record reversed), `mark_dish_86` (restores prior 86 state — see the schema-bug note below), `upgrade_customer_tier` (restores prior tier), `create_purchase_order` (soft-cancels), `create_promotion` (deactivates), `create_staff_task` (soft-cancels). All preserve the original record (no deletes) so the audit trail still shows what happened and that it was undone. |

## A functional bug found and fixed along the way

`_tx_mark_dish_86` (this file) and `services/rules_engine.py`'s
`_action_mark_dish_86` (the rules-engine automation with the same job) were
both writing `is86ed`/`eightySixReason` to the product document. The actual
schema (`models/product.py`) has always used `eightySixed`/`eightySixedAt`/
`eightySixedBy` — nothing anywhere (POS, kitchen display, online ordering,
the low-stock/OOS endpoints) has ever read `is86ed`. Both "mark dish 86'd"
paths — Ash's tool and the rules engine's automated action — have therefore
never actually 86'd anything visible anywhere in the app; they silently
wrote an orphan field and reported success. Fixed both to use the real
field names; `_tx_mark_dish_86` now also captures the prior state so its
new rollback function can restore it correctly.

Full backend suite re-verified green after every change above
(`python -m pytest tests/inprocess -q` — 485 passed, 0 failed).

## Deliberately out of scope for this pass

- **Rollback for the remaining ~15 tools** (`issue_voucher`, `cancel_reservation`,
  `dismiss_insight`, `approve_pending_approval`/`reject_pending_approval`,
  `add_customer_note`, and every read-only/communications tool). Most of the
  communications tools (`send_customer_sms`, `send_customer_email`,
  `call_customer`) are irreversible by nature — there's no "unsend". The
  clearest remaining candidates for a future pass are `issue_voucher`
  (deactivate the voucher) and `cancel_reservation` (restore prior status) —
  both have a natural, safe compensating action and weren't in the
  directive's explicit list of seven.
- **True concurrent-execution race testing.** The added idempotency claim
  (`find_one_and_update` + short poll) is exercised for the sequential
  retry/replay case in `test_ash_safety_controls.py`, but the in-process
  test harness runs one request at a time against a single event loop, so a
  genuine two-thread race against the same idempotency key isn't exercised
  by an automated test here — only reasoned about at the code level.
- **Scheduler-triggered tool execution guardrails.** `services/nua_scheduler.py`
  currently only generates read-only insights/digests — it never calls
  `execute_tool()` — so there's nothing to guard yet. If a future change has
  the scheduler invoke Ash tools autonomously, it will go through the same
  `execute_tool()` funnel as every other path and inherit the kill switch,
  risk floor, and idempotency support already in place — but this hasn't
  been exercised by a test because the code path doesn't exist yet.
- **Manager-level approval of high-risk actions.** `POST /approvals/{id}/approve`
  is gated `require_owner_or_manager`, so a manager (not just the owner) can
  approve a queued `add_wallet_credit` or `create_purchase_order`. This
  wasn't changed — approving a specific, already-reviewed action is a
  different trust decision than the kill switch or the auto-execute floor
  (which this pass restricted to owner-only / disallowed-outright
  respectively), and the directive didn't call this out specifically. Flagging
  it here as a design question rather than a bug: worth an explicit decision
  on whether high-risk approvals should be owner-only too.
