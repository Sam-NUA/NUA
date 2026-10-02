# Vercel-only deployment — verified 2026-09-27 UTC

The requested application hosting target is Vercel only. Railway and Fly are
not required accounts for this deployment. Earlier Docker/Fly deployment
instructions are historical alternatives, not the selected target.

Target: `sam-nua/nua-pos-staging`, project
`prj_QhddJTj9toxACgdy613aXKvAcJQ0`, connected to `Sam-NUA/NUA`.

## Configuration prepared

The root `vercel.json` uses the current Services model, not the older
`experimentalServices` format in PR #2. Three services deploy together:

| Path | Service |
| --- | --- |
| `/api/*` | POS FastAPI backend |
| `/bookings-api/*` | Standalone Bookings FastAPI service |
| All remaining paths | React frontend, including client-side navigation |

Frontend requests use the same origin. Python is pinned to the tested 3.12
series. The Bookings wrapper preserves the original API routes under a mount,
including its lifespan and generated documentation.

## Staging verification

Deployment `dpl_CiQyC8pynCqrD3XBX5mC1outjM7y`, commit `7137ab8`,
is Ready (Preview). Its frontend renders the NUA sign-in screen:
https://nua-pos-staging-erm36xo6y-sam-nua.vercel.app/.
Live `/api/ready` returned `{"status":"ready"}` and
`/bookings-api/ready` returned `{"status":"ready","service":"nua-bookings"}`.
The latter verifies a transaction-capable MongoDB topology. These checks do
not establish authenticated user workflows, payment processing, or job delivery.
All CI checks on that commit passed, including real MongoDB transaction tests.

## Remaining launch gates

The free MongoDB Atlas integration was provisioned in Sydney and connected to
the staging project. Its secret is injected as `MONGO_MONGODB_URI`; both services
accept that name, while explicit service-specific URLs retain priority. POS and
Bookings use separate database names on the staging cluster.

`DB_NAME`, `JWT_SECRET`, `BOOKINGS_DB_NAME`, and `BOOKINGS_ADMIN_KEY` are
configured for both Preview and Production in this isolated staging project.
`REPO_SYNC_ENABLED=false`. The integration-provided URI supplies both services;
separate `MONGO_URL` and `BOOKINGS_MONGO_URL` are optional overrides.
The frontend uses same-origin APIs. Configure `FRONTEND_URL` when a specific
cross-origin frontend is needed.
Vercel-only application hosting still needs a managed database; do not put
MongoDB data on ephemeral function storage.

The operator must securely configure `ADMIN_EMAIL` and a unique
`ADMIN_PASSWORD`, then redeploy and sign in. Do not send secrets in chat.
Bootstrap creates the account only when absent; subsequent starts preserve
its password, role and status (`emergent/owner-recovery`, 2026-10-02: fixed
the race where a mismatch used to overwrite the password on every cold
start, and self-heals an owner stored with different `ADMIN_EMAIL` casing
than login's lowercased lookup expects — the two never used to match).
Credential resets must use the account management flow, not changes to the
bootstrap variable. `SEED_DEMO_STAFF` is off by default and must remain off
for deployed environments; local test/demo runners explicitly enable it. No
demo accounts are needed to configure real staff.

If the owner is locked out (wrong/forgotten password) and SendGrid isn't
configured yet so `/auth/forgot-password` can't help, set `OWNER_RECOVERY_KEY`
(a long random secret, separate from `ADMIN_PASSWORD`, never shared outside
Vercel) and use `POST /api/auth/owner-recovery/initiate` (recoveryKey + email)
then `POST /api/auth/owner-recovery/complete` (token + new password). Single
shared lockout bucket after 5 wrong keys, 15-minute single-use token, every
attempt audited to `db.owner_recovery_audit`, and it can only ever reach the
one existing owner account — a key that's valid but names a different email
than the current owner is rejected (409), so it cannot be used to retarget or
duplicate the account. Remove `OWNER_RECOVERY_KEY` from Vercel once access is
restored; it is a standing secret while set.

For native projection, the Bookings URL ends in `/bookings-api`; provision a
partner key, external-authority venue and the explicit native mapping described
in DEPLOYMENT_READINESS.md. Never use production credentials for previews.

The existing delivery outboxes are durable, but their polling loops and the
Ash/coursing schedulers currently run in process. Vercel can retire idle
instances, including containers. Before launch, convert these jobs to bounded
invocations driven by Vercel Queues/Workflows or authenticated Vercel Cron,
with concurrency claims, retries, tenant context and missed-run recovery.
Hobby Cron is limited to daily execution and cannot meet minute-level coursing
or timely delivery requirements. Do not hide this limitation by declaring a
successful build to be a completed product.

Other platform-specific gates: shared real-time fan-out across instances,
distributed rate limiting, durable upload/backup storage, cold-start bootstrap
behaviour, runtime dependency size and live role/tenant/payment tests.

No production promotion is authorized by passing a build alone. Deploy and
inspect a staging candidate first, then verify readiness and these jobs under
instance termination before promotion.

Sources checked: https://vercel.com/docs/services,
https://vercel.com/docs/services/routing,
https://vercel.com/docs/functions/container-images,
https://vercel.com/docs/cron-jobs/usage-and-pricing.
