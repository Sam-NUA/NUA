# Vercel staging deployment

This branch prepares NUA for an isolated Vercel staging deployment. It does not authorize production data, production domains, or database migrations.

## Architecture

Vercel should use the repository's Services preset and `vercel.json`:

| Service | Root | Mount path |
|---|---|---|
| Frontend | `frontend` | `/` |
| Backend API | `backend` | `/api/backend` |
| Bookings API | `bookings-api` | `/api/bookings-api` |

The frontend appends `/api` to `REACT_APP_BACKEND_URL`, so set it to `/api/backend`. Browser calls such as `/api/backend/api/auth/login` are then forwarded to the backend as `/api/auth/login`.

## Staging environment variables

Enter secrets directly in Vercel. Do not commit them or paste them into PR comments.

Required:

- `MONGO_URL`: staging-only MongoDB connection string
- `DB_NAME=nua_staging`
- `JWT_SECRET`: a new high-entropy staging secret
- `BOOKINGS_DB_NAME=nua_bookings_staging`
- `BOOKINGS_ADMIN_KEY`: a new high-entropy staging secret
- `REACT_APP_BACKEND_URL=/api/backend`

Optional or deferred:

- `BOOKINGS_MONGO_URL`: omit to reuse `MONGO_URL`
- `REACT_APP_LICENSE_ENFORCEMENT=false` for staging
- `LICENSE_ENFORCEMENT_ENABLED=false` for staging
- `FRONTEND_URL`: set to the assigned staging URL after the first deployment
- `NUA_BOOKINGS_API_URL`: set after the deployment URL is assigned if backend-to-bookings integration is enabled
- `NUA_BOOKINGS_API_KEY`: use the same staging value as `BOOKINGS_ADMIN_KEY` only when that integration is enabled
- `NUA_BOOKINGS_VENUE_ID`: staging venue identifier, if required
- `FORWARDED_ALLOW_IPS`: configure only after Vercel's proxy topology is verified

## Release sequence

1. Create an isolated Vercel project named `nua-staging`.
2. Add staging-only environment variables.
3. Deploy this branch as a Preview deployment; do not promote it.
4. Verify health, login, tenant isolation, bookings, orders, SPA navigation, and WebSocket behavior.
5. Run any ownership migration in dry-run mode only.
6. Merge only after all checks pass.
7. Production promotion, production secrets, live data, and migrations require separate approval.

## Rollback

Do not promote a failed preview. If a later staging deployment regresses, use Vercel's previous known-good deployment or redeploy the last known-good commit. No database rollback is implied by a deployment rollback.
