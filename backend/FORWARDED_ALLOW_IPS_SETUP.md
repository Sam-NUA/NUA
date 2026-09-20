# Configuring `FORWARDED_ALLOW_IPS` (proxy trust)

## What changed and why

This backend runs uvicorn with `--proxy-headers`, which lets a reverse
proxy in front of it tell FastAPI the guest's *real* IP via the
`X-Forwarded-For` header (otherwise every request would appear to come
from the proxy's own address). uvicorn only honours that header from a
peer whose actual TCP source IP is in `--forwarded-allow-ips` — everyone
else's `X-Forwarded-For` is ignored.

Until this fix, `--forwarded-allow-ips` was hardcoded to `'*'`: trust
that header from *any* caller, not just a real proxy. On a deployment
with no such proxy in front of it (or one that doesn't strip inbound
`X-Forwarded-For` before forwarding), that meant any internet client
could set `X-Forwarded-For` to whatever it wanted and `request.client.host`
would become that spoofed value inside the app. This was empirically
reproduced during the Trust Release audit: a minimal FastAPI app run with
these exact flags, hit with plain `curl -H "X-Forwarded-For: <anything>"`
and zero real proxy anywhere in the loop, showed `request.client.host`
becomes whatever the client sends.

That mattered because several protections in this codebase are keyed on
`request.client.host`:
- `server.py`'s `RateLimitMiddleware` (guest-facing rate limits on
  `/api/public/*`, `/api/table/*`, the voice webhook)
- `routes/auth.py`'s `forgot_password` brute-force throttle

(`routes/auth.py`'s login/2FA lockouts were separately fixed to key on
the account instead of the IP — see `TRUST_RELEASE_FINAL_REPORT.md`
§11.4 — so those two are safe regardless of this setting. Everything
else above is not.)

An attacker who can set `X-Forwarded-For` could rotate it per request
and bypass every one of those IP-keyed limits.

## The fix

`--forwarded-allow-ips` now reads from the `FORWARDED_ALLOW_IPS`
environment variable, defaulting to `127.0.0.1` (trust loopback peers only) instead
of `*` (trust everything) when the variable isn't set. With the safe
default, `request.client.host` reflects the real TCP peer — no rewriting
happens at all unless you explicitly configure it — which is safe on any
topology, including an internet-facing container with nothing in front
of it. The cost of the safe default: if a real reverse proxy *is* sitting
in front of this container, every request will appear to uvicorn to come
from the proxy's own IP, and this variable must be set correctly to
enable the header rewrite.

## What you need to determine before setting it

**Do not set `FORWARDED_ALLOW_IPS` to anything other than the default
until you can answer this with certainty**, because a wrong answer either
leaves the bypass in place (setting it too permissively) or breaks the
app's ability to see the real client IP at all (leaving it unset when a
real proxy is in front of you, or setting it to the wrong IP):

1. **What sits between the internet and this container?** Concretely:
   is there a load balancer, CDN, or reverse proxy (Railway's edge,
   Fly.io's edge/Anycast, a Cloudflare proxy, an nginx/Caddy instance you
   run yourself) that terminates the inbound connection and makes its
   *own* new connection to this container? Or does this container receive
   connections directly from the internet?

2. **If something sits in front of it: does that layer set/overwrite
   `X-Forwarded-For` itself, or does it just pass through whatever the
   original client sent?** A proxy that blindly forwards the header
   without stripping/overwriting it does not close the gap — an attacker
   can still set the header value; the proxy is not authenticating it.
   You need the layer immediately in front of uvicorn to be the one
   *setting* the header from its own view of the TCP connection, not
   relaying the client-supplied value unchanged.

3. **What is that layer's own outbound IP address (or address range),
   as seen by this container?** This is the value `--forwarded-allow-ips`
   needs — not the proxy's public-facing domain or the platform's
   published edge IP list (those are the addresses *clients* connect to,
   not necessarily what the proxy connects to *this container* from,
   especially on a platform that proxies internally). Confirm this
   empirically if possible: log `request.client.host` for a real request
   and check what it shows without the header-trust flag enabled.

Neither `Railway Setup.md` nor `Fly.io Setup.md` in this repo confirms
which platform (if any) is the actual live-serving edge for this
deployment, so this cannot be answered from the repository alone — it
requires someone with access to the actual running deployment's
infrastructure.

## How to set it once you know

```
FORWARDED_ALLOW_IPS=<comma-separated IPs or CIDRs>
```

Examples:
- A single known proxy IP: `FORWARDED_ALLOW_IPS=10.0.0.5`
- A private network range the proxy lives in: `FORWARDED_ALLOW_IPS=10.0.0.0/8`
- Multiple specific addresses: `FORWARDED_ALLOW_IPS=10.0.0.5,10.0.0.6`

Only use the literal `*` (trust every peer) if you have confirmed there
is no way for a request to reach this container except through a proxy
that itself strips/overwrites `X-Forwarded-For` — i.e., the container has
no other network path exposed at all. This is rarely true on a
platform-hosted single-container deployment; prefer an explicit IP/CIDR.

## Automated local reproduction

`scripts/verify_forwarded_allow_ips.py` spawns real uvicorn subprocesses
(not the in-process test client, which never runs uvicorn's own
`ProxyHeadersMiddleware`) and empirically proves the mechanism:

```
$ python scripts/verify_forwarded_allow_ips.py
Case 1 — untrusted caller (--forwarded-allow-ips 10.0.0.1, real peer is 127.0.0.1)...
  PASS: forged header ignored — request.client.host stayed the real peer ('127.0.0.1').
Case 2 — trusted caller (--forwarded-allow-ips 127.0.0.1, matches the real peer)...
  PASS: forged header honoured for a listed, trusted caller — the mechanism works as designed.
Case 3 — old hardcoded value (--forwarded-allow-ips '*', trust everyone)...
  PASS: '*' reproduces the original vulnerability — confirms the old default was really exploitable by ANY caller.
```

This is a local sandbox reproduction of the mechanism, not a substitute
for the real-deployment verification in the next section — every probe
here connects over loopback, so it proves *how the trust list
discriminates*, not what your actual production edge does.

## How to verify it worked

With the sandbox reproduction technique from the audit (a throwaway route
that echoes `request.client.host`, or a temporary log line), confirm:
1. A request carrying a forged `X-Forwarded-For` from a source **not** in
   your configured `FORWARDED_ALLOW_IPS` does **not** change
   `request.client.host` — it still shows the real TCP peer (the proxy).
2. A real client request, arriving through the actual production path,
   **does** show the real guest IP in `request.client.host` — proving the
   trusted proxy's own forwarding still works once configured correctly.

Until both of these are verified against the real deployment, this
repository's own risk assessment (`TRUST_RELEASE_FINAL_REPORT.md`) keeps
PILOT-READY blocked on this specific gap — not as an oversight, but
because guessing the answer wrong is worse than leaving it named as an
open question.
