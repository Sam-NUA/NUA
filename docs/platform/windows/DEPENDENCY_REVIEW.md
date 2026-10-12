# Dependency review — 2026-10-12

Windows pins Electron 44.7.0 and electron-builder 26.15.3 in its own lockfile; root/Android manifests are untouched. The old Electron 33 frontend path is not a supported Windows release route.

`npm audit` in apps/windows: 8 moderate, 0 high, 0 critical. All eight package reports share one underlying advisory, GHSA-hp3w-g68c-fv3c (sprintf-js unbounded precision format DoS), through electron-builder → app-builder-lib → @electron/get → global-agent → roarr. Official advisory lists no patched sprintf-js version. The inspected global-agent logging calls use fixed source format strings; proxy/request values are structured context, not attacker-controlled format templates. The path is build tooling only and is not packaged as a runtime dependency. `npm audit --omit=dev`: 0 vulnerabilities. This limits production exposure, but does not erase the build-tool advisory. No ignore or forced downgrade was added. Restrict builds to reviewed code; reassess when a maintained upstream fix is available.

Existing frontend audit: 129 package findings (4 critical, 81 high, 39 moderate, 5 low). Direct affected roots include Capacitor CLI, old Electron/Electron-builder, concurrently/shell-quote, CRA, serve, Tailwind and ESLint. These are predominantly toolchain paths, but this review does not classify every transitive path as harmless. The existing SECURITY_DEPENDENCY_DEBT.md's old count and claim that every finding is webpack-dev-server debt are out of date. Current Electron has been isolated for Windows; Android version changes belong with Claude. A shared toolchain remediation/migration is still required. No baseline or ignore list was expanded.

Backend `pip-audit -r requirements.txt`: no known vulnerabilities reported in this environment. This does not certify provider SDK behavior or production configuration.

Evidence: official advisory https://github.com/advisories/GHSA-hp3w-g68c-fv3c ; locally inspected apps/windows/node_modules/global-agent/src and roarr/dist/factories/createLogger.js. Dependency scans are point-in-time results and should rerun before any release.
