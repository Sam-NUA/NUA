# Multiplatform collaboration — Claude / ChatGPT (Codex) lanes

Two agents worked the multiplatform effort in parallel, each on its own
branch, with no direct channel to each other — GitHub (branches, commits,
PR descriptions) plus this file were the coordination mechanism. This
file now also records how that parallel work was reconciled, since the
reconciliation itself is part of the history worth keeping, not just the
original split.

## What actually happened (2026-10-12 → 2026-10-13)

- **Claude**: `feat/multiplatform-foundation` — Phase 0 audit, ADR-001,
  the shared `frontend/src/platform/` abstraction layer, backend device
  identity (model/routes/revocation), Android scaffold (`frontend/android/`),
  then iOS/iPadOS scaffold (`frontend/ios/`) in a later pass.
- **Codex (ChatGPT)**: `feat/windows-foundation` (PR #21) — an
  independent Windows Phase 0 audit (`docs/platform/windows/
  CURRENT_ARCHITECTURE_AUDIT.md`, preserved in git history), then a real
  Electron host (`apps/windows/`) and a reusable, identity-scoped cash
  queue (`packages/platform-core/`), deliberately isolated under
  `docs/platform/windows/` rather than touching Claude's canonical
  `docs/platform/` set or the shared frontend, per its own
  `CLAUDE_HANDOFF.md`.
- **Reconciliation**: on explicit instruction, Codex's branch was merged
  into `feat/multiplatform-foundation`, extended with the
  `frontend/src/platform/electron/*` adapters Codex's own handoff
  correctly identified as the next step, a backend test for
  `platform: "windows"` (mirroring the one already written for `"ios"`),
  and new IPC (`nua:token-*`, `nua:device-id-*`, `nua:print-html`,
  `nua:save-file`) backed by primitives Codex had already built and
  tested (`EncryptedStore`, `windowsCrypto`). Codex's `docs/platform/
  windows/` findings were folded into this canonical doc set (crediting
  which pass did what) rather than left as a second, forked set of docs
  describing the same repository.

This file is kept as the record of that split and reconciliation, not as
a live "who owns what" table any more — there's one branch and one doc
set now. If a third parallel track starts again, add a new dated section
above rather than editing this history away.

## Original lanes (2026-10-12, as agreed at the time)

| Area | Owner | Notes |
|---|---|---|
| `docs/platform/CURRENT_ARCHITECTURE_AUDIT.md`, `ADR-001-multiplatform-architecture.md` | Claude | Full-repo Phase 0 audit + architecture decision. Codex audited Windows specifically and independently, under `docs/platform/windows/` at the time — now folded into these same canonical files. |
| Shared platform abstraction (`frontend/src/platform/`) | Claude (authoring), shared (implementing) | Interfaces are platform-agnostic by design — Android, iOS, and Windows adapters all implement the same contracts. |
| Android: `frontend/android/`, Capacitor config/adapters | Claude | First-priority target per the directive. |
| iOS: `frontend/ios/`, iOS-specific Info.plist/adapters | Claude | Later pass, per explicit instruction overriding the directive's own default deferral. |
| Windows: `apps/windows/`, `packages/platform-core/` | Codex, then Claude (taken over for integration) | See "What actually happened" above. |
| `bookings-api/*` | Untouched by either agent | — |
