# Deployment and recovery contract

This branch is a tested release candidate, not a verified production deployment.
The selected hosting target is now Vercel only; see VERCEL_ONLY.md for the
current configuration and migration gates. The existing Docker/Fly path is a
previously tested alternative, not a required account. In-process schedulers
and workers still need durable Vercel execution before launch. A successful
build alone does not establish runtime readiness.

## Required environment

| Service | Required setup |
|---|---|
| POS backend | `MONGO_URL` for a replica set or sharded MongoDB, `DB_NAME`, unique `JWT_SECRET`, approved `FRONTEND_URL`, bootstrap owner credentials via secrets |
| Bookings | Separate database, `BOOKINGS_MONGO_URL`, `BOOKINGS_DB_NAME`, unique `BOOKINGS_ADMIN_KEY`; resident worker runs in lifespan |
| Native projection | `NUA_BOOKINGS_API_URL`, `NUA_BOOKINGS_API_KEY`, `NUA_BOOKINGS_VENUE_ID`, `NUA_BOOKINGS_BUSINESS_ID`; one explicit mapping per deployment; remote venue `authority: external` |
| Webhooks | `BOOKINGS_WEBHOOK_ALLOWED_HOSTS`: comma-separated exact HTTPS hostnames; partner signing secret securely installed at receiver |
| Edge trust | `FORWARDED_ALLOW_IPS` restricted to actual proxy peers; no direct path around proxy |
| Providers | Payment sandbox credentials and supported checkout dependency; Social publication still requires real provider adapter and OAuth account |

Never reuse production databases or payment accounts for CI. Real MongoDB tests
create and drop only random isolated test databases. Compose now initializes a
single-node replica set; production needs managed redundancy, TLS, credentials,
backups and restore evidence.

## Release order

1. Back up and restore to an isolated environment. Record recovery duration and
   reconcile counts before a live migration.
2. Verify staging database transaction support and permissions.
3. In `bookings-api`, run `python scripts/migrate_booking_times.py VENUE_ID` for
   each existing venue. Resolve ambiguous legacy times explicitly. After review,
   add `--apply`. Each venue migrates atomically. Noncanonical active bookings
   block new allocation until migration completes.
4. Deploy Bookings first. `/ready` must return 200, not just `/health`.
5. Create an external-authority venue for native projection. It rejects local
   confirmations and availability sales. Existing venues are not auto-converted.
6. Deploy POS; `/api/ready` must return 200; run login, role/tenant, booking, checkout and receiver smoke flows
   through the actual edge using sandbox providers. Restart a process mid-delivery.
7. Inspect `GET /api/booking-sync` as owner/manager and
   `GET /admin/webhook-deliveries?partner_id=...` as platform operator. Explicit
   retries: `POST /api/booking-sync/{source_id}/retry` and
   `POST /admin/webhook-deliveries/{event_id}/retry`.
8. Promote only after those checks pass. Fly deployments depend on the mandatory
   real-Mongo transaction workflow.

## Webhook receiver contract

`X-NUA-Signature` is `sha256=` plus HMAC-SHA256 hex over
`X-NUA-Timestamp + "." + raw_request_body`, using the UTF-8 signing secret.
Compare in constant time; reject timestamps outside five minutes; durably dedupe
`X-NUA-Event-Id` before side effects. Acknowledge only after durable acceptance.
Delivery is at least once and can arrive out of order. Refetch authoritative
booking state rather than blindly applying event arrivals.

Provisioning returns the signing secret. Rotation endpoint:
`POST /admin/partners/{partner_id}/rotate-webhook-secret`. Listings omit secrets.
Rotation affects retries immediately; coordinate receiver rotation before replay.
Only approved hosts are contacted; redirects are disabled. Enforce egress rules
against internal IP ranges too: hostname approval alone is not DNS pinning.

## Recovery and remaining gates

Preserve outbox records and tombstones. Concurrent native edits invalidate old
claims; remote versions reject stale deliveries. Tombstones remove guest fields.
Delivery metadata is not a full audit journal; retention needs configuration.

Rolling back across UTC migration to code comparing naive local strings is
unsafe. Freeze confirmations and reconcile or restore a verified snapshot first.
Reverting code cannot undo migrated data or external effects.

Release evidence still required: exact committed CI, selected hosting target,
real environment secrets, deployed two-tenant/role tests, payment sandbox proof,
backup restore, edge trust, sustained workers and browser/device smoke. Pulse,
Crew, entitlement expansion, external POS adapters and other architecture backlog
items remain separate unfinished workstreams; booking reliability does not
complete the entire product roadmap.
