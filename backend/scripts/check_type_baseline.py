#!/usr/bin/env python3
"""Differential type-check gate.

server.py's transitive imports pull in almost the entire backend, so
`mypy server.py` type-checks the whole untyped codebase in one shot —
784 pre-existing findings as of the "Trust Release" baseline (see
TRUST_RELEASE_FINAL_REPORT.md), the overwhelming majority of which are a
single reproduced false-positive: motor's `Database`/`Collection` stubs
carry no generic document type here (`db = client[DB_NAME]` in
database.py has no `Document` type param), so mypy infers `None`/`Never`
for `await db.<collection>.find_one(...)` and flags the assignment
(`func-returns-value`) or a later `.get()` on it (`call-overload`) —
verified directly:

    async def f(x):
        doc = await db.customers.find_one({"id": x}, {"_id": 0})
        return doc                          # func-returns-value
    async def g(x):
        doc = await db.customers.find_one({"id": x}, {"_id": 0}) or {}
        return doc.get("name")              # call-overload

reproduces both on a two-line throwaway file with no other code — so
literally any new `find_one`/`find` call anywhere in this codebase adds
1-2 findings to the total regardless of whether the surrounding code is
correct. A whole-codebase fix means giving `db` (and every collection
accessor built from it) a real generic `Document`/`TypedDict` type across
~150 route/service files — exactly the "risky whole-codebase type
rewrite" the Trust Release mandate says not to attempt as a rider on a
security pass.

So this gate does not require the mypy error count to never move — new
legitimate code will keep adding a couple of these every time it reads a
document — it requires that it never *decrease in rigor*: the recorded
baseline (mypy_baseline_count.txt) is the accepted floor, checked in
alongside this script. A PR that pushes the count higher must either fix
what it added or deliberately raise the recorded baseline in the same
diff (so a reviewer sees the number move, rather than CI silently
absorbing debt). Zero new *error codes* (a check this script also makes)
is the actual regression signal that matters: a new mypy error class
appearing that was never in the baseline is far more likely to be a real
bug than the 421 already-known func-returns-value/call-overload noise.

Usage: python scripts/check_type_baseline.py [--update]
  --update   rewrite mypy_baseline_count.txt to the current count instead
             of failing (use when a reviewed PR deliberately accepts a
             higher count, same convention as SECURITY_DEPENDENCY_DEBT.md).
"""
import re
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
BASELINE_FILE = BACKEND_DIR / "mypy_baseline_count.txt"
CODES_FILE = BACKEND_DIR / "mypy_baseline_codes.txt"


def run_mypy() -> str:
    result = subprocess.run(
        [sys.executable, "-m", "mypy", "--ignore-missing-imports", "server.py"],
        cwd=BACKEND_DIR, capture_output=True, text=True,
    )
    output = result.stdout + result.stderr
    if result.returncode not in (0, 1) or (result.returncode == 1 and not count_errors(output)):
        raise RuntimeError(f"mypy did not complete successfully (exit {result.returncode}):\n{output}")
    return output


def count_errors(output: str) -> int:
    return len(re.findall(r"^\S+\.py:\d+: error:", output, re.MULTILINE))


def error_codes(output: str) -> set:
    return set(re.findall(r"\[([a-z-]+)\]\s*$", output, re.MULTILINE))


def main() -> int:
    update = "--update" in sys.argv
    output = run_mypy()
    current_count = count_errors(output)
    current_codes = error_codes(output)

    if update:
        BASELINE_FILE.write_text(f"{current_count}\n")
        CODES_FILE.write_text("\n".join(sorted(current_codes)) + "\n")
        print(f"Updated baseline: {current_count} errors, {len(current_codes)} error codes.")
        return 0

    if not BASELINE_FILE.exists():
        print(f"No baseline recorded at {BASELINE_FILE} — run with --update to create one.")
        return 1

    baseline_count = int(BASELINE_FILE.read_text().strip())
    baseline_codes = set(CODES_FILE.read_text().split()) if CODES_FILE.exists() else set()

    new_codes = current_codes - baseline_codes
    ok = True

    if new_codes:
        print(f"FAIL: {len(new_codes)} new mypy error code(s) not in the accepted baseline: "
              f"{sorted(new_codes)}")
        print("A new error CATEGORY (not just more of an already-accepted one) usually means "
              "a real bug, not stub noise — investigate before widening the baseline.")
        ok = False

    if current_count > baseline_count:
        print(f"FAIL: mypy error count {current_count} exceeds recorded baseline {baseline_count} "
              f"(+{current_count - baseline_count}).")
        print("Fix the new findings, or if they're the known motor-stub false-positive class "
              "(func-returns-value / call-overload on a db.<collection>.find_one/find call — see "
              "this script's module docstring), re-run with --update and note why in the PR "
              "description, same convention as SECURITY_DEPENDENCY_DEBT.md.")
        ok = False

    if ok:
        print(f"OK: {current_count} errors (baseline {baseline_count}), "
              f"no new error codes ({len(current_codes)} known categories).")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
