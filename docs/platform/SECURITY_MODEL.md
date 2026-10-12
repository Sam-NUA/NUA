# Security model (multiplatform additions)

The backend's existing tenant isolation and RBAC (JWT + `tenant_scope_filter`'s
fail-closed predicate, `deps.require_permission`) are unchanged by this
work and remain the actual security boundary — see
`CURRENT_ARCHITECTURE_AUDIT.md`'s backend section. Nothing below weakens,
bypasses, or replaces any of that; this document covers what's new.

## The non-negotiable rule, restated and verified

> Mobile or desktop applications must NEVER be treated as trusted clients.
> The FastAPI backend remains authoritative.

Verified true of everything added this pass:
- Device registration (`POST /api/devices/register`) requires an existing
  valid session — a device cannot mint itself an identity, only an
  already-authenticated user can claim one.
- The `X-Device-Id` header a client sends at login is **looked up
  server-side** against the `devices` collection — the client asserting an
  id proves nothing by itself; only a server-side match against an
  `active` row grants anything (and a mismatch/unknown id fails closed,
  rejecting the login, not falling back to "treat as unregistered").
- Device revocation enforcement lives in `RequireAuthMiddleware` and
  `get_current_user` — server-side, on every request, not a client-side
  check the app could skip.
- `SecureStorageService` (Preferences on Android) is better-protected
  *storage* for the same bearer token the backend already issues and
  validates the same way regardless of where it's stored — it does not
  change what the token proves or who's trusted.

## What's actually new here

1. **Device revocation** — closes a real gap that didn't exist before
   this pass: previously, a stolen/compromised terminal's session was
   only as revocable as the access token's own 8-hour expiry (or a full
   password change for every user who'd ever logged in on it). Now an
   owner can revoke a specific device and have it rejected on its very
   next request. See `DEVICE_IDENTITY_MODEL.md`.
2. **Token storage hardening on Android** — `@capacitor/preferences`
   (EncryptedSharedPreferences-backed) instead of plain `localStorage` for
   the primary read/write path. **Caveat, stated plainly**: a
   compatibility mirror into `localStorage` was added so ~20 pre-existing
   pages that read `localStorage.getItem('nua_token')` directly keep
   working (see `MOBILE_DESKTOP_BACKLOG.md`) — as long as that mirror
   exists, the token is *also* sitting in plain, unencrypted WebView
   storage, so this is a partial hardening, not a complete one. Full
   benefit requires migrating those ~20 call sites to stop reading
   `localStorage` directly, which is backlog, not done this pass.
3. **Biometric reauthentication for sensitive actions** (refunds, voids,
   sensitive settings — directive Phase 5) — **not implemented this
   pass**. No `BiometricService` exists yet; this is a real gap against
   the master directive's own Phase 5 ask, named here rather than silently
   dropped.

## Threat model notes specific to a POS terminal

- A registered device is shared infrastructure, not tied to one staff
  member's identity the way the user account itself is — revoking it
  logs out *whoever is currently signed in on it*, which is the correct
  behavior for "this tablet was stolen," not "this one employee is fired"
  (that's the existing account-deactivation path, untouched).
- PIN login (the primary sign-in method on a shared terminal) still has
  no cryptographic binding to the device beyond the optional `X-Device-Id`
  header — a PIN is inherently weaker than a password and is explicitly
  documented elsewhere in this codebase (`TRUST_RELEASE_FINAL_REPORT.md`,
  prior session's audit work) as not a replacement for real account
  security, only a fast-switching convenience. This work doesn't change
  that posture, just adds device-level revocability on top of it.

## Explicitly not done, and why

- **Keystore-hardware-backed storage** (vs. EncryptedSharedPreferences) —
  would need a dedicated secure-enclave plugin; `@capacitor/preferences`
  was judged sufficient for a v1 given the mirror-to-localStorage caveat
  above already caps the realistic security ceiling until that's cleaned
  up too.
- **Certificate pinning** for native API calls — not implemented; the app
  talks to `https://app.nuapos.com.au` over standard TLS, same trust model
  as the web app.
- **Jailbreak/root detection** — not implemented, not requested.
