# Multiplatform readiness — Windows foundation

Repository Sam-NUA/NUA. Base `main` at `99635835b841b1516b9eeb4e394faf29f3a90d2d`; working branch `feat/windows-foundation`. Review-only; no merge/deploy/Railway/live transaction.

## Completed package

Phase 0 audit and browser API inventory published before source changes. Isolated pinned Windows Electron host reuses the React build with SPA routing, restricted main-frame IPC, sandbox/CSP/navigation/permission guards, in-memory Chromium session, touch/desktop controls and validated structured receipt printing. Added OS-encryption adapter, atomic scoped persistence and separately tested cash queue with stable operation IDs, account fencing, retry/backoff and retained conflicts. Added Windows native smoke + unsigned NSIS CI. Android files and shared frontend runtime are untouched to avoid concurrent ownership conflicts.

This is FOUNDATION, not an integrated offline POS release. Store/queue primitives are deliberately not exposed to an unverified renderer or substituted under the shared AuthContext. Existing web queue/token/receipt paths remain integration blockers, detailed in the audit and Claude handoff.

## Validation at initial review submission

| Check | Result |
|---|---|
| Foundation unit/security/durability tests | PASS — 17 passed, 0 failed |
| Shared React production compile | PASS — compiled successfully, zero compile errors |
| Windows renderer preparation | PASS — shared assets copied, inline web-only scripts removed, explicit API origin validated |
| Backend flake8 | PASS — no findings |
| Backend mypy differential | PASS — 290 errors vs accepted 814 baseline; no new error categories |
| Backend pip-audit | PASS — no known vulnerabilities reported |
| Windows npm audit | 8 moderate package findings, one underlying build-only advisory; 0 high/critical. See DEPENDENCY_REVIEW.md |
| Windows production npm audit | PASS — 0 findings |
| Existing frontend npm audit | FAIL/debt — 129 package findings: 4 critical, 81 high, 39 moderate, 5 low; not ignored |
| Full backend in-process | PASS — first full run: 916 passed, 0 failed, 37,083 warnings in 498.59s; final rerun/CI pending |
| Browser Playwright locally | BLOCKED — serve crashes on restricted `uv_interface_addresses`; CI required |
| Windows shell/OS crypto/installer | CI PENDING — Linux host cannot prove Windows behavior |
| Secret scan, branch diff | PASS — no leaks in this change; complete-tree scan flags an unchanged test fixture at backend/tests/test_iteration6_features.py:179 |
| Physical Windows/hardware/payment | NOT TESTED |

## Readiness and blockers

Percentages count evidence gates, not estimated product completion. Windows has 2 of 10 release gates established locally (reviewed architecture; automated primitive validation): **20%**. Remaining gates: native build/smoke, integrated auth, integrated offline acceptance, device revocation, native payment reconciliation, physical hardware/touch QA, signed release/updates, and operational pilot. CI build/smoke can raise this to 30%; it cannot clear the other gates.

Android status here: **NOT STARTED by Codex**, owned by Claude; existing Capacitor configuration is not evidence of a working Android package. Apple/iPad readiness: **0 of 10 release gates / 0% implementation readiness**; design notes only.

Hardware: Windows spooler adapter implemented, no physical printer certified; keyboard-wedge scanners unverified; USB/serial/LAN direct drivers, drawer and payment terminals unsupported. No simulated terminal result is represented as success.

## Security and deliberate exclusions

No backend authorization/tenant code or seed credentials changed. Primitive tests cover business/account boundaries and wrong-tenant replay responses, not full native-backend authorization. Existing browser offline/cache cross-account risk, renderer tokens, legacy print HTML, service-worker caching, device credentials and payment unknown states are explicitly unresolved. No raw cards/secrets/custom offline card behavior introduced.

Legacy frontend package manifests were not rewritten because Claude owns Android dependency alignment. Shared AuthContext, POSTerminal and active IndexedDB queue need one coordinated change, not competing rewrites. Old Electron scripts must not be used to release this package. No deployment credentials or signing material were requested or invented.

Next exact package: shared-auth/offline integration across Claude's Android adapter and this Windows host, including legacy-data quarantine, server-verified scopes, pinned transport, UI conflict recovery, receipt routing, and the real restart/reconnect/exactly-one/foreign-tenant acceptance tests. Then revocable device credentials and provider-backed terminal integration; then physical qualification and signed release.
