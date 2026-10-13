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
- `SecureStorageService` (Preferences on Android/iOS — see the
  correction below, it's not actually better-protected storage; a real
  OS-encrypted store on Windows, see below) is for the same bearer token
  the backend already issues and validates the same way regardless of
  where it's stored — it does not change what the token proves or who's
  trusted.

## What's actually new here

1. **Device revocation** — closes a real gap that didn't exist before
   this pass: previously, a stolen/compromised terminal's session was
   only as revocable as the access token's own 8-hour expiry (or a full
   password change for every user who'd ever logged in on it). Now an
   owner can revoke a specific device and have it rejected on its very
   next request. See `DEVICE_IDENTITY_MODEL.md`.
2. **Token storage abstraction on Android/iOS, CORRECTED claim** — an
   earlier pass of this document claimed `@capacitor/preferences` was
   "EncryptedSharedPreferences-backed" on Android. That was checked
   against the installed plugin's actual native source during the iOS
   pass and found **false**: it's plain
   `context.getSharedPreferences(group, MODE_PRIVATE)` on Android and
   plain `UserDefaults.standard` on iOS — neither encrypted at rest,
   neither touching Android Keystore or iOS Keychain. The real security
   property is identical to `localStorage`: sandboxed to this app, not
   encrypted beyond that. The compatibility mirror into `localStorage`
   (so ~20 pre-existing pages that read `localStorage.getItem('nua_token')`
   directly keep working — see `MOBILE_DESKTOP_BACKLOG.md`) therefore
   costs nothing security-wise that wasn't already true. **No token
   storage hardening has actually happened on either platform yet** —
   the `SecureStorageService` abstraction exists and is correctly
   positioned to swap in a real Keystore/Keychain-backed plugin later
   without touching call sites again, but that plugin isn't chosen or
   installed. Tracked honestly in `MOBILE_DESKTOP_BACKLOG.md` as not
   done, not as "v2 hardening" of something already secure.
3. **Biometric reauthentication for sensitive actions** (refunds, voids,
   sensitive settings — directive Phase 5) — **not implemented this
   pass**. No `BiometricService` exists yet; this is a real gap against
   the master directive's own Phase 5 ask, named here rather than silently
   dropped.
4. **Windows (Electron) host isolation** — built and tested independently
   (originally by Codex on `feat/windows-foundation`, folded in here):
   `apps/windows/src/main.cjs` runs the renderer sandboxed
   (`sandbox: true`, `contextIsolation: true`, `nodeIntegration: false`),
   serves only bundled assets over a custom `nua://` origin with a strict
   CSP (`default-src 'none'`, `script-src 'self'`, no remote script
   execution), denies every `window.open`/external navigation/webview
   attach and every permission check/request outright, and validates
   every IPC call's sender frame/window before running its handler
   (`assertSender` in `policy.cjs`) — a compromised or spoofed renderer
   frame cannot invoke a native command at all, let alone one for another
   window. `SecureStorageService.setToken`/`DeviceIdentityService
   .register` route through `nua:token-*`/`nua:device-id-*`, backed by
   `EncryptedStore` (atomic temp-file-then-rename writes) +
   `windowsCrypto` (real Windows DPAPI via Electron's `safeStorage`,
   fails closed with no plaintext fallback if OS encryption is
   unavailable) — **this genuinely is encrypted at rest**, unlike the
   Android/iOS claim corrected in item 2 above. The Chromium session
   itself (`session.fromPartition('nua-windows-foundation')`, no
   `persist:` prefix) stays in-memory by design, so nothing Chromium
   manages on its own survives a restart — only what's explicitly routed
   through the encrypted store does.

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

- **Any encryption-at-rest for the stored token, on Android or iOS** —
  `@capacitor/preferences` does not provide this (see the corrected claim
  above); a dedicated Keystore/Keychain-backed secure-storage plugin is
  needed and not yet chosen or installed. This is a real, open gap, not
  a "v1 judged sufficient" tradeoff — the earlier version of this
  document described it as the latter incorrectly. Windows does not
  share this gap — see item 4 above.
- **Windows offline queue is not wired to the live app** —
  `packages/platform-core/queue.cjs`'s `CashOrderQueue` is a real,
  independently tested (scope-fenced to a server-verified `{businessId,
  userId, deviceId}` tuple, exclusive/serialized writes, exponential
  backoff, conflict retention) primitive, but nothing in the shared
  frontend calls it yet. Wiring it in requires the same legacy-
  IndexedDB-quarantine work the Android/iOS offline queue already needs
  (see `OFFLINE_SYNC_ARCHITECTURE.md`) — doing that hastily, just to
  claim "Windows offline works," is exactly the kind of rushed
  integration that risks the tenant-isolation regression this document's
  opening paragraph promises never to introduce. Left as a primitive,
  not integrated, intentionally.
- **Certificate pinning** for native API calls — not implemented; the app
  talks to `https://app.nuapos.com.au` over standard TLS, same trust model
  as the web app.
- **Jailbreak/root detection** — not implemented, not requested.
