# NUA POS — Multiplatform foundation

## Current reviews — 15 October 2026

- [Terminal session and Windows durability report](TERMINAL_DURABILITY_REVIEW_2026-10-15.md): PR #24, `fix/terminal-session-durability`; current contracts, exact validation and launch limits.
- [Mobile hardening review](MOBILE_HARDENING_REVIEW_2026-10-14.md): stacked parent PR #23; tenant spot check, login/sale/booking/recovery traces and dependency exposure triage.
- [Claude's remaining iOS/dependency work](CLAUDE_IOS_DEPENDENCY_HANDOFF_2026-10-15.md): reviewed again 16 October; PR #25 preserves the latest session/Windows fixes, with extended iOS acceptance failing during Appium startup and dependency cleanup still unstarted.

These are review branches; nothing here authorises merging or deployment.
The foundation inventory below is historical. Its original environment limits
do not supersede the dated reports' actual native CI results.

Working branch: `feat/multiplatform-foundation`, base `main` @ `9963583`
(see `CURRENT_ARCHITECTURE_AUDIT.md`'s "Baseline verification").

Read in this order:

1. `CURRENT_ARCHITECTURE_AUDIT.md` — Phase 0 factual inventory: what exists
   today, including a partial, stalled Capacitor/Electron scaffold found
   already in the repo, plus a second, independent Windows-specific
   Phase 0 audit folded in at the end. `BROWSER_API_INVENTORY.md` is the
   concrete source-hit backing for it — a repo-wide survey, not
   platform-specific.
2. `ADR-001-multiplatform-architecture.md` — the architecture decision:
   Capacitor for Android/iOS, Electron for Windows, extend the existing
   IndexedDB offline queue rather than build a new one, shared backend
   device-identity model.
3. `COLLABORATION.md` — history of which agent (Claude/ChatGPT) owned which
   files while working in parallel, and how that was reconciled once
   Windows work was taken over into this same branch (see below).
4. `DEVICE_IDENTITY_MODEL.md`, `OFFLINE_SYNC_ARCHITECTURE.md`,
   `HARDWARE_ABSTRACTION.md`, `SECURITY_MODEL.md` — the shared contracts.
5. `ANDROID_ARCHITECTURE.md`, `IOS_IPADOS_ARCHITECTURE.md`,
   `WINDOWS_ARCHITECTURE.md` — what was actually built and verified for
   each platform, and what wasn't, honestly (no on-device run for any of
   the three — see each document for why, and why the reason differs per
   platform).
6. `TENANT_ISOLATION_TEST_PLAN.md`, `HARDWARE_COMPATIBILITY_MATRIX.md`,
   `MOBILE_DESKTOP_BACKLOG.md`, `MULTIPLATFORM_READINESS_REPORT.md` —
   test coverage, what's supported vs. simulated vs. untested, what's left,
   and the overall readiness verdict.

## Windows: how this doc set absorbed a second author's work

Windows foundation work (the `apps/windows/` Electron host and
`packages/platform-core`'s cash queue) was started independently by
Codex/ChatGPT on a separate branch (`feat/windows-foundation`, PR #21),
under its own `docs/platform/windows/` doc set, specifically to avoid
overwriting this doc set while both were worked on in parallel — see the
original `docs/platform/windows/CLAUDE_HANDOFF.md`, preserved in git
history. On explicit instruction, that work was then merged into this
branch, extended (the shared `platform/electron/*` adapters, the
device-identity backend test, token/device-id/print/file IPC), and its
real findings folded into this single canonical doc set rather than left
forked — `docs/platform/windows/` no longer exists as a separate tree.
Where a section below describes Windows-specific work, it says so and
credits which pass did what; nothing from that audit was silently
absorbed as if it had always been part of this one.
