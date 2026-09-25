# Vercel-only deployment — 2026-09-25

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

## Not yet a launch-ready Vercel deployment

The free MongoDB Atlas integration was provisioned in Sydney and connected to
the staging project. Its secret is injected as `MONGO_MONGODB_URI`; both services
accept that name, while explicit service-specific URLs retain priority. POS and
Bookings use separate database names on the staging cluster.

Configure
`MONGO_URL`, `DB_NAME`, `JWT_SECRET`, `FRONTEND_URL`, bootstrap owner secrets,
`BOOKINGS_MONGO_URL`, `BOOKINGS_DB_NAME`, and `BOOKINGS_ADMIN_KEY` securely.
Use separate staging databases with MongoDB replica-set transaction support.
Vercel-only application hosting still needs a managed database; do not put
MongoDB data on ephemeral function storage.

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
