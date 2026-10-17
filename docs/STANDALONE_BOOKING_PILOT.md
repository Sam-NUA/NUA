# Standalone Booking pilot

## Scope and status

This branch implements the first product boundary for the approved modular NUA direction.
It is a no-charge, owner-operated Booking pilot, not a paid product launch.
Existing POS accounts are not migrated. Signup is disabled unless the operator sets
`BOOKING_PRODUCT_SIGNUP_ENABLED=true`. Do not enable public acquisition before the launch gates below.

A new owner receives a new `nb_` business, a 14-day Booking trial, and no POS licence.
The venue starts unpublished. The dedicated `/booking-app` workspace provides venue
name/timezone/hours/capacity, guest publication, date-based reservation list, creation,
reservation cancellation, JSON export, and independent trial cancellation.
Guest links use `/book/v/<businessId>` and show confirmation on screen.
There are no deposits, SMS/email reminders, paid subscriptions, Square integration,
staff invitations, individual table assignment, overnight hours or booking amendments
in this pilot. The interface states the main limitations. Bookings use overlapping
90-minute capacity windows and a 60-day booking horizon.

## Implementation

- `product_accounts` holds the immutable business ID, venue configuration and per-product states.
- Signup writes owner, business and product account in one Mongo transaction. A unique
  email index prevents concurrent registrations from claiming the same identity.
- Typed request models reject unknown fields, including caller-selected tenant IDs,
  payment flags or entitlement changes.
- `ProductAccessMiddleware` blocks legacy authenticated staff/POS APIs for signed
  Booking account sessions, independently of the legacy licence-enforcement switch.
- Legacy public venue resolution excludes Booking-only businesses; their guest flow
  goes through the dedicated Booking API, with an entitlement check on every creation.
- Reservation persistence reuses the shared capacity leases and transaction fencing.
  Deterministic Mongo `_id` values deduplicate retries; a payload fingerprint rejects
  reuse of the same request ID for different details.
- Trial expiry makes the account read-only. Cancellation closes the guest page and
  updates only `products.booking`. Read/export and cancellation of existing bookings remain.
- No automatic conversion or paid activation endpoint exists. Billing availability is false.
- API responses do not expose password hashes, webhook credentials or booking fingerprints.

## Running and verification

Backend in-process acceptance tests:

```sh
cd backend
python -m pytest tests/inprocess/test_booking_product.py -q
```

Full compatibility regression: `python -m pytest tests/inprocess -q`.
Frontend production build: `cd frontend && CI=false npm run build`.
Browser acceptance: `cd frontend && npx playwright test e2e/booking-product.spec.js`.
The repository browser harness enables this pilot only against an in-memory test database.
Its transaction replacement is not evidence of real Mongo transaction or multi-instance safety.

## Deployment approach

Stage this branch separately from the existing staging production deployment. Use the
existing API and `/booking-app` first. `booking.nuapos.com.au` selects the dedicated
frontend entry point, but no DNS changes are included or have been made.
Configure DNS using the exact Vercel project target only after staging acceptance.
Configure HTTPS cookies, trusted frontend origin(s), runtime database access and secrets
in the deployment; never put credentials in client build variables.

Mongo must support transactions (replica set/Atlas). Do not replace transactions with
non-atomic fallbacks in deployed environments. Restarted clients need a persistent database.
Keep the signup flag disabled until operational approval for a limited pilot.

## Gates before a customer pilot

1. Run browser acceptance and a real-database concurrent signup/booking test.
2. Test cancellation racing with publication and booking creation, repeated submits,
   lease expiry and cold starts; no overbooking or post-cancellation new commitments.
3. Verify published pages, account isolation and export on the deployed staging URL.
4. Verify durable backup readback and full restore of product accounts and reservations.
5. Finalise consent/privacy/retention terms, email verification and abuse protection.
6. Provide support-assisted account recovery and a documented incident procedure.

## Next increments

1. Booking amendments, table assignment, staff invitations and communication delivery.
2. Product-level Stripe subscription checkout/webhooks, grace policies, exact entitlements,
   replay-safe billing, plan change/cancellation tests, and merchant-owned deposits.
3. Controlled merchant pilot with pricing validation before marketing a paid launch.
4. Loyalty standalone mode, followed by real Square OAuth, mapped imports, refund effects,
   reconciliation and supported redemption. Preserve the boundaries established here.
5. Expand to Insights only after connected source data reconciles correctly.

No claim is made that all 24 proposed commercial packages are production-ready.

## Verification recorded for this change

- Broad in-process compatibility run: 849 passed (initial pilot plus existing suite).
- Final focused product/backup run after lifecycle fencing and backup inclusion: 15 passed.
  Includes cross-tenant denial, duplicate request handling, overlapping capacity,
  expiry/cancellation, entitlement input rejection, cancellation waiting for an in-flight
  booking, and tenant-scoped backup inclusion of product account state.
- Final frontend production build: compiled successfully.
- Real Mongo process startup in this execution environment failed with
  `open: Operation not permitted`; real-database concurrency and restore remain gates.
- Browser acceptance test added to the existing CI harness; result is tracked in the PR.
