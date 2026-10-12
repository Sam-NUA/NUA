# Multiplatform collaboration — Claude / ChatGPT lanes

Two agents are working the multiplatform effort in parallel. GitHub (branches,
commits, PR descriptions) plus this file are the coordination mechanism —
neither agent has a direct channel to the other. Keep this file current
when you touch shared ground; don't delete the other agent's section.

## Lanes (as of 2026-10-12)

| Area | Owner | Notes |
|---|---|---|
| `docs/platform/CURRENT_ARCHITECTURE_AUDIT.md`, `ADR-001-multiplatform-architecture.md` | Claude | Full-repo Phase 0 audit + architecture decision already written. ChatGPT is separately auditing — if conclusions differ, reconcile before either side scaffolds further rather than shipping two contradictory ADRs. |
| `packages/platform/*` (shared `PlatformService` interfaces) | Claude (authoring), shared (implementing) | Interfaces are platform-agnostic by design — both Android and Windows adapters implement the same contracts. Coordinate before changing an interface's shape once the other side has an adapter against it. |
| Android: `frontend/android/`, `frontend/capacitor.config.json`, Android-specific adapter implementations under `packages/platform/android/` | Claude | First-priority target per the directive. |
| Windows: `frontend/electron/`, `frontend/electron-package.json`, `build-windows.bat`, Windows-specific adapter implementations, Phase 3 (offline-first) and Phase 4 (device identity) **as they apply to the Windows/Electron target specifically** | ChatGPT | Per explicit user direction (2026-10-12). Claude will not touch these files. |
| Phase 3/4 **shared, non-platform-specific pieces** (backend device-identity model/endpoints, the offline-mutation idempotency contract both platforms' queues must satisfy) | Claude, until ChatGPT's section below says otherwise | These aren't Windows-exclusive — both platforms' sync engines need to agree on the same server-side contract. Documented in the ADR; please read it before building a Windows-side offline queue against a different shape. |
| `bookings-api/*` | Untouched by either agent this pass | — |

## Claude section

### Branch: `feat/multiplatform-foundation`
Base: `main` @ `9963583` (verified live production deployment at the time
this work started — see `CURRENT_ARCHITECTURE_AUDIT.md`'s "Baseline
verification" section for why this isn't `codex/owner-access`).

Working through: Phase 0 (audit, done) → Phase 1 (ADR) → Phase 2 (shared
platform-abstraction interfaces) → Phase 6 (Android scaffold + first
demonstration flow), per the master directive. Phases 3/4's Windows-specific
work is explicitly ChatGPT's per the user's direction — Claude is only
defining the shared contract those phases need to agree on (device-identity
schema, idempotency-key shape for queued mutations), not implementing a
Windows offline store or Windows device registration UI.

## ChatGPT section

(ChatGPT: add your branch name, base SHA, and what you're working on here —
this placeholder exists so the next person finds this file already
structured for you, not because content has been added yet.)
