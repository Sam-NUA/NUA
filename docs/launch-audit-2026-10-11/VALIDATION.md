# Validation evidence

| Check | Result |
|---|---|
| Initial full backend: `cd backend && python -m pytest tests/inprocess -q` | 861 passed, 0 failed, 35,598 warnings; 314.96s |
| Post-change full backend, same command | 870 passed, 0 failed, 35,761 warnings; 328.21s |
| Bookings service: `python -m pytest tests -q` | 35 passed, 0 failed, 127 warnings; 0.48s |
| Backend `python -m flake8 .` using repository configuration | Exit 0; no findings |
| `python scripts/check_type_baseline.py` | Pass: 293 findings within baseline 814, no new error categories; baseline files untouched |
| Frontend `CI=false npm run build` after Axios update | Compiled successfully; zero compiler errors |
| `pip-audit -r requirements.txt --no-deps --disable-pip --format json` | 117 pinned packages, 0 advisories; raw JSON included |
| Resolver pip-audit and existing dependency differential gate | Exit 0, but only one package returned; not treated as complete audit coverage |
| Frontend npm audit after update | 129 affected entries: 4 critical, 81 high, 39 moderate, 5 low; triage and raw JSON included |
| Gitleaks 8.30.0 full Git history | 517 commits, 2 matches for the same historical test-only fixture in backend/tests/test_iteration6_features.py:179; no discovered live credential; no ignore added/history rewritten |
| Gitleaks changed tracked diff | Zero matches; full staged patch scan also performed before publication |
| Local Playwright | 0 tests executed: browser download invalid ZIP; webServer also fails on sandbox-denied network-interface enumeration. No test bypass added. |
| GitHub CI / Playwright | Pending at publication; final results will be recorded in the PR description. |

Historical scanner matches are commits a8f4f190f328c1ea8242e0d0a9f72089f672c20d and b85d7056574520c0aaff6b72fe4dd944e77f2ce2. The literal is used solely as the legacy test request's fake integration key. It is not reproduced in this report. The workflow's changed-commit scan must still pass; this assessment does not change scanner configuration.

The nine added backend regression cases cover fresh PIN token validity after password changes, rejection of the old token, profile sanitization, account/venue 2FA enforcement, both staff/manager approval 2FA branches, foreign and unowned reservation rejection, valid reservation enrichment, and a duplicate-ID cross-tenant bulk edit. Existing tests were not skipped or relaxed. Local tests use mongomock and do not prove real database transaction/cold-start/hardware/provider behavior.
