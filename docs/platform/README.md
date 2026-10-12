# NUA POS — Multiplatform foundation

Working branch: `feat/multiplatform-foundation`, base `main` @ `9963583`
(see `CURRENT_ARCHITECTURE_AUDIT.md`'s "Baseline verification").

Read in this order:

1. `CURRENT_ARCHITECTURE_AUDIT.md` — Phase 0 factual inventory: what exists
   today, including a partial, stalled Capacitor/Electron scaffold found
   already in the repo.
2. `ADR-001-multiplatform-architecture.md` — the architecture decision:
   Capacitor for Android/iOS, Electron for Windows, extend the existing
   IndexedDB offline queue rather than build a new one, shared backend
   device-identity model.
3. `COLLABORATION.md` — which agent (Claude/ChatGPT) owns which files, so
   the two don't collide while working in parallel.
4. `DEVICE_IDENTITY_MODEL.md`, `OFFLINE_SYNC_ARCHITECTURE.md`,
   `HARDWARE_ABSTRACTION.md`, `SECURITY_MODEL.md` — the shared contracts.
5. `ANDROID_ARCHITECTURE.md` — what was actually built and verified this
   pass, and what wasn't (honestly: no APK, no emulator run — see why).
6. `TENANT_ISOLATION_TEST_PLAN.md`, `HARDWARE_COMPATIBILITY_MATRIX.md`,
   `MOBILE_DESKTOP_BACKLOG.md`, `MULTIPLATFORM_READINESS_REPORT.md` —
   test coverage, what's supported vs. simulated vs. untested, what's left,
   and the overall readiness verdict.

`WINDOWS_ARCHITECTURE.md` and `IOS_IPADOS_ARCHITECTURE.md` are present as
short pointer files only — Windows implementation is explicitly ChatGPT's
lane this pass (see COLLABORATION.md), and no iOS-specific work was done
or needed yet per the master directive's own Phase 10 guidance.
