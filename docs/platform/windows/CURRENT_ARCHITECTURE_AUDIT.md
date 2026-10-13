# PHASE 0 AUDIT RESULT

Audit date: 2026-10-12. Scope: Windows touchscreen POS (target 3) and Windows desktop (target 4). Android tablet/phone ownership remains with Claude.

## Verified baseline

Repository: Sam-NUA/NUA. Working branch: `feat/windows-foundation`.
Base: `origin/main`, `99635835b841b1516b9eeb4e394faf29f3a90d2d`.
`codex/owner-access` exists at `4a9f10f389e3029b4479a9d853c699230c62efff`, but lacks the later merged launch corrections. Main contains PRs 17–20, including the atomic points-sale and cron/PIN corrections. This is why this branch starts from main, rather than silently assuming main is deployed.
The GitHub Vercel status for the base is successful; live readiness exposed the corrected cron completion shape. Exact production alias-to-SHA inspection is BLOCKED (Vercel connector 403). No deployment is performed by this work. Remote branches were fetched before creating this worktree; no Android foundation PR was visible at that point.
Baseline CI on the identical pre-merge tree: 916 backend tests passed; 13 browser tests passed. These are historical baseline results, not validation of this branch.

## Structure and architecture

React 19 / React Router 7 / CRA 5 / CRACO 7 / Tailwind and Radix frontend in `frontend`. FastAPI / Motor / MongoDB in `backend`; a separate FastAPI bookings service in `bookings-api`. Vercel routes web, POS and bookings through three services. Server routes, actor context, database stores and provider integrations remain the authority for business rules. No backend or MongoDB belongs in a desktop installer.
Owner login/password, PIN and MFA/recovery live in `backend/routes/auth.py`; create-once seed behavior is intentional. `frontend/src/contexts/AuthContext.jsx` gates protected views during transient auth errors. RBAC and tenant scoping must stay server enforced.
`backend/middleware/actor_context.py` resolves the active user and business and fails closed for missing tenant context. `transactions.py` scopes client operation deduplication; points redemption uses the existing atomic store. Reservations and KDS have separate authorization and state transitions. None can be replaced by a local PIN or locally supplied business ID.
Device activation/revocation already exists in `routes/licensing.py`, owner/manager activation and owner revocation scoped through `_own_tenant_id`. This license inventory is NOT cryptographic per-request terminal attestation. Trusted MFA devices are a separate concept. `ops/device-status` is diagnostics, not hardware certification.
Realtime includes tenant live-feed WebSockets and a split-bill socket with deliberately limited unauthenticated event payloads. Serverless persistence/reconnect and query-token logging need operational review. Background work includes authenticated cron dispatch, coursing and booking outboxes. Do not move this authority into a client.
Payments include Stripe checkout/server finalization, QR flows, split bills and manually recorded tenders. A recorded card tender is not proof of provider authorization. Native terminal SDK pairing/reconciliation is not implemented by the desktop wrapper. Loyalty balance mutation remains server-owned. AI/voice integrations need microphone permission and server credentials; those credentials must never enter the native bundle.

## Findings and root causes

| ID | Severity | Evidence / root cause | Disposition |
|---|---|---|---|
| W01 | Blocker | `frontend/electron/main.js` never loads its preload; advertised IPC methods have no handlers. | Replace Windows entry path with isolated tested shell. |
| W02 | Blocker | Electron 33 and alternate Electron 28 manifest compete; alternate packages backend/Mongo paths. | New Windows-only locked manifest; old launch commands must not be treated as supported. |
| W03 | Blocker | BrowserRouter uses paths while shell loads `file://`; API env is baked at build, not read from bridge. | Bundled custom secure origin with SPA fallback and explicit build-time API origin. |
| W04 | Critical | Active IndexedDB `nua-offline` is global; records/cache lack account/business partition. Replay uses the current account's token. | Shared integration blocker; implement reusable scoped queue foundation and coordinate migration before release. Do not replay legacy rows under guessed ownership. |
| W05 | Critical | `offlineQueue.js` drops server-rejected records; KDS actions lack stable initial mutation IDs; offline card returns synthetic success. | Durable failure/unknown states and idempotent cash-only queue contract; current POS caller migration is required. |
| W06 | High | Auth access/trusted-device tokens reside in localStorage; multiple direct consumers. | OS-encrypted storage foundation; shared auth migration must be coordinated with Android, never silently claimed complete. |
| W07 | High | Printer service POSTs HTTP to raw TCP port 9100; receipt HTML interpolates business/item data unescaped. | Windows native spooler and escaped structured receipt foundation. Legacy browser print paths remain release blockers until routed. |
| W08 | High | Active SW excludes `/api/` but not `/bookings-api/`; generic GET caching and forced activation can retain data/reload mid-sale. `sw.js` is a second implementation. | Windows has bundled assets and no service worker; shared PWA correction belongs in coordinated work. |
| W09 | Blocker | No device pairing credential bound to every native request; license revocation does not itself revoke a staff token. | Document server extension; no fabricated device authorization. |
| W10 | Blocker | No signing identity, controlled updater, minimum-client-version endpoint or physical hardware matrix evidence. | Unsigned CI artifact only; release gates remain closed. |
| M01 | Blocker | Root Capacitor 8 vs frontend Capacitor 6; no confirmed complete platform project/pipeline. | Claude Android ownership. |
| I01 | Blocker | No Apple project/signing/entitlements or certified iOS hardware path. | Design only, not implemented here. |

Legacy `frontend/src/services/offline.js` has no imported consumers in the source search and uses a second unscoped SquarePOSDB. Keep quarantined from the new platform path; absence of imports is not a migration strategy. The shared active queue and all browser print consumers need explicit integration tests before shipping Windows.

## Compatibility and implementation sequence

See `BROWSER_API_INVENTORY.md` for concrete source hits. DOM, keyboard/touch and IndexedDB exist in Electron; availability alone does not establish security or offline correctness. Camera, microphone, USB/serial/Bluetooth, notifications and geolocation require explicit grants or adapters. File access must use narrow commands, never expose Node or unrestricted paths. WebSockets must use the configured backend origin rather than `window.location.host` on the desktop custom origin.

1. Publish this Phase 0 audit before shell/source modifications.
2. ADR: retain Electron for Windows native spooler support and the existing JavaScript maintenance path; isolate dependencies from Android. Evaluate Tauri again if deployment footprint becomes decisive.
3. Implement secure bundled shell, narrow bridge, touch/desktop modes, native receipt command, encrypted local store and durable tenant/account queue primitives with restart/failure tests.
4. Add Windows unsigned installer CI; compile shared React assets and run complete backend regression after code batches.
5. Coordinate shared auth/queue/printer callers with Claude. Block release until integration, signing, hardware and real payment reconciliation are verified. No production changes or deployments.
