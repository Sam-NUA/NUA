# Frontend dependency vulnerability debt

`npm audit --audit-level=high` is now wired into CI (see `.github/workflows/ci.yml`) and runs on every PR. As of 2026-09-14:

- **Before this pass**: 59 vulnerabilities (1 critical, 36 high, 10 moderate, 12 low).
- **After a safe `npm audit fix` (no `--force`, no breaking changes, build verified green after)**: 46 vulnerabilities (1 critical, 27 high, 7 moderate, 11 low).

## Why the remaining 46 are deferred

Every remaining advisory only has a fix path through `npm audit fix --force`, which npm itself reports would install `react-scripts@0.0.0` — i.e. it wants to remove Create React App entirely. The vulnerable packages (`webpack-dev-server`, `sockjs`, `uuid`, and their dependents) are transitive dependencies of `react-scripts`/`craco` itself, used only in the **development server**, not in the production build output — `craco build` (what CI and deploy actually run) doesn't invoke `webpack-dev-server` at all. That materially lowers real-world exploitability of this specific batch (an attacker needs access to a developer's local `npm start` session, not the deployed app), but it doesn't make it zero, and "remove CRA" is a framework migration, not a dependency bump — far outside the scope of a security-remediation pass.

## Recommended next step

Track a dedicated migration task (e.g. to Vite, or to a maintained CRA fork) rather than attempting to force-resolve these in place — forcing them here would likely just break the build without actually improving production security, since the vulnerable code never ships to production in the first place.
