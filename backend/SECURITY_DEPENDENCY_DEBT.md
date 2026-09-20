# Backend dependency vulnerability debt

`pip-audit -r requirements.txt` is wired into CI (see `.github/workflows/ci.yml`) and runs on every PR. This file tracks what's been fixed and what's deliberately deferred, with the reasoning, so the CI step's output is honest and traceable rather than either silently suppressed or blocking merges on a scope a given pass didn't cover. As of Pass 3 there's also a real merge gate, not just a report: `backend/scripts/check_dependency_baseline.py`, checked against `backend/dependency_baseline.json`, fails CI if pip-audit reports an advisory for a package or advisory id that isn't already triaged there.

## Pass 4 — 2026-09-20: coordinated framework and dependency upgrade

The previously deferred upgrade was completed and verified rather than left as
accepted debt. FastAPI/Starlette, cryptography, pytest, black, and their pinned
transitive dependencies were upgraded together. FastAPI's new lazy included-
router representation required one compatibility adjustment in the auth-gate
test so that it continues to enumerate the complete effective route table; the
test still sweeps all 926 registered API routes.

Verification against the exact pinned environment:

- `pip-audit --local`: **0 known vulnerabilities**
- backend in-process suite: **810 passed**
- frontend production build: **compiled successfully**
- undefined-name/syntax lint gate and `git diff --check`: **passed**

`dependency_baseline.json` is now intentionally empty. Any future advisory is
therefore new debt and will fail the differential CI gate until it is fixed or
explicitly investigated and documented.

The older pass notes below are retained as the audit trail explaining what was
previously deferred; their package versions and recommendations are historical
and are superseded by this pass.

## Pass 3 — 2026-09-15: final pre-merge assurance pass — reachability proof + a real bypass found and fixed

Reproduced pip-audit independently against the exact same requirements.txt Pass 2 left: **26 advisory rows pip-audit reports, 14 distinct advisory IDs across 4 packages** (pip-audit's own row count double-counts a handful of IDs that resolve through more than one OSV alias path — e.g. starlette's PYSEC-2026-161 and PYSEC-2026-1943 each appear as 2 rows for 1 real advisory; the earlier "26 advisories" framing was pip-audit's row count, not distinct-ID count — noted here so the two numbers don't look like a discrepancy). Confirmed byte-for-byte identical to Pass 2's set: same 4 packages, same IDs, nothing regressed or drifted since.

This pass went one step further than Pass 2's reachability triage by API surface (which functions does NUA call) into **proof**: for cryptography, confirmed via `grep` that none of `PolicyBuilder`/`x509.verification`/`pkcs7_decrypt_*`/`.verify(` appear anywhere in this codebase's actual cryptography usage (`services/connect/credentials.py`'s `Fernet`, `utils/wallet_passes.py`'s `hazmat.primitives`/`x509.CertificateBuilder` for Apple Wallet pass signing) — the 3 x509/PKCS7 CVEs (PYSEC-2026-3552/3553/3554) are in APIs this app never calls, not just "probably not called."

**For starlette, the same exercise found something Pass 2's API-surface read didn't: PYSEC-2026-161 (Host-header path-injection, aka GHSA-86qp-5c8j-p5mr / X41-2026-002) is exploitable in this app right now, independent of the FastAPI-pin story.** Starlette's `Request.url` rebuilds a URL by string-concatenating the raw, unvalidated `Host` header with the real request path and reparsing it (`starlette/datastructures.py`'s `URL.__init__`: `url = f"{scheme}://{host_header}{path}"`). `server.py`'s `RequireAuthMiddleware` — the thing that makes every `/api/*` route default-deny — read `request.url.path` for its public-vs-protected decision. A request with `Host: x/api/public` turns `/api/users` into `request.url.path == "/api/public/api/users"`, which `_is_public_api()` waves through with **no token check at all** — while FastAPI's actual routing (which dispatches on `request.scope["path"]` directly and never touches `Host`) still sends the request to the real handler. `RateLimitMiddleware` and the `/api/ash/*` → `/api/nua/*` alias shim had the identical pattern.

Reproduced end to end before fixing anything: `GET /api/users` (no route-level `Depends` — `routes/settings.py`'s `get_users`/`create_user`, one of 124 routes across the codebase with no per-route auth dependency, relying entirely on the middleware) with no token correctly 401s; the same request with `Host: x/api/public` reached `db.users.find()` inside the real handler (failed only on this sandbox having no live MongoDB, not on any auth check) — and `POST /api/users` with the same header reached Pydantic body validation on `UserCreate`, i.e. one JSON payload away from creating an arbitrary staff account with zero authentication.

**Fixed directly at the application layer, not by waiting on a starlette/FastAPI bump**: `server.py` (`RequireAuthMiddleware`, `RateLimitMiddleware`, `NuaAliasMiddleware`), `middleware/license_middleware.py`, and `services/observability.py`'s request logging now read `request.scope["path"]` — the value FastAPI's router itself dispatches on, which is never derived from any header — instead of `request.url.path`. Regression test added: `tests/inprocess/test_auth_gate.py::test_a_forged_host_header_cannot_smuggle_a_protected_path_past_the_gate`, which sends every `MUST_BE_SHUT` path with a `Host` header built from every `PUBLIC_API_PREFIXES` entry and asserts the gate still holds; verified this test fails against the pre-fix code (`git stash` on `server.py` alone reproduces the 401→200 bypass) and passes after. This means this specific advisory — the one with a real, confirmed exploit path in this app — no longer represents live risk, regardless of when the broader FastAPI/starlette version bump happens.

The other 6 starlette advisories (2 multipart-form DoS — unbounded field buffering, event-loop-blocking large-file spooling; 2 lower-severity misc) remain deferred with Pass 2's reasoning unchanged: reachable in principle (this app accepts multipart uploads) but DoS-class only, no auth bypass or data exposure, and still genuinely blocked by `fastapi==0.110.1`'s `starlette<0.38.0,>=0.37.2` pin.

### Dependency-risk classification (all 14 distinct advisory IDs, 4 packages)

| Package | Advisory id(s) | Direct/transitive | Runtime/dev-only | Reachable? | Exploit conditions | NUA surface affected | Disposition |
|---|---|---|---|---|---|---|---|
| black 25.9.0 | PYSEC-2026-2120, PYSEC-2026-2121 | Direct (dev tool) | Dev-only | No — never imported by app code | N/A | None | Deferred, zero prod exposure |
| pytest 8.4.2 | PYSEC-2026-1845 | Direct (dev tool) | Dev/CI-only | No — never imported by app code, and the CVE itself needs local multi-user access to the test-running machine | N/A | None | Deferred, zero prod exposure, major-version fix (8→9) risks breaking the 644-test suite for no real gain |
| cryptography 46.0.7 | PYSEC-2026-3552 (PKCS7 decrypt oracle), PYSEC-2026-3553 (x509 chain-build DoS), PYSEC-2026-3554 (x509.verification DNS-wildcard bypass) | Direct | Runtime | Package yes, vulnerable API no — confirmed via grep that this app never calls `pkcs7_decrypt_*`/`PolicyBuilder`/`x509.verification`/`.verify(` | Would need this app to decrypt attacker-supplied PKCS7 envelopes or verify x509 chains with name constraints — it does neither | None currently; would matter if a future feature added cert-chain verification or S/MIME | Deferred, unreachable at the API level today |
| cryptography 46.0.7 | GHSA-537c-gmf6-5ccf (bundled OpenSSL advisory) | Direct | Runtime | Yes — this is about the OpenSSL binary statically linked into the wheel, independent of which Python API is called | Any TLS/crypto operation through this build | `Fernet` (credential encryption), Wallet-pass signing | Deferred pending the documented 46→48→49→50 major-version walk |
| starlette 0.37.2 | PYSEC-2026-161 (Host-header path-injection / auth-bypass) | Direct | Runtime | **Yes — confirmed exploitable, reproduced end to end** | Attacker sends any `/api/*` request with a crafted `Host` header | Every route with no route-level `Depends()` (124 across the codebase) relying on `RequireAuthMiddleware` alone | **Fixed this pass at the app layer** (`request.scope["path"]` instead of `request.url.path`) — no longer live risk |
| starlette 0.37.2 | PYSEC-2026-1941, PYSEC-2026-1943 (multipart form DoS: unbounded field buffering, blocking large-file spool) | Direct | Runtime | Yes | Attacker uploads a large multipart form/file | Any endpoint accepting file/form uploads (menu images, CSV imports) | Deferred — DoS only, no auth bypass or data exposure; blocked by the FastAPI pin |
| starlette 0.37.2 | PYSEC-2026-2280, PYSEC-2026-2281, PYSEC-2026-248, PYSEC-2026-249 | Direct | Runtime | Not specifically investigated beyond Pass 2's read (lower-severity, no auth/data-exposure impact class identified) | — | — | Deferred, blocked by the FastAPI pin, same as above |

### Recommended next step (unchanged from Pass 2, still real work)

Only `starlette` (blocked on a coordinated FastAPI bump, though its one confirmed-exploitable advisory is now neutralized independent of that bump) and `cryptography`'s remaining major-version jump are left as real, tracked debt. Schedule a dedicated task that: (1) bumps FastAPI to a version whose `starlette` constraint reaches a fixed release, running the full route surface's tests plus a manual smoke test; (2) separately walks `cryptography` 46→48→49→50 one major at a time, auditing this app's direct crypto call sites against each changelog between bumps.

## Pass 2 — 2026-09-15: full severity/reachability/exposure/blast-radius triage

Pass 1 (below) took a "bump anything low-risk" approach and explicitly deferred the framework-level packages. This pass re-triaged every advisory pip-audit reported against pass 1's baseline (152 advisories) — which had already fallen to **97 advisories across 9 packages** by the time this pass started, from upstream fixes landing between passes — using four questions per package: is it actually reachable from this app's code (imported and called, or just installed and unused), what's the real severity of what's reachable, how far does a safe fix have to jump (patch vs. minor vs. major, and is that jump even installable under this app's other pins), and what's the blast radius if the bump is wrong.

**Result: 97 advisories → 26, across 9 packages → 4.** Full backend suite (`python -m pytest tests/inprocess -q`) re-run green after every change: 629 passed, 0 failed.

### Fixed — patch/minor bumps, no compatibility risk

| Package | Old → New | Advisories closed | Why safe |
|---|---|---|---|
| `pymongo` | 4.5.0 → 4.6.3 | 1 (CVE-2024-5629, OOB read in bson parsing) | `motor==3.3.1` (the only thing wrapping it) pins `pymongo>=4.5,<5` — 4.6.3 is inside that range with room to spare. Patch-level bson bugfix, no driver API change. |
| `cryptography` | 46.0.3 → 46.0.7 | 3 of 13 (CVE-2026-26007, CVE-2026-34073, CVE-2026-39892) | These three are fixed at 46.0.5/46.0.6/46.0.7 — still inside the 46.x patch series. The other 10 need 48.0.1/49.0.0/50.0.0 (see deferred, below). |
| `pillow` | 12.2.0 → 12.3.0 | 25 | Patch bump; image handling here is receipt/QR generation, not processing untrusted uploads. |
| `pypdf` | 6.14.2 → 6.16.1 | 8 | Minor bump; used for PDF export (BAS/STP reports, receipts), not parsing untrusted PDFs. |
| `aiohttp` | 3.13.5 → 3.14.3 | 28 | Minor bump, and `aiohttp-retry` (the only pinned package that requires it) has no version constraint on it at all. **Reachability note:** `grep -rn "import aiohttp"` across the entire backend returns nothing — nothing in this codebase imports `aiohttp` directly (outbound HTTP here goes through `httpx`). It's a pure transitive dependency of something else in the pin set, so these 28 advisories had zero actual runtime exposure even before the bump; fixed anyway since the bump is free. |

### Fixed — removed, not bumped (zero reachability, and no fix exists anyway)

| Package | Advisories | Why removed instead of bumped |
|---|---|---|
| `ecdsa` | 1 (CVE-2024-23342, Minerva timing attack on P-256 signing) | No fix version exists upstream at all (`python-ecdsa`'s own position is that pure-Python constant-time signing isn't practical) — not "patchable" by definition. But `grep -rn "import ecdsa"` / `from ecdsa` across the backend returns nothing: the vulnerable `SigningKey.sign_digest()` path is never called. `pip show ecdsa` confirms it's `Required-by: python-jose` only, and `python-jose` itself (directly pinned in requirements.txt) is never imported anywhere — this app does its JWT encode/decode exclusively through `PyJWT` (`import jwt`, used in `middleware/actor_context.py`, `routes/auth.py`, `services/two_factor.py`, etc.). `rsa==4.9.1` was `Required-by: python-jose` only too. Removed all three (`ecdsa`, `python-jose`, `rsa`) from requirements.txt as genuinely dead dependencies — this closes the advisory by eliminating the unreachable code that carried it, rather than leaving an unfixable CVE on the books forever. `pyasn1`/`pyasn1_modules` were left in place — `google-auth` (which is used) depends on those independently. |

### Deliberately deferred — reasoning updated this pass

| Package | Current | Remaining advisories | Why not fixed now |
|---|---|---|---|
| `starlette` | 0.37.2 | 14 (fixes land at 0.40.0+/1.x) | **Structurally blocked, not just risky:** `fastapi==0.110.1`'s own metadata pins `starlette<0.38.0,>=0.37.2` — 0.37.2 is already the *ceiling* of what this FastAPI version allows. There is no starlette version this app can install today that both satisfies FastAPI's constraint and picks up any of these fixes. Closing this requires bumping FastAPI itself first (a framework major-version-range move with its own request/response/dependency-injection behavior changes across the whole app's ~150 routes), which is correctly a separate, dedicated, full-regression pass — not something "bump the version" can do safely, let alone as a rider on this one. |
| `cryptography` | 46.0.7 | 7 (need 48.0.1 for 1, 49.0.0 for 3, 50.0.0 for 3) | The remaining fixes span three major-version jumps (46→48→49→50). `cryptography` has a documented history of removing deprecated APIs across majors; this codebase's direct usage (JWT-adjacent crypto operations) needs an audit against each major's changelog before it's safe to move, which the patch bump already taken doesn't require. Genuinely a separate tested pass, matching pass 1's own conclusion. |
| `black` | 25.9.0 | 3 (fix 26.3.x) | Dev-only formatter — never imported or executed by the running application, zero production reachability. Lowest priority by construction, not just by choice. |
| `pytest` | 8.4.2 | 2 (CVE-2025-71176, `/tmp/pytest-of-{user}` local privilege/DoS issue; fix 9.0.3) | Dev/CI-only — never present in a deployed instance, and the CVE itself requires **local, multi-user access to the same machine running the test suite**, which is not this app's threat model at all (zero remote reachability). The fix is also a pytest **major** version bump (8→9), which risks breaking collection/fixtures across all 629 tests in this suite for a vulnerability with no production exposure — not a trade worth making under "without breaking compatibility." |

## Pass 1 — 2026-09-14 baseline (152 advisories at the time)

`pip-audit -r requirements.txt` reported 152 known advisories across the pinned dependency set at the time.

### Fixed in pass 1 (bumped, full test suite re-run green: 468 passed / 0 failed)

| Package | Old | New | Why safe to bump blind |
|---|---|---|---|
| PyJWT | 2.10.1 | 2.13.0 | Small, stable `encode`/`decode` API; directly relevant given this codebase's JWT-centric auth. |
| urllib3 | 2.5.0 | 2.7.0 | Patch/minor, widely used, no API surface this app touches directly changed. |
| requests | 2.32.5 | 2.33.0 | Same. |
| idna | 3.11 | 3.19 | Pure parsing library, no app-facing API change. |
| click | 8.3.0 | 8.3.3 | Dev-tool dependency (used transitively), patch bump. |
| Pygments | 2.19.2 | 2.20.0 | Dev-tool dependency, patch bump. |
| python-dotenv | 1.1.1 | 1.2.2 | Only used at process startup to load `.env`; narrow surface. |
| python-multipart | 0.0.20 | 0.0.31 | Used by FastAPI for form/file parsing; several of the fixed CVEs are in this exact path (malformed multipart handling), so this one matters. |
| ecdsa | 0.19.1 | 0.19.2 | Patch bump (superseded by pass 2's removal, above). |
| pyasn1 | 0.6.1 | 0.6.4 | Patch bump. |
| httplib2 | 0.31.2 | 0.32.0 | Patch bump. |

## Recommended next step

Only `starlette` (blocked on a coordinated FastAPI bump) and `cryptography`'s remaining major-version jump are left as real, reachable, unresolved debt. Schedule a dedicated task that: (1) bumps FastAPI to a version whose `starlette` constraint reaches a fixed release, running the full route surface's tests plus a manual smoke test; (2) separately walks `cryptography` 46→48→49→50 one major at a time, auditing this app's direct crypto call sites against each changelog between bumps.
