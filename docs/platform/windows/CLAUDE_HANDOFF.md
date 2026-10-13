# Parallel work boundary

Claude: Android targets 1 and 2; Capacitor versions, Android projects, Android UI and mobile release pipeline.
Codex: Windows targets 3 and 4; `apps/windows`, reusable `packages/platform-core`, Windows CI and platform audit/docs. Shared frontend changes need coordination; this package intentionally avoids rewriting AuthContext or the active offline queue underneath Android work.

Release blockers requiring a coordinated integration PR:
- Replace global IndexedDB/cache with tenant + account + device partitions; never infer ownership of legacy rows. Quarantine them for explicit reconciliation.
- Auth tokens and trusted-device tokens need one asynchronous platform storage API. Update ALL direct localStorage consumers together, with refresh/account-switch tests.
- Pass the verified server identity into platform queue context. Bind every replay to that identity and cancel on logout/switch.
- Route printers through native receipt adapter; make unsupported hardware/payment capabilities visible in UI.
- Fix service-worker bookings API exclusions and forced reloads; Windows uses bundled assets without SW.
- Add durable server idempotency for KDS mutation paths before enabling their offline replay.
- Device license inventory is not request authentication; implement revocable device credentials and pairing server-side without trusting client businessId.

No merge, deployment, Railway or infrastructure changes authorized. Review both branches against the latest remote state before integration.

## Claude audit reviewed before publishing

Remote `feat/multiplatform-foundation` appeared during this session at `a17fe1e9d468cdbdf61077fe2326e66176d59927` (Claude, Phase 0). It adds the canonical `docs/platform/CURRENT_ARCHITECTURE_AUDIT.md`. To avoid overwriting it, Windows moved to `feat/windows-foundation` and all Windows documentation is under `docs/platform/windows/`. Claude's branch is untouched.

The audit agrees on React/CRA, existing native scaffolds, absolute API origins, separate auth clients, browser routing, disabled native service workers and hardware/toolchain gaps. Points to reconcile before shared implementation:
- IndexedDB availability is not offline safety: the active queue/cache lacks tenant/account partition, replays with the current token and drops rejected rows. Treat this as a security/reliability blocker, not low-risk as-is portability.
- Frontend printer.js's network path uses HTTP fetch to a nominal raw-printer port; only backend escpos.py uses actual raw TCP. Native printing must not preserve the HTTP assumption.
- Current ActorContextMiddleware verifies active user state/business with a DB lookup; do not replace it with JWT-claims-only tenant authority.
- Electron is the Windows exception selected after audit; the directive's preferred desktop starting option was Tauri, not Electron.
- Claude reports independent Vercel metadata confirming main; this Windows session's own alias inspection remains 403-blocked. Keep provenance distinct.

No Android code was visible on the remote branch at this check. Review its latest head again at integration time.
