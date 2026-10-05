# Standalone Loyalty and Members pilot

## What is implemented

NUA Loyalty is an owner-operated, no-charge 14-day standalone product. It requires
no NUA POS licence or external POS. Merchants can configure their program, terms
and lifetime earned-points tiers; publish enrolment; search/paginate members;
record signed points adjustments with reasons; pause/reactivate membership;
create/edit/archive reward options; fulfil claims or cancel them with a points
refund; export data; and cancel the product independently.

The member portal supports venue-specific signup and password login, explicit
terms acceptance, optional marketing consent (unchecked by default), points and
tier progress, reward claims with references, latest ledger/claim history, JSON
export, password changes, consent changes and server-revoked logout. No welcome
points or discounts are promised or minted automatically. Rewards are supplied
by the merchant in person; claim references are not cash or payment credentials.

This is manual operation: Square sales sync, automatic purchase credit, POS
redemption, imports, referrals, wallet passes, messaging, payment collection,
paid subscriptions and self-service forgotten-password recovery are not included.
Email ownership is not verified yet. Keep registration closed to public acquisition
until verification/recovery, privacy/retention and operational support are ready.
Existing POS Loyalty and its member routes are not migrated into this product.
Booking and Loyalty pilot owners currently use separate accounts/emails. A unified
multi-product dashboard and subscriptions are a later migration, not an implicit
extension of a Booking-only entitlement.

## Entry points and domain testing

| Product | Path on the same preview | Planned domain |
|---|---|---|
| Loyalty management | `/loyalty-app` | `loyalty.nuapos.com.au` |
| Venue membership | `/members/v/<businessId>` | `members.nuapos.com.au/members/v/<businessId>` |
| Booking | `/booking-app` | `booking.nuapos.com.au` |

No DNS changes are included. All three can be tested from the existing Vercel
preview before domain setup. The UI selects Loyalty on `loyalty.nuapos.com.au`
and `members.nuapos.com.au`; members must follow the full venue-specific path,
which identifies the merchant. The root of the members hostname currently shows
the Loyalty sign-in, not a cross-business member directory. Portal links generated
in management use the current origin. Once the members domain is configured,
retain `/members/v/<businessId>` when sharing that domain with customers.

Use the same Vercel project/build for the pilot and add both domains to that project.
Use the DNS records Vercel supplies for that project, not guessed CNAME values.
For same-origin APIs leave `REACT_APP_BACKEND_URL` unset. For split origins use
an explicitly trusted API origin and CORS allowlist. Hostname selection is only a
frontend choice; all authorization is enforced by the API.

Set `LOYALTY_PRODUCT_SIGNUP_ENABLED=true` on an isolated testing deployment only
when ready to create test accounts; default is false. It is a server runtime flag,
not a frontend variable. Do not switch it on globally for public acquisition.
The automated browser harness enables it only against the in-memory test database.

## Integrity and authorization

- New business IDs start `nl_`. Their owners can access dedicated Loyalty routes
  and account authentication, not legacy POS/customer/Booking APIs. Headers cannot
  grant access to another tenant. Legacy public order/booking venue lookup excludes them.
- Staff and member identities are distinct. Member JWTs require an explicit
  audience, business ID, type, expiry and session version, and cannot be used as
  merchant credentials. Member operations derive the member ID from verified auth.
- Password hashes are never returned by the APIs or business/member exports.
  Member tokens live in sessionStorage per business, expire after eight hours,
  and are revoked by logout, password changes and membership status changes.
- Membership IDs are unique by business + normalized email. Terms accepted and
  consent are retained. No marketing message is sent by signup.
- `loyalty_product_members`, `loyalty_product_ledger`,
  `loyalty_product_rewards`, `loyalty_product_redemptions` are tenant scoped.
  Product state lives in `product_accounts`. All are included in durable backup data.
- Points and reward receipts commit together in real Mongo transactions.
  All business mutations touch the product revision, so conflicts with concurrent
  configuration changes/cancellation retry against fresh state across instances.
- Request UUID plus payload fingerprint prevents duplicate adjustments/claims.
  The merchant must still avoid entering one purchase under multiple new request
  IDs; receipt references are recorded but are not automatically reconciled.
- Claims cannot make balances negative. Rewards snapshot their cost and label.
  Cancelling a pending claim refunds once; fulfilled claims cannot be re-used or
  cancelled through this pilot. Points have no automatic expiry in this version.
- Positive adjustments increase lifetime tier progress. Negative corrections and
  reward spending do not lower lifetime progress. Refunds do not earn tier credit.
- Trial expiry/cancellation stops new enrolments, awards and claims, but preserves
  records/exports and fulfilment/refund of pending claims. Other products are unchanged.
- Shared database rate limits protect owner registration and member surfaces.
  Database failure fails closed. No ephemeral function files hold balances or records.

## Verification

Local focused tests: `cd backend && python -m pytest tests/inprocess/test_loyalty_product.py tests/inprocess/test_booking_product.py -q`.
Full regression: `python -m pytest tests/inprocess -q`.
Production build: `cd frontend && CI=false npm run build`.
Browser journey: `npx playwright test e2e/loyalty-product.spec.js`.

The mandatory Mongo transaction CI job runs `backend/tests_real`, including real
Loyalty overspend contention, identical-claim retry, concurrent refund and forced
transaction rollback. In-process tests replace transactions only in test fixtures;
they are not evidence of database atomicity. The browser test uses separate owner
and member browser contexts and a mobile viewport for the member. It exercises
signup, publication, enrolment, award, claim, refund, second claim, fulfilment,
trial cancellation, retained member access and download.

Before customer use: test against the actual configured domain and persistent
staging database; exercise multiple instances/cold starts; verify backup readback
and restore including these four new collections; finish email ownership and
recovery, incident support, and privacy/retention processes. Existing paid-launch
and Booking operational gates still apply.
