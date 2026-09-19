#!/usr/bin/env python3
"""Differential dependency-vulnerability gate.

`pip-audit -r requirements.txt` (the CI step above this one) is report-only
by design — dependency_baseline.json is what actually decides pass/fail.
Each entry there is a package pip-audit currently flags, with the specific
advisory IDs someone has actually triaged (reachability checked against
this codebase's real usage — see SECURITY_DEPENDENCY_DEBT.md) and accepted
for now. This script fails CI when reality has moved past that record:

  - pip-audit reports an advisory for a package that ISN'T in
    dependency_baseline.json at all — a brand new vulnerable dependency
    landed (direct or transitive) and nobody has looked at it yet.
  - pip-audit reports an advisory ID for a listed package that ISN'T in
    that package's accepted_ids — either a new CVE was published against
    the exact pinned version, or someone bumped the version and picked up
    a different vulnerable release. Either way the existing reachability
    write-up no longer speaks for the current state.

It does NOT fail when pip-audit reports fewer advisories than the baseline
lists (a version bump that happens to close one) — that's strictly good
news; update dependency_baseline.json (--update) to drop the stale entry
next time someone's in there rather than gating on it.

Usage: python scripts/check_dependency_baseline.py [--update]
  --update   rewrite dependency_baseline.json's accepted_ids to match the
             current pip-audit output for already-listed packages (does
             NOT add newly-vulnerable packages — those need a real
             reachability write-up, not a rubber stamp).
"""
import json
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
BASELINE_FILE = BACKEND_DIR / "dependency_baseline.json"


def run_pip_audit() -> dict:
    result = subprocess.run(
        [sys.executable, "-m", "pip_audit", "-r", "requirements.txt", "-f", "json"],
        cwd=BACKEND_DIR, capture_output=True, text=True,
    )
    # pip-audit exits 1 when it finds vulnerabilities — that's expected, not
    # a tool failure. A genuine tool failure (network, bad requirements.txt)
    # produces no parseable JSON on stdout, which json.loads below catches.
    return json.loads(result.stdout)


def current_advisories(audit: dict) -> dict:
    out = {}
    for dep in audit.get("dependencies", []):
        ids = sorted({v["id"] for v in dep.get("vulns", [])})
        if ids:
            out[dep["name"]] = ids
    return out


def main() -> int:
    update = "--update" in sys.argv
    audit = run_pip_audit()
    current = current_advisories(audit)

    baseline = json.loads(BASELINE_FILE.read_text()) if BASELINE_FILE.exists() else {}

    if update:
        for pkg, ids in current.items():
            if pkg in baseline:
                baseline[pkg]["accepted_ids"] = ids
        BASELINE_FILE.write_text(json.dumps(baseline, indent=2) + "\n")
        print(f"Updated accepted_ids for {len(current)} package(s) already in the baseline. "
              f"New packages still need a manual reachability write-up added by hand.")
        return 0

    problems = []
    for pkg, ids in current.items():
        if pkg == "_comment":
            continue
        entry = baseline.get(pkg)
        if entry is None:
            problems.append(f"{pkg}: not in dependency_baseline.json at all "
                             f"(advisories: {', '.join(ids)}) — new vulnerable dependency, needs triage")
            continue
        accepted = set(entry.get("accepted_ids", []))
        new_ids = [i for i in ids if i not in accepted]
        if new_ids:
            problems.append(f"{pkg}: new advisory id(s) not yet triaged: {', '.join(new_ids)}")

    if problems:
        print("FAIL: dependency advisories outside the accepted baseline:")
        for p in problems:
            print(f"  - {p}")
        print("\nTriage each (reachability against this codebase's actual usage, severity, fix "
              "availability), add the reasoning to SECURITY_DEPENDENCY_DEBT.md, then either patch "
              "or re-run with --update to accept it explicitly.")
        return 1

    print(f"OK: {sum(len(v) for v in current.values())} advisories across {len(current)} package(s), "
          f"all within the accepted baseline.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
