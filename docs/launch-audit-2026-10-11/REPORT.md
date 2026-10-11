# NUA POS launch audit — 11 October 2026 (Melbourne)

## Scope and inventory

Requested base: `codex/owner-access`, fetched at `f150264` (merge of PR #13). Working/review branch: `codex/launch-audit-owner-access`; not based on main. Recent history: f150264, e8b4aaf (PIN recovery UI), 77181c4 (PIN bootstrap/recovery), b6be4b9 (owner access/password recovery), 21418ab (sign-in copy), 1a7fe01 (dependency patches). Open PRs at inventory: #2 and #4–#10. None changed or merged. Earlier uncommitted scheduler-health work remains in a separate worktree and is excluded.

Read README.md, docs/OWNER_ACCESS.md, docs/LAUNCH_FOUNDATION_RUNBOOK.md, CI/deployment workflows, authentication and tenant middleware. No AGENTS.md found. Vercel configuration describes static React web, FastAPI POS and Bookings services. No deployment, infrastructure operation, Railway action, live database migration, credential reset or real payment was performed. The review branch explicitly disables its automatic Vercel Git deployment using `git.deploymentEnabled`; production branches are unaffected. Reference: https://vercel.com/docs/project-configuration/git-configuration .

## Defects fixed and root causes

| Finding | Root cause | Change |
|---|---|---|
| PIN sign-in fails after owner recovery/password change | The separate PIN token issuer omitted `iat`, so password-change revocation treated newly issued tokens as old. | Use the existing access-token issuer; test old-token rejection and new-token `/auth/me` success. |
| PIN bypasses two-factor authentication | PIN and off-roster approval issued access tokens without checking account enrolment or venue 2FA policy. | Fail closed with an email/authenticator sign-in instruction for protected users and approving managers, before writing an override. Existing email 2FA remains the supported completion flow. |
| Sensitive authentication fields in profiles | PIN sign-in and `/auth/me` returned account documents with PIN/TOTP setup fields. | Shared response sanitizer for password sign-in, PIN sign-in and `/auth/me`; preserve internal auth objects and effective permissions. This is not a claim that every staff-administration response was redesigned. |
| Cross-tenant reservation enrichment | Kitchen creation read a reservation using ID alone. | Require the linked reservation to be tenant-owned, even when the caller supplies covers; return 404 before ticket creation otherwise. |
| Scoped read followed by unscoped writes | Product per-row bulk edit/translation and kitchen overnight cleanup discarded tenant predicates in the final write. | Carry the tenant predicate into each write. Duplicate-ID regression checks the actual foreign row stays unchanged. |
| Unowned stock history | Product adjustments inserted history without ownership. | Stamp the authenticated business on both location and global adjustment records. |
| Guest variant data disclosure | Variant listing did not apply the guest product cost/stock/SKU redaction used by the main product endpoint. | Apply the same existing hidden-field list to guest variant responses. |
| Browser dependency advisories | The locked Axios version was 1.18.1, below the patched 1.20.0 range. | Targeted same-major upgrade, lockfile included; no forced framework/toolchain upgrades. |
| Misleading owner setup guidance | README still advertised obsolete shared passwords and a demo 2FA code. | Replace with current create-once/operator-provisioned access guidance. |
| Recovery E2E was a false positive | It asserted that PIN login returned a user but never used the token, missing the revocation failure. | Require `/auth/me` acceptance and actual browser PIN navigation after recovery. No assertion removed or weakened. |

`_insert_seed_user()` remains create-once. No fallback secret/password/PIN was introduced. No tenant filter, permission or test was weakened, skipped or disabled. An existing 2FA account cannot use PIN alone: this is an explicit security restriction, not a new bypass.

## Validation

See VALIDATION.md for command results and final counts. The initial backend full run was **861 passed, 0 failed**, 35,598 warnings, 314.96 seconds. Warnings are mainly existing Python/Pydantic deprecations; this is not warning-clean code. Backend checks used Python 3.12 and the available pinned test environment (pytest 9.1.1, mypy 1.18.2, flake8 7.3.0). GitHub CI uses its configured Python 3.11 environment. The numeric mypy total depends on the installed stub/runtime environment; it is not evidence of eliminating the accepted type debt.

## Five-file tenant-isolation spot check

These five request-handling files were selected before edits. This is a bounded audit, not whole-repository tenant certification. Direct database operations and the relevant delegated helpers were traced.

| File | Scope reviewed | Findings/disposition |
|---|---|---|
| routes/products.py | Guest venue resolution, product/variant list, CRUD, stock adjustment, translation, bulk edits, image storage; stamped CRUD helpers | Fixed final ID-only translation/bulk writes and missing adjustment ownership. Existing list/CRUD/image operations resolve or stamp a business. Also fixed guest variant trade-data exposure. |
| routes/customers.py | Customer CRUD/profile/feedback, credit, wallet and settings; entity_service and wallet_service | Direct route reads/writes are scoped and entity_service reapplies scope. **Open:** wallet_service birthday lookup/issuance, expiry and voucher listing use customerId alone and birthday vouchers lack businessId. Parent customer validation does not make those child queries strictly scoped. Requires voucher ownership reconciliation and a dedicated regression pass; no legacy vouchers were reassigned here. |
| routes/channel_menus.py | Every list, override, bulk price, heat and slow-mover query/aggregation/write/delete | Direct operations have tenant predicates and inserts stamp businessId. **Open:** patch accepts a productId without checking ownership/existence of that referenced product; it writes only the caller's override, but can create invalid references. Heat reads `kds_orders` while the active ticket path writes `kitchen_orders`; heat may incorrectly stay cool. |
| routes/kitchen.py | Ticket list/heat/prep, create/enrichment, status/course/priority mutations, overnight cleanup, docket config | Fixed reservation lookup and overnight final write. Most ticket mutations carry tenant scope. **Launch blocker for multiple businesses:** docket configuration still reads/writes `_id: singleton`, including updatedBy, without businessId. Existing singleton ownership is ambiguous; migration must be reviewed rather than silently assigning it. |
| routes/reservations.py | Reservation CRUD/status/deposit/cancellation, blackout queries, floor plans/tables, waitlist, public tracking; floor_tables and reservation_store | Direct authenticated operations are scoped; business lookup is keyed by the verified record's businessId. Capacity/store helpers preserve scoped writes. **Review required:** public waitlist tracking/stream intentionally look up a capability code globally; confirm code entropy/rate limiting/privacy policy. Customer/table relationships can be supplied by ID and need a consistent foreign-reference rejection policy, even where scoped helper lookups prevent data disclosure. No public capability design was silently changed. |

## Launch-critical code walkthrough

### Owner email/password

Login.jsx → AuthContext.login → POST `/api/auth/login`: normalized email, bcrypt verification and account lockout. Enrolled or policy-required 2FA returns a challenge instead of an access token; the existing challenge UI calls `/auth/2fa/challenge`. Successful completion returns `{user, token}` and cookies; `/auth/me` enforces active membership and password-change token revocation. Browser tests cover good and bad password paths. Actual production credentials and email delivery were not exercised in this audit.

### Owner PIN

Login.jsx → staffMgmtAPI.pinLogin → `/auth/pin-login`: exactly one active PIN match is required. Owner/manager bypass the roster gate, not tenant membership or 2FA. Ordinary staff require an active roster entry or same-business manager approval. The response retains `{user, token}` or `{needsApproval, staffId, staffName}`. Previously the issued token failed `/auth/me` after recovery; the shared issuer fixes that. Protected 2FA accounts now receive 403 with an actionable email sign-in message; Login.jsx displays backend detail. PINs remain short and stored as existing plaintext account fields, globally unique/ambiguity-denied; terminal-bound stronger PIN authentication is future security work. No hardcoded 0311 assignment was made.

### POS selection → sale/payment

POSTerminal loads the scoped catalog, builds modifier/cart lines and discounts, then handleCheckout → createTransactionResilient → POST `/transactions`. Network-only failures enter the offline queue with a client operation ID; server validation errors are not queued. Backend recalculates catalog price, scopes product/customer/loyalty reads, validates splits, writes the sale and applies stock/accounting/loyalty side effects. The card smoke records an externally collected tender; it does **not** prove a physical EFTPOS charge. Hosted Stripe stores sale payload/cashier context, redirects to Checkout and finalizes via verified webhook/status handling in integrations.py. Finalization claims are retryable after timeout.

**Financial launch risks:** transaction insert and later side effects are not one database transaction; point redemption occurs before insert. Payment webhook crash/replay and partial side-effect failures need real-replica/provider fault testing. Some paths catch voucher/recipe/notification errors and continue. Open/custom lines intentionally accept client pricing; modifier and manual-discount permissions deserve explicit owner review. QR confirmation and external card tender are not proof of settlement. Do not call this flow financially certified from the five browser smoke tests.

### Reservation/booking creation

Reservations.jsx validates form and submits reservationsAPI.create with the model's guest/date/time/partySize fields. An optional AI overbooking suggestion can fail open, but the backend booking-rules engine remains authoritative. `/reservations` derives authenticated business context, acquires a business/date capacity lease, validates blackout/capacity/experience/window rules and writes via reservation_store with transactional projection/outbox support. Success returns a Reservation object; rule conflicts return 409 that the UI displays. Public booking has its separate venue-resolution route. The route's optional-user signature does not itself grant a tenant to an anonymous caller; helpers/middleware still matter. Real Mongo capacity/contention proofs remain required in addition to mongomock.

### Owner recovery

OwnerRecovery.jsx initiate → `/auth/owner-recovery/initiate`: configured operator key, constant-time comparison, shared lockout, exact owner email selection and hashed 15-minute token bound to owner ID/current password hash. Complete validates password and optional PIN, atomically consumes the token, rejects duplicate PIN/account changes, writes password/PIN together and invalidates prior sessions/trusted devices/reset links. Blank frontend PIN omits the field and preserves it. Frontend requires four digits while backend accepts 2–4: compatible but intentionally different restrictions. Recovery preserves 2FA, so recovered protected owners still use email/authenticator. Token re-use is rejected. Email recovery additionally depends on verified sender/provider configuration and real delivery, not merely access-options readiness.

## Deliberately untouched / launch risks

- No deployment/merge/live mutation. Do not treat this audit PR as launch approval.
- Ambiguous legacy ownership migration (especially docket settings and wallet vouchers) needs reviewed evidence; never assign all unowned records to the default business.
- 129 frontend tooling/desktop dependency entries remain; see DEPENDENCIES.md and raw audit JSON for every package/advisory. No ignored-advisory expansion. Desktop release is not cleared.
- Existing global PIN namespace, plaintext PIN storage, throttling and trusted-terminal policy need a separate authentication design review.
- Real terminal/printer/cash drawer, card/refund, offline reconnect, email delivery/recovery, concurrent database writes, backup restore and scheduled jobs need environment/provider tests before launch.
- UTC-wall-clock roster checks differ from Melbourne venue time; verify actual shift boundaries and daylight saving behavior.
- Vercel schedulers intentionally run via Cron while health checks inspect local scheduler loops; health can be misleading. The separate unfinished scheduler work was not transplanted into this branch.
- AuthContext on this base removes the token after any `/auth/me` failure, including transient/network errors; later main-branch work is outside this audit base.
- Historical README feature claims include mocked social publishing and unverified external integrations. Code existence is not evidence of provider readiness.
- No dead branch was deleted based only on apparent lack of use. Concrete stale paths found: channel heat's `kds_orders` collection and the old recovery E2E assertion that never exercised the token. No wholesale dependency, bootstrap or UI rewrite was attempted.
