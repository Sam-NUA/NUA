# Foundation Day runbook — pilot venue go-live

Steps to complete against the pilot venue's staging database before handing it
over, in order. Do not run these procedures against production until the
staging reports and operator sign-off have been reviewed.

## 1. Reconcile legacy tenant ownership

Never assign every unowned legacy document to the default or first business.
The former `/api/business/backfill-tenant` endpoint is retired and returns
`410`; it must not be restored or called from an operator UI.

This is a support-operated, dry-run-first workflow. It requires an owner token
plus the separately managed `SUPPORT_OVERRIDE_KEY`. Start by listing the
explicit collection allowlist:

```
GET /api/admin/ownership-migration/collections
Authorization: Bearer <owner token>
```

For every returned collection, scan one bounded page at a time. Preserve each
report as release evidence and follow `nextCursor` until it is `null`:

```
POST /api/admin/ownership-migration/scan/<collection>?batch_size=500&after_id=<nextCursor>
Authorization: Bearer <owner token>
X-Support-Override: <support override key>
```

The scan writes nothing. Review `resolved`, `quarantined`, and `conflicts`.
Only after the complete scan has been approved may an authorised operator run
the same collection, using the same pagination rules:

```
POST /api/admin/ownership-migration/run/<collection>?batch_size=500&after_id=<nextCursor>
Authorization: Bearer <owner token>
X-Support-Override: <support override key>
```

The migration assigns ownership only when customer and creator evidence agree.
Ambiguous rows remain unowned and are quarantined. Review them with:

```
GET /api/admin/ownership-migration/quarantined/<collection>?after_id=<nextCursor>
Authorization: Bearer <owner token>
X-Support-Override: <support override key>
```

Resolve a quarantined row only after checking an authoritative source record:

```
POST /api/admin/ownership-migration/quarantined/<collection>/<documentKey>/resolve
Authorization: Bearer <owner token>
X-Support-Override: <support override key>
Content-Type: application/json

{"businessId": "<verified business id>", "evidence": "<specific source and review note>"}
```

**Verify:** re-scan every collection after the run. There must be no unexpected
unowned rows, every quarantine must have an explicit disposition, and any
`conflicts` must be investigated before go-live. Never paste the support
override key into tickets, reports, source control, or command history.

## 2. License enforcement — decision: leave OFF for Aug 15

`LICENSE_ENFORCEMENT_ENABLED` stays unset (defaults to `false`).

Why: `LicenseEnforcementMiddleware` only does anything once a
`tenant_licenses` document exists for the tenant (`middleware/license_middleware.py:85`
— no license row means "allow all", regardless of the flag). The Aug 15
launch is one pilot venue that isn't going through subscription billing yet,
so no license row will exist and flipping the flag on would be a pure no-op
today — except for the added per-request DB lookup, and the risk that a
stray `tenant_licenses` row (leftover test data, a manual DB edit) puts the
tenant into a non-`active` state and silently blocks `/api/transactions` —
i.e. breaks checkout — on the one day it must not break.

Turn it on later, deliberately, as part of the real multi-tenant billing
rollout: once there's a tested onboarding flow that creates the license row
on purpose, and a test confirming an `active` license still allows POS
sales end-to-end.

## 3. Purge demo data

Deletes every row the startup seeders created (`seed_demo_customers`,
`seed_alcohol_catalog`) — the 5 sample guests and their generated
reservations/transactions/feedback, plus the starter alcohol catalog
(categories, products, stock units, sell variants). Run this last, after
the pilot venue's real menu and any real customer data have been entered
(purge only removes rows tagged `isDemo: true` at seed time — it can't
touch anything the venue entered themselves).

```
POST /api/business/purge-demo-data
Authorization: Bearer <owner token>
Content-Type: application/json

{"confirm": "PURGE"}
```

Response: `{"purged": {<collection>: <rows deleted>, ...}, "total": N}`.
Missing/wrong `confirm` value returns `400` and deletes nothing — the
explicit token exists so this can't fire from a bare POST or a UI
misclick. Never touches `businesses`, `auth_users` (admin/staff),
`changelog`, or `chart_of_accounts` — none of those are seeder-tagged.

Covered by `backend/tests/inprocess/test_demo_purge.py`.
