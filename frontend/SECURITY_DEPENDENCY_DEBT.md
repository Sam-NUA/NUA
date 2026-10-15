# Frontend dependency vulnerability debt

`npm audit --audit-level=high` runs in CI (`.github/workflows/ci.yml`) as a non-blocking (`|| true`) informational gate. This document tracks what's actually known about the remaining vulnerabilities, re-verified and rewritten on 2026-10-15.

## npm vs. yarn: two independent lockfiles, only one of them ships

This repo carries both `package-lock.json` (npm) and `yarn.lock` (yarn classic 1.22.22, pinned via `package.json`'s `packageManager` field). **They resolve dependency versions completely independently** — fixing or bumping a transitive package in one has zero effect on the other.

Only one of them is actually used to build the deployed artifact:
- `frontend/Dockerfile`'s build stage runs `yarn install --frozen-lockfile && yarn build`.
- Vercel's deploy also resolves via `yarn.lock` (a prior stale-lockfile incident broke that deploy with `errorCode: "dirty_lock_file"` — see git history).

So **`yarn audit` is the production-relevant audit**, not `npm audit`. The previous version of this document only tracked the npm side, which understated the real picture. Both are now tracked below.

## Current numbers (2026-10-15, after this pass's safe fixes)

**npm** (`npm audit`): 118 vulnerabilities — 1 critical, 75 high, 37 moderate, 5 low, across 1727 resolved dependencies.

**yarn** (`yarn audit`, the one that matters for the shipped build): 234 vulnerabilities — 6 critical, 126 high, 92 moderate, 10 low, across 1744 resolved dependencies, spanning 23 unique vulnerable module names.

## What this pass did (safe fixes only — no CRA/Vite migration, no major bumps)

- Ran `npm audit fix` (no `--force`): reduced npm-side critical count from 4 → 1 (all other npm criticals were in `electron-builder`'s own transitive chain and got a non-breaking bump).
- Removed the `serve` devDependency from `package.json` — grepped the whole repo (scripts, `Dockerfile`, `docker-compose*`, CI workflows) and confirmed it is invoked nowhere; the actual production web server is nginx (via `frontend/Dockerfile`), not `serve`. Zero-risk dead-weight removal, not a version bump.
- Regenerated `yarn.lock` via a real `yarn install` after the `package.json` change (first run, before the `serve` removal, reported "Already up-to-date" — confirming the npm-side fixes above never touched yarn's resolution at all).
- Verified `craco build` (the actual `npm run build` / CI build command) and `yarn build` both complete successfully against the updated lockfiles, and `yarn install --frozen-lockfile` passes cleanly (the same check that catches the kind of lockfile drift that broke the Vercel deploy previously).

## Root-cause map: all 23 yarn-flagged modules, traced to their actual dependency chain

Every vulnerable module name was traced to its root-level consumer(s) by parsing `yarn.lock`'s dependency graph directly (not guessed). All 23 resolve to **devDependency-only build/CLI tooling** that is never imported by application source code and never ships in any deployed artifact (the CRA production bundle, the Capacitor Android/iOS webview bundle, or the packaged Windows Electron app) — with one distinct exception, `electron` itself, covered separately below.

| Module | Severity counts | Root chain(s) | Shipped? |
|---|---|---|---|
| `webpack-dev-server`, `webpack-dev-middleware` | high / moderate | `react-scripts` (CRA dev server only — `craco build` never invokes it) | No |
| `braces`, `compression`, `node-forge`, `nth-check`, `postcss-selector-parser`, `serialize-javascript`, `svgo`, `underscore` | high / moderate | `react-scripts` (CRA/webpack build toolchain) | No |
| `postcss` | moderate / high | `react-scripts` + `tailwindcss` (both compile CSS at build time; output is static CSS, not shipped JS) | No |
| `brace-expansion`, `@tootallnate/once`, `fast-uri`, `sprintf-js` | high / moderate / low | shared across `react-scripts`, `eslint`/`eslint-plugin-*`, `electron-builder`, `@capacitor/cli` | No |
| `@eslint/plugin-kit` | low | `eslint` + `react-scripts` | No |
| `uuid` | moderate | `react-scripts` + `@capacitor/cli` | No |
| `app-builder-lib`, `builder-util-runtime`, `ip-address` | high / moderate | `electron-builder` (packaging tool itself — builds the installer, isn't part of it) | No |
| `tar` (all 6 of the critical findings) | critical / high / moderate | `@capacitor/cli` (native-project sync tool) + `electron-builder` (installer packaging) | No |
| `extract-zip` | high | `electron` (used only by Electron's own install-time `postinstall` script to unpack the downloaded binary — not required or shipped by the Electron runtime itself) | No |

Verification method: for each module, the full `yarn.lock` dependency graph was parsed and walked backward to every root-level package declared in `package.json`. No module in this table traces to any path outside `react-scripts`, `eslint`/`eslint-plugin-*`, `tailwindcss`, `electron-builder`, or `@capacitor/cli` — all five are devDependency-rooted (or, for `react-scripts`/`@capacitor/cli`, prod-listed-but-CLI-only tooling never imported by app code).

Forcing a fix for any of these (`npm audit fix --force` / `yarn upgrade --latest`) means a major, breaking bump: CRA → Vite-class migration for the `react-scripts` cluster, `electron-builder` 25 → 26 for its cluster. Per the explicit scope of this pass (safe fixes only), none of that was attempted here. Tracking a dedicated CRA/Vite migration task remains the right recommendation for the `react-scripts` cluster specifically.

## The one genuinely different finding: `electron` itself

Everything above is build-tooling that never reaches a shipped artifact. `electron` (the npm package, pinned to major `33`, currently resolved to `33.4.11`) is **not** in that category — it's a devDependency in `package.json`, but the exact binary version it resolves to is literally what `electron-builder` packages into the real, user-facing Windows `.exe` (`electron-build` script: `craco build && electron-builder --win --publish never`). Its own vulnerabilities (moderate × 21, high × 11, low × 6) are a genuine, currently-unaddressed gap in the shipped Windows app, not a false positive like the rest of this document.

Clearing it requires a 33 → 41 major version jump (8 majors), which risks the Windows packaging/smoke-test pipeline already built and verified earlier in this project. That is explicitly **out of scope for this pass** (safe fixes only, no major bumps) and should be tracked as its own dedicated, tested task — distinct from, and higher-priority than, the build-tool-only clusters above, since this is the one place where a real vulnerability count maps to a real shipped binary.

## Summary of outstanding, explicitly out-of-scope work

1. **`electron` 33 → 41** (devDependency, but genuinely shipped via electron-builder) — needs its own pass with full Windows packaging + smoke-test re-verification.
2. **CRA → Vite (or maintained CRA fork) migration** — would clear the entire `react-scripts` cluster, the largest share of both audits' findings. Framework migration, not a dependency bump.
3. **`electron-builder` 25 → 26** — would clear its own cluster (`app-builder-lib`, `builder-util-runtime`, `ip-address`, its share of `tar`/`brace-expansion`/etc.). Major version bump.

None of the three above change behavior of the deployed web app, Android/iOS app, or backend as they stand today — they reduce latent risk in build/packaging tooling (#2, #3) and in the shipped Windows binary (#1) respectively.
