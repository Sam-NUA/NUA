# NUA Vercel deployment

NUA is deployed as two container services in one Vercel project:

- `frontend`: the React/CRACO SPA served by nginx;
- `backend`: the FastAPI application served by Uvicorn;
- `/api/*`: routed to the backend service;
- all other paths: routed to the frontend service.

This keeps browser API and WebSocket traffic on the same Vercel origin. The
frontend Docker build deliberately leaves `REACT_APP_BACKEND_URL` empty, so
its existing `/api` requests remain relative to that origin.

## Staging prerequisites

Create a Vercel project from `Sam-NUA/NUA` using the repository root. Select
the **Services** framework preset if Vercel does not select it automatically.

Configure these Preview environment variables before the first deployment:

| Variable | Requirement |
| --- | --- |
| `MONGO_URL` | A staging-only MongoDB connection string; never production data. |
| `DB_NAME` | The dedicated staging database name. |
| `JWT_SECRET` | A new high-entropy staging secret. |
| `FRONTEND_URL` | The exact Vercel preview/custom staging origin once assigned. |
| `FORWARDED_ALLOW_IPS` | Set only after Vercel's trusted proxy topology is confirmed; do not use `*` by default. |

Provider credentials such as Stripe, Twilio, SendGrid and AI keys are optional
for the first platform smoke test, but each corresponding integration remains
disabled or degraded until its staging credential is configured.

## Safe first deployment

1. Deploy a Preview environment from a branch; do not alias it to production.
2. Confirm both containers become ready.
3. Check `GET /api/` returns the NUA API metadata.
4. Verify SPA deep links load directly, not only through client navigation.
5. Run login, tenant-isolation, booking, ordering and WebSocket smoke tests.
6. Run the ownership-migration preflight in dry-run mode against staging only.
7. Promote the already-tested Preview deployment rather than rebuilding a
   different production artifact.

## Operational cautions

- Startup seeders are idempotent, but a new staging database must be reviewed
  after its first boot before it is used for acceptance testing.
- NUA contains in-process schedulers and in-memory WebSocket connection maps.
  Before production, verify their behaviour under container scaling and
  restarts. Move scheduled work to Vercel Cron/Queues and shared fan-out state
  if more than one backend instance will run.
- EFTPOS/printer sockets that target a venue LAN cannot be reached directly
  from a cloud container; those integrations require the local POS/edge agent.
- Do not run live-data migrations as part of deployment.

## Cutover rule

The existing Fly.io workflow must not be treated as an active staging path.
Its last deployment failed because `FLY_API_TOKEN` was unset, and both public
Fly endpoints currently return HTTP 502. Disable or replace that workflow only
when the Vercel Preview deployment and smoke tests are green.
