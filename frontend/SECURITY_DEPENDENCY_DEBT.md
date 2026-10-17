# Frontend dependency audit — 17 October 2026

The previous CRA-era report is superseded by this audit. All counts are npm
package findings, including vulnerable ancestors, not distinct CVEs.

| Scan | Critical | High | Moderate | Low | Total |
| --- | ---: | ---: | ---: | ---: | ---: |
| Starting branch, fresh full audit | 4 | 89 | 41 | 5 | 139 |
| Final frontend full audit | 0 | 5 | 24 | 0 | 29 |
| Final frontend `npm audit --omit=dev` | 0 | 0 | 0 | 0 | 0 |

## Remediation

Removed the unused legacy Electron application under `frontend/electron` and its
packaging dependencies. The supported desktop application remains `apps/windows`.
Removed CRA/CRACO, its development server and unused development editing plugins;
Vite 8 now builds the same React application. Jest 30 keeps the existing tests,
an explicit ESLint gate catches undefined names/JSX, and WebdriverIO 10 removes
the old automation dependency chain. Capacitor CLI and Tailwind animation are
build dependencies. Compatible updates are captured by `package-lock.json`.
No forced audit fix, blanket resolution override or ignore-file expansion was used.

CI enforces zero runtime advisories. The full audit remains visible and nonzero.
`npm ci` is the canonical install everywhere; the obsolete Yarn lockfile was
removed rather than publishing an unverified second dependency graph.

## Remaining findings and actual input paths

| Advisory | Reachability and decision |
| --- | --- |
| [braces stack exhaustion](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm) | Five high package findings through Tailwind 3's glob/watch tree. Only repository-owned content paths reach it during builds, not customer requests or uploaded files. The latest braces 3 still has this advisory. npm proposes Tailwind 4, which changes styling defaults and requires newer Safari. Keep this visible until a separately verified design/browser migration; don't silently reduce tablet support. |
| [postcss-selector-parser CPU exhaustion](https://github.com/advisories/GHSA-rj75-hqrm-r3gf) | Tailwind 3/postcss-nested build chain parses repository CSS. No customer-supplied CSS enters the build. Same major-version migration as above. |
| [sprintf-js precision DoS](https://github.com/advisories/GHSA-hp3w-g68c-fv3c) | Jest/Babel coverage instrumentation loads js-yaml 3/argparse/sprintf-js. Tests and coverage configuration are trusted repository inputs. Not included in the deployed browser. No patched compatible sprintf-js 1 version was offered; npm's proposed Babel/Jest downgrade is inappropriate. |
| [uuid caller-buffer bounds](https://github.com/advisories/GHSA-w5hq-g745-h8pq) | Capacitor CLI → xcode → uuid 7. The xcode project generator calls v4, while the advisory concerns v3/v5/v6 with caller buffers. Used to generate build projects, never a tenant request handler. npm proposes downgrading Capacitor CLI; that does not constitute a verified remediation. |

These paths lower customer exploitability; they do not eliminate build/supply-chain
risk. Do not accept untrusted repository CSS, glob patterns or test configuration.
ESLint 9 is compatible with this plugin set but now emits an EOL warning; plan the
ESLint 10/plugin migration. It is not a runtime advisory or a reason to disable lint.

The separate `apps/windows` audit must be tracked independently; see the closure
report. Neither its packages nor its existing audit policy were replaced by this
frontend migration.
