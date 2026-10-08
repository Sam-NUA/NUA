# NUA POS staging reliability verification

Target: Vercel project `sam-nua/nua-pos-staging`.
Branch: `codex/staging-reliability`, stacked on PR #7 commit
`6e8a5e278dec0fea9964155253daae6d6f891c98`.

## Live findings

- The project dashboard shows the **Hobby** team plan. Every-minute cron and
  hourly cron require **Pro or Enterprise**. Hobby accepts daily schedules;
  incompatible expressions fail deployment, rather than silently slowing down.
- Vercel Cron schedules execute only for **Production** deployments. A project
  named "staging" can use Production deployment mode with staging databases;
  an ordinary Preview deployment does not run scheduled cron jobs.
- No plan upgrade, credential change, or new storage connection was performed.
- The stable branch URL is
  `https://nua-pos-staging-git-codex-vercel-only-sam-nua.vercel.app`.
  Its `/api/ready` returned HTTP 500 `FUNCTION_INVOCATION_FAILED` on October 2.
  Runtime logs show `KeyError: MONGO_URL`. The dashboard points to old commit
  `78436e9`, before the existing Atlas environment-alias fix. A successful build
  marked Ready is not proof that this runtime is healthy.
- Owner-recovery deployment `5wyxAtzRCrhkaLYmocE1N91P44TA` failed dependency
  resolution: `emergentintegrations==0.2.2` is not in the public registry.
  This branch restores the known baseline requirements, keeps `sentinels`, and
  adds the official `vercel==0.11.4` Python SDK. Optional Emergent-specific
  integrations still require an independently deployable adapter/package;
  removing a bad freeze entry does not prove those integrations work.
- The CLI health smoke ran against the real branch URL: all three checks
  failed because deployment protection redirected to Vercel login (HTML), not
  JSON API readiness. The browser session could inspect the earlier runtime
  500; the CLI is not authenticated to Vercel.
- Full authenticated role/tenant/payment smoke testing has **not** passed on
  Vercel. No live cold-start/multi-instance placement proof is claimed.

Official references checked October 2, 2026:
- https://vercel.com/docs/cron-jobs/usage-and-pricing
- https://vercel.com/docs/cron-jobs/manage-cron-jobs
- https://vercel.com/docs/functions/websockets
- https://vercel.com/docs/vercel-blob/private-storage

## Shared coordination implemented

`SharedRuntime` uses Mongo atomic updates and its unique `_id` index for a
shared fixed-window counter. Limit decisions survive worker restarts and new
instances. Client-supplied `X-Tenant-Id` cannot create fresh authenticated
buckets. A storage outage fails closed with 503; 429 includes Retry-After.
TTL indexes control storage growth. Fixed windows can admit two windows' worth
of traffic around a boundary; this is not a rolling-window limiter.

The dashboard/KDS/floor-plan hook reads a tenant-scoped, bounded Mongo event
feed every five seconds, using normal HTTP requests and existing token refresh.
There are no per-instance subscriptions to lose on cold start. Atomic append
order, opaque cursors, and a reset signal handle reconnect/overflow. Clients
refresh authoritative state when resetting; floor plans now also reconcile
on a 30-second timer. Up to 100 events per tenant are retained temporarily.
This is an invalidation feed, not a durable transaction ledger.

Legacy WebSocket routes remain for compatibility. Their local push fan-out is
not claimed to be cross-instance. Split-bill guest/staff screens already poll
Mongo-backed status every 4/3 seconds; low-latency cross-instance split socket
fan-out remains outside the proof. Tenant-less staff sockets no longer receive
other venues' events. Slow local sends have a timeout.

Booking-sync cron releases are fenced by an invocation token, preventing an
expired invocation from releasing its successor's lease. Outbox delivery still
uses its existing per-message leases/idempotency; the cron lock is not the
financial exactly-once mechanism.

## Durable uploads and backups

The audit found **product images already stored in MongoDB**, not function
storage. They remain durable there, now stamped/scoped by business and included
in backup archives. Untagged legacy images are deliberately not visible to all
tenants: an operator must assign each legacy record to its verified owner
before it appears again. Do not bulk-assign all legacy rows to one tenant.

The only runtime file write found is temporary audio for one transcription
request, removed in `finally`. It is intentionally not retained. No persistent
upload path depends on that file surviving an invocation.

Backups previously existed only as in-memory/downloaded archives; the automatic
restore drill discarded its archive. The scheduled drill now writes to a
**private Vercel Blob store**, reads the object back without cache, verifies
SHA-256, then restores those retrieved bytes to a scratch database. Restore
counts are compared with the archive manifest, avoiding false failures from
concurrent writes to the live database. Metadata records are marked verified
only after the independent Blob read passes. No filesystem fallback exists.

Owner API additions:
- POST `/api/ops/backups`: retain a tenant-scoped archive.
- GET `/api/ops/backups`: list that tenant's retained metadata.
- GET `/api/ops/backups/{id}`: authorized download with checksum validation.

Internal whole-deployment backups are not exposed to venue owners. The Blob
store also retains objects independently of Mongo metadata, using dated paths
under `nua-backups/`; an operator can recover them from the Vercel store if the
primary database is lost. Store access must remain private. No automatic
retention deletion is enabled; storage growth must be monitored. Exports are
still assembled in memory, are not a transaction-consistent full database
snapshot, and need a streaming/provider-snapshot strategy before large data
volumes. Mongo/Blob live recovery has not been verified without store access.

## Verification and continuation

Completed before publishing:
- Real MongoDB 7, five separate processes: 100 rate-limit attempts, exactly 25
  allowed; a new process could not reset the exhausted bucket.
- 50 distinct cross-process events; tenant isolation, cursor replay, window
  rollover, overflow/reset behavior passed.
- New private-storage tests cover read-back verification, corruption rejection,
  absent credentials, tenant-scoped reads, and persisted image inclusion.
- Frontend production build and backend lint passed.
- Type gate passed at 814 existing errors, baseline 814, no new error codes.
- Full backend run: 843 passed, one auth-sweep harness failure caused by the
  intended new shared limit. The sweep was changed to clear test counters per
  case so auth is still exercised directly. The focused rerun passed all
  69 auth, cron, shared-runtime and durable-storage checks.

The real-Mongo proof is repeatable and wired into the transaction CI workflow:

```sh
TEST_MONGO_URL=mongodb://127.0.0.1:27018/?replicaSet=nua-test \
  python scripts/verify_shared_runtime.py
```

Deployment gates, in order:
1. Authorize/complete Pro upgrade for `sam-nua` to retain the requested minute
   cadence. Do not deploy the current cron array to Hobby expecting it to run.
2. Connect a private Vercel Blob store to the staging project and inject
   `BLOB_READ_WRITE_TOKEN` for the chosen deployment environment. Keep staging
   and production stores separate. Set `CRON_SECRET` securely as well.
3. Deploy the reviewed PR chain's latest commit, verify its actual SHA and the
   Atlas-compatible configuration, and use staging DBs in Production mode if
   testing Vercel Cron. Do not promote the old `78436e9` deployment again.
4. Run read-only readiness, then securely provision smoke credentials. Never
   put passwords, tokens, Mongo URIs, or provider keys into chat/PR logs.

```sh
SMOKE_BASE_URL=https://<verified-staging-deployment> \
  python scripts/smoke_test_live_edge.py --health-only
```

For protected deployments, securely supply the project-scoped automation
secret as `SMOKE_VERCEL_BYPASS_SECRET`; the script sends it only as a header and
does not follow redirects. Do not disable deployment protection for testing.

Full smoke mode uses `SMOKE_OWNER_EMAIL`, `SMOKE_OWNER_PASSWORD`,
`SMOKE_MONGO_URL`, and `SMOKE_DB_NAME`. Verify that Stripe uses a test key before
setting `SMOKE_STRIPE_SANDBOX_CONFIRMED=1`. The script generates unique test
passwords and cleans up its records in `finally`; skipped tenant/payment
coverage fails the release gate. A sandbox checkout session is not proof of
payment completion/webhook settlement; those still require a sandbox end-to-end
payment flow.

5. Verify the same stored backup from a later deployment, download and restore
   it, and inspect cron history. Use concurrent authenticated event reads/writes
   after an idle period and correlate Vercel invocation logs to prove more than
   one real function instance. If only one instance appears, report that result
   as inconclusive rather than treating load alone as multi-instance proof.
