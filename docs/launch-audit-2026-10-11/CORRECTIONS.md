# Review corrections — 12 October 2026 (Melbourne)

Base: Claude PR #18, `codex/review-launch-audit-2026-10-11`, commit
`c208a2564794ee50691e4461bdce09a9462469c2`. This remains stacked above PR #17
and ultimately `codex/owner-access` (`f150264`), not main.

Branch: `codex/launch-review-corrections`. Its Vercel Git deployment is disabled
in the first published tree. Review only: no merge, deployment, Railway action,
production database access, credential changes or provider payments.

## Findings and corrections

### PIN attempts shared across different guesses

Root cause: the new lockout in PR #18 keyed failures by the guessed PIN, so
trying different values never exhausted a common attempt budget.

The existing Mongo-backed rate limiter now enforces 10 requests per 60-second
fixed window per network client across both `/api/auth/pin-login` and its
approval endpoint. Guess values, tenant headers and forwarded headers cannot
select another bucket. Existing per-PIN checks and all 2FA, role and tenant
checks remain. The limiter fails closed if its shared store is unavailable.

Regression: ten different guesses, alternating endpoints and spoofing headers,
exhaust one bucket; the eleventh is rejected with Retry-After; a later window
admits another attempt. Existing SharedRuntime coverage verifies the underlying
cross-instance counter. This limits one source, not a distributed attack.
Shared venue networks also share this budget; email/2FA sign-in remains available.

### Legacy docket inspection requires support authorization

Root cause: the new legacy report returned the unowned singleton, including
`updatedBy`, to any business owner or manager. A venue role is not evidence of
ownership of this deployment-wide legacy document.

Inspection now requires an owner session plus the existing separately configured
`X-Support-Override` secret gate used by ownership migration. Missing, incorrect,
or unconfigured support credentials fail closed. No row is assigned, migrated,
deleted or copied. Normal tenant-owned docket settings continue to work.

Regressions cover owners from two different venues denied without support,
incorrect/missing configuration, authorized support inspection, and the existing
non-owner rejection and independent tenant settings tests.

### Points and sale commit together

Root cause: refunding on every sale-insert exception assumes that a failed
response means a failed write. A write can commit before its acknowledgement is
lost. The workaround could therefore refund points for an existing discounted
sale. It also did not cover earlier split-guest failures.

`services/pos_sale_store.py` commits the sale, all customer point debits, and
all redemption ledger records in one MongoDB transaction, using snapshot reads
and majority writes. Every customer access retains tenant/quarantine filters,
positive balance and fraud-lock checks. A failure rolls back all participating
writes; there is no unconditional compensation. The driver handles retryable
transaction and uncertain-commit errors. Transactions require a replica set or
transaction-capable MongoDB topology; there is no standalone fallback.

`clientOpId` replays return the existing scoped sale without another debit.
A failed duplicate insert aborts its transaction before reading the winner.
Clients must retain the same operation ID when retrying; the POS offline queue
already generates it before the first attempt. The API's existing optional-ID
contract is unchanged: unrelated requests without an operation ID cannot be
recognized as retries.

The old race test inserted its winner before the request and accidentally took
the early replay return. It now hides the winner until the insert is attempted
and asserts that the insert was actually called. Additional HTTP tests cover a
lost response after commit and a later split guest failing after an earlier
guest's debit. The in-process transaction double explicitly models rollback;
it is not evidence of MongoDB atomicity.

Six new real-replica-set cases cover same-operation concurrency, distinct-sale
balance contention, missing and locked split guests, failure after an actual
in-transaction debit, and response loss after a real commit followed by replay.
They run in the existing mandatory MongoDB workflow, alongside the original
reservation/outbox proofs; none are skipped or weakened.

### Cron health reflects outcomes

Root cause: `claimedAt` records a start, even when work then fails. Missing
history returned unknown, which overall health treated as successful. Some
workers also swallowed partial failures before returning.

All four Cron entry points now record running/succeeded/failed states and
separate success/failure timestamps. Completion writes are fenced by the claim
owner token, so an older invocation cannot overwrite a newer invocation's
outcome. Stored errors contain the exception class, not provider error text.
Hourly worker partial failures and failed automatic course fires are surfaced
as failed runs. A failed restore drill is also a failed Cron run.

The existing hourly/coursing health checks now require recent successful
completion, reject the latest failed run, detect expired running claims, and
mark missing, malformed or unavailable history as degraded. The configured
75-minute hourly and 5-minute coursing tolerances remain. Local resident-loop
checks remain for non-Vercel deployments.

Regressions cover missing history, claim-only history, failure after earlier
success, stale/stalled jobs, malformed timestamps, success/failure/recovery,
old-owner fencing, partial hourly work, and failed course firing.

Completion telemetry for booking-sync/backup is stored too. The two scheduler
checks on `/api/health` do not certify booking projection delivery, provider
acceptance or backup restore correctness; those require their own result
inspection. Until each monitored job succeeds after rollout, health correctly
reports missing completion instead of inventing a successful historical run.

## Validation evidence

The following completed locally before publication:

| Check | Result |
| --- | --- |
| Full backend after security changes | 904 passed, 0 failed; 36,930 warnings; 327.54s |
| Full backend after points changes | 906 passed, 0 failed; 36,990 warnings; 318.13s |
| Bookings service | 35 passed, 0 failed; 127 warnings; 0.78s |
| Production frontend build | Compiled successfully, zero compiler errors |
| Configured flake8 | Exit 0, no findings |
| Final type differential | 290 findings vs unchanged baseline 814; no new error categories |

The final full backend run, Playwright and real-MongoDB CI results are recorded
in the accompanying PR description against the published commit after they
finish. That section is the final verification record; this file is the
publication-time snapshot, not a claim that pending checks have passed.

No test, baseline, security check or permission was disabled or widened. Test
expectations that previously declared unobserved Cron jobs healthy were changed
to enforce the corrected contract. Dependencies are unchanged from PR #18.
The 129 npm tooling/desktop advisory entries from the previous audit remain;
this change does not reclassify them as harmless or claim they were upgraded.

## Remaining launch boundaries

These four review findings are addressed in code, subject to final CI. This is
not a claim that the whole sale pipeline is transactional: inventory, earned
points, voucher consumption, accounting and provider payment effects still
need durable reconciliation/fault-injection work. A process failure after sale
commit may leave those later effects incomplete; the debit/ledger/sale boundary
introduced here does not hide or solve that separate existing risk.

Global PIN namespace/plaintext migration, provider sandbox settlement/refund
proof, real terminal/printer/cash drawer checks, offline recovery, email delivery,
backup restoration and actual deployed Cron execution remain separate gates.
No production migration or test was run. Owner bootstrap remains create-once.
