"""Local, runnable reproduction of the X-Forwarded-For trust gap and its
fix — see FORWARDED_ALLOW_IPS_SETUP.md and TRUST_RELEASE_FINAL_REPORT.md
§11.4/§11.9.

Spawns a real uvicorn subprocess (not the in-process TestClient, which
never runs uvicorn's own ProxyHeadersMiddleware) under three different
--forwarded-allow-ips values and sends the exact same forged
X-Forwarded-For header to each. In this local sandbox every probe
connects over loopback, so the caller's real TCP peer is always
127.0.0.1 — the discriminating factor being tested is whether the
CONFIGURED trust list matches that real peer, not the literal string
"127.0.0.1":

  1. --forwarded-allow-ips 10.0.0.1   (a value that does NOT match the
     real caller) simulates an untrusted/misconfigured caller — expect
     the forged header to be IGNORED, client_host == the real peer.
  2. --forwarded-allow-ips 127.0.0.1  (matches the real caller, the same
     shape as this codebase's new default) simulates a correctly
     configured trusted proxy — expect the forged header to be HONOURED.
  3. --forwarded-allow-ips '*'        (the OLD hardcoded value this
     codebase shipped with) trusts every caller unconditionally — expect
     the forged header to be HONOURED regardless of source, proving the
     old default really was exploitable by anyone, not just a listed
     proxy.

On a real internet-facing deployment, no genuine external client ever
connects via 127.0.0.1 — so this codebase's actual default of
FORWARDED_ALLOW_IPS=127.0.0.1 (case 1's shape, not case 2's) means
"trust nobody by default," exactly as intended. Case 2 exists here only
to prove the trust mechanism itself works correctly when the configured
value DOES match the real proxy, which is the state a correctly
configured production deployment should be in once FORWARDED_ALLOW_IPS
is set to that proxy's real outbound IP.

Usage: python scripts/verify_forwarded_allow_ips.py
Exit code 0 = all three assertions passed. Non-zero = something regressed.
"""
import subprocess
import sys
import time
import textwrap
import tempfile
import os
import urllib.request

PROBE_APP = textwrap.dedent("""
    from fastapi import FastAPI, Request
    app = FastAPI()

    @app.get("/whoami")
    async def whoami(request: Request):
        return {"client_host": request.client.host if request.client else None}
""")

FORGED_IP = "203.0.113.66"


def _run_probe(forwarded_allow_ips: str, port: int) -> str:
    with tempfile.TemporaryDirectory() as d:
        app_path = os.path.join(d, "probe_app.py")
        with open(app_path, "w") as f:
            f.write(PROBE_APP)
        proc = subprocess.Popen(
            [
                sys.executable, "-m", "uvicorn", "probe_app:app",
                "--host", "127.0.0.1", "--port", str(port),
                "--proxy-headers", "--forwarded-allow-ips", forwarded_allow_ips,
                "--log-level", "warning",
            ],
            cwd=d, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            deadline = time.time() + 10
            last_err = None
            while time.time() < deadline:
                try:
                    req = urllib.request.Request(
                        f"http://127.0.0.1:{port}/whoami",
                        headers={"X-Forwarded-For": FORGED_IP},
                    )
                    with urllib.request.urlopen(req, timeout=2) as resp:
                        import json
                        return json.loads(resp.read())["client_host"]
                except Exception as e:
                    last_err = e
                    time.sleep(0.3)
            raise RuntimeError(f"probe server never came up: {last_err}")
        finally:
            proc.terminate()
            proc.wait(timeout=5)


def main() -> int:
    ok = True

    print("Case 1 — untrusted caller (--forwarded-allow-ips 10.0.0.1, real peer is 127.0.0.1)...")
    host_untrusted = _run_probe("10.0.0.1", port=18901)
    print(f"  request.client.host = {host_untrusted!r}")
    if host_untrusted == FORGED_IP:
        print("  FAIL: forged header was honoured even though the caller isn't in the trust list.")
        ok = False
    else:
        print(f"  PASS: forged header ignored — request.client.host stayed the real peer ({host_untrusted!r}).")

    print("Case 2 — trusted caller (--forwarded-allow-ips 127.0.0.1, matches the real peer)...")
    host_trusted = _run_probe("127.0.0.1", port=18902)
    print(f"  request.client.host = {host_trusted!r}")
    if host_trusted != FORGED_IP:
        print("  FAIL: expected the forged header to be honoured once the caller IS in the trust list.")
        ok = False
    else:
        print("  PASS: forged header honoured for a listed, trusted caller — the mechanism works as designed.")

    print("Case 3 — old hardcoded value (--forwarded-allow-ips '*', trust everyone)...")
    host_star = _run_probe("*", port=18903)
    print(f"  request.client.host = {host_star!r}")
    if host_star != FORGED_IP:
        print("  FAIL: expected '*' to reproduce the original vulnerability, but it didn't.")
        ok = False
    else:
        print("  PASS: '*' reproduces the original vulnerability — confirms the old default was really exploitable by ANY caller.")

    print()
    print("Conclusion: 127.0.0.1 trusts loopback peers only, including a local reverse proxy. "
          "These probes verify Uvicorn's mechanism, not the production network topology. "
          "Confirm the real immediate proxy peer and its header-stripping behavior before rollout.")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
