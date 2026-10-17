# Launch software closure — 17 October 2026

Status: implementation complete, final local and native CI verification in progress.
This report is updated with final results before handover. No merge, deployment,
Railway operation, live payment or production data/configuration change is authorized.

## Source and integration path

Started from `fix/native-session-durability` at
`1df99be16c5c214d42ff86e87e7da81918ade53f` (PR #31), whose application
commit `c95e164f18a9dd61d3bd4c35fd547c641f46915b` passed its five workflows.
The working branch is `fix/launch-software-gaps`, stacked on that branch rather
than `main`. Existing worktrees and owner seed semantics were preserved.
Read README, OWNER_ACCESS, LAUNCH_FOUNDATION_RUNBOOK, and both original
multiplatform directives before selecting gaps. The old remaining-work checklist
predates the Android/iOS/Windows milestones; those are not undone or reimplemented.

Reviewed and integrated the backend consistency source from PR #26 (`c4d9429`):
stock-transfer atomicity, appointment locking/ownership references, channel-menu
slow-mover timestamp compatibility and durable consistency helpers. This PR is
one integration path for that source; do not separately merge overlapping #26,
#27 and #28 changes into this stack. Earlier native durability work remains in #31.

## What was broken and why

| Root cause | Fix and verification |
| --- | --- |
| Proprietary `emergentintegrations` imports were absent from reproducible public installs, making configured AI/Stripe paths fail before reaching providers. | Owned bounded adapters use the already pinned public OpenAI and Stripe SDKs. Existing route authorization/tenant tools are preserved. HTTP/SDK boundary tests verify payloads, amounts, errors and unpaid status without external requests. |
| Voice ordering wrote raw audio to disk and called an unavailable gateway; the loyalty wrapper passed a Request where an authenticated user was expected and swallowed transcription failures. | Send bounded named audio bytes directly to the public async SDK; pass the authenticated actor, return a visible provider failure and retain no temporary recording. |
| A lost Stripe response could create another session after the local two-second wait; a permanent upstream key would instead replay expired attempts forever. | Send a business-scoped key derived from the durable claim generation. Reconstruct generated order metadata on retries; compare-and-swap rotates stale generations. Tests cover identical retry payloads, tenant separation and expiry rotation. |
| Legacy CRA/CRACO, unused desktop packaging and old automation tooling brought 139 frontend audit findings. | Vite/Jest/WebdriverIO migration and compatible updates reduce findings to 29, with zero runtime advisories. Explicit lint replaces the correctness checks CRA used to provide. Canonical npm lockfile/install removes dual graph drift. See dependency debt document for each remaining advisory's reachable input path. |
| Service worker treated `/bookings-api/` as a cacheable static resource. | Both private API prefixes are network-only and return offline 503. Cache version v4 purges earlier shell caches. Tests assert no private cache reads/writes and old-cache removal. |
| Live sales confused string `.replace()` with datetime normalization, mixed date types and used old sales as today's fallback. | Normalize BSON UTC and ISO strings, filter by venue-local day, discard malformed rows and return zero for a genuinely empty day. Browser walkthrough now asserts no API 5xx across registered staff screens. |
| Customer wallet refresh referenced undefined `fetchAll`, so successful wallet edits could throw instead of refreshing. | Reload the selected profile and customer list through the existing defined loaders. New explicit lint caught this; obsolete ESLint suppression comments were removed, not replaced by a disable. |
| Low-stock expression failed on legacy missing/null stock counters. | `$ifNull` treats missing stock as zero while requiring an explicit positive reorder threshold and tenant scope. |
| Event updates accepted arbitrary ownership/id/counter fields; ticket increments were a read/write race. | Whitelist editable event fields and atomically enforce active status, positive quantity and remaining capacity. Concurrency test proves a one-seat event only accepts one request. |
| Staff roster writes accepted foreign/nonexistent staff references. | Verify the staff member within the actor's business before create/update. Foreign/missing references return 404. |
| Refund kitchen-effect metadata update used only a generated id. | Include the actor's strict tenant filter on the write, retaining the preceding ownership check. |

The first post-adapter full run found one genuine test-double incompatibility:
the audio privacy test still mocked the old synchronous SDK while the production
path became async. Replaced the SDK boundary stub, retaining all raw-audio privacy
assertions. That full run was 959 passed / 1 failed; the subsequent full run was
999 passed / 0 failed. Final-tree counts follow below; neither partial run is
presented as the final proof.

## Static and dependency checks

No credential fallback, test skip, security-baseline expansion or weakened tenant
check was used. `backend/.flake8` remains the existing error-only policy. The
mypy differential gate still checks the existing count and accepted categories;
it is not a claim of a fully typed backend. Public SDKs were already dependencies,
so this change adds no Python package or private index requirement.

Frontend full audit: 139 → 29 package findings (0 critical, 5 high, 24 moderate,
0 low). Runtime audit: zero. Remaining build inputs and upgrade tradeoffs are
listed in `frontend/SECURITY_DEPENDENCY_DEBT.md`, not hidden in an ignore file.
ESLint 9 EOL and existing redundant dynamic-import build warnings remain visible.

Final validation table will be filled from completed runs, including new native
runs for the Vite/WebdriverIO build. Earlier native results alone do not prove
this application revision.

## Tenant isolation spot check

Reviewed five previously untouched request files: `devices.py`, `customers.py`,
`loyalty.py`, `transactions.py`, `staff_management.py`, including their stamped
insert/update helpers. Device/customer data paths use actor business filters and
server-stamped ownership. Event ownership injection, roster references and the
refund metadata write were fixed as described above. Newly touched files now have
negative cross-business coverage. No broad legacy default-business fallback added.

Global PIN lookup/collision checks in staff authentication are deliberate identity
resolution before a business is known, not unscoped tenant-data browsing. They
reject ambiguous PINs, inactive memberships and MFA-only accounts. No PIN policy,
manager authority or tenant permission was widened. This is a bounded spot check,
not a proof that every historical route is free of tenant bugs.

## End-to-end code traces

- **Owner email/password:** Login → `authAPI` → `/api/auth/login` → saved bcrypt
  credential → account lockout and required 2FA → `_complete_login` → membership,
  device binding and native durable session storage. Challenges grant no business
  access. Bootstrap env changes deliberately never overwrite saved credentials.
- **Owner PIN:** Login → `staffAPI.pinLogin` with device headers →
  `/api/auth/pin-login` → unique PIN, active account/business and device validation.
  MFA-required owners must use email + second factor. No shared/default `0311`
  is installed; it works only when privately assigned to that account and unique.
- **POS:** Product selection/POSContext cart → `POSTerminal.handleCheckout` →
  `createTransactionResilient` → actor-bound queue or `/transactions` → server
  product/tax/tender/loyalty validation and atomic sale effects → transaction id.
  Offline cash is queued, not represented as settled server data. Stripe uses a
  hosted-session redirect; signed webhook/provider status drives finalization,
  never a client success flag. Physical EFTPOS and printing remain separate gates.
- **Reservation:** Reservations form → `reservationsAPI.create` → `/reservations`
  with matching `Reservation` response model. Backend validates owned customer/
  table references, booking rules and tenant/date capacity fence; reservation store
  writes durable booking-sync outbox work. UI renders rule 409 for authorized
  overrides. Public booking service has separate contention/replay tests.
- **Recovery:** `/owner-recovery` → initiate verifies operator secret and existing
  owner email → hashes a 15-minute one-use token bound to saved credentials →
  complete atomically consumes it, sets password/optional unique PIN, revokes old
  sessions/trusted devices. It preserves MFA and business/role. Routine email reset
  is separately configuration-gated and must be delivery-tested before handover.

No API-shape mismatch was found in these traced paths after adapter replacement.
Removed dead development plugins and unused frontend Electron host; supported
Windows host remains in `apps/windows`. The old webpack public-path shim is
replaced by Vite module-relative chunks and an explicit host asset manifest.

## Provider configuration and reproducibility

Server only: `OPENAI_API_KEY`; optional `NUA_AI_MODEL` (default current route model,
usually `gpt-5.2`), `NUA_TRANSCRIPTION_MODEL` (default `whisper-1`),
`OPENAI_BASE_URL` (HTTPS, no embedded credentials; default public OpenAI API).
Legacy `EMERGENT_LLM_KEY` does not act as an OpenAI secret. No key is exposed in
Vite's explicit public build-variable allowlist. Chat history is bounded per
adapter instance; it is not shared across tenants or process-global sessions.
The adapter sends `store=false`; this is not a claim about the provider's full
retention policy or compliance status.

Stripe: `STRIPE_API_KEY` and existing webhook secret/configuration; the public SDK
uses per-request credentials, integer AUD cents and actual Checkout status. It does
not register webhooks or select a payment provider for a venue. Retry URLs must
remain consistent for a given provider key; Stripe safely rejects conflicting
parameters rather than charging another session. Coinbase's existing two-second
local claim wait is unchanged; this PR does not claim provider-side dedup for it.
See public [OpenAI chat](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create),
[audio](https://developers.openai.com/api/reference/resources/audio/subresources/transcriptions/methods/create)
and [Stripe idempotency](https://docs.stripe.com/api/idempotent_requests) contracts.

Build: Node 22.12+, `cd frontend && npm ci && npm run lint && npm test -- --runInBand
--watchAll=false && npm run build`. Native builds retain explicit HTTPS API
origin and existing Capacitor/Electron isolation policies. Vercel service roots,
API-prefix routing and SPA fallback are preserved; only frontend framework and
install/build commands change. This branch has Git deployment disabled.

## Remaining launch gates / original checklist disposition

| Area | Current disposition |
| --- | --- |
| Shared web/mobile/Windows foundation, actor-bound offline queue, plaintext token migration, docket escaping | Implemented in the earlier stack; retained here. Re-run current native workflows before review approval. |
| iOS refresh/PIN cold restart | PR #31 proved strict refresh provenance, exact actor and logout invalidation using Keychain. Current build migration needs fresh simulator proof below. |
| Consistency and tenant references | PR #26 source integrated; full in-process and real Mongo proofs required for this combined tree. |
| Portable public AI/Stripe execution | Software adapter and contract tests implemented here; provider sandbox credentials, model access, webhook delivery and actual venue checkout still need an authorized isolated smoke run. No paid or live request performed. |
| Offline cold-start authorization | Intentionally requires server verification before a saved native session may act. Do not bypass actor/device checks to make offline startup appear successful. |
| Printer/drawer/scanner/payment terminal | Honest capability abstractions exist. Choose supported hardware/provider/SDK and test actual devices, disconnects, reconnects, cash drawer and paper errors at the pilot venue. No hardware success invented from simulator runs. |
| Signing and distribution | Release certificates/profiles, app-store accounts/review, signed Windows distribution and device installation remain operator-controlled external inputs. |
| Backup/restore, tenant legacy reconciliation, delivery and launch pilot | Follow foundation runbook against authorized staging, review quarantine evidence, prove restore and actual recovery-email delivery, then run a supervised venue acceptance session. No production migration or destructive operation performed here. |

The next phase is review/integration, then an explicitly authorized isolated
provider + physical-device pilot and signing/distribution. No percentage or
unqualified production-ready claim substitutes for those external proofs.
