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
2. **Token storage on Android/iOS — now genuinely hardened.** An earlier
   pass of this document claimed `@capacitor/preferences` was
   "EncryptedSharedPreferences-backed" on Android; that was checked
   against the installed plugin's actual native source during the iOS
   pass and found false (plain `SharedPreferences`/`UserDefaults`,
   identical security to `localStorage`). This pass replaces it with
   `capacitor-secure-storage-plugin`, verified the same way — by reading
   its own native source, not trusting its name or README — rather than
   repeating that earlier mistake:
   - **Android**: `PasswordStorageHelper.java` generates an RSA keypair
     inside `AndroidKeyStore` (`KeyStore.getInstance("AndroidKeyStore")`)
     and uses it to RSA-encrypt (`Cipher`, `RSA_ECB_PKCS1_PADDING`) the
     value before it's written to `SharedPreferences` — the stored bytes
     are ciphertext, and the decrypting key never leaves the Keystore.
     The plugin's own fallback to plain base64 only applies below API 18;
     this app's `minSdkVersion` is 24, so that path is unreachable here.
   - **iOS**: `SecureStoragePlugin.swift` stores through
     `KeychainWrapper`/`SwiftKeychainWrapper` — the real system Keychain,
     not `UserDefaults`.
   `SecureStorageService.getToken()` migrates an existing
   `@capacitor/preferences`-stored token into the new store on first
   read (an install updated from before this pass isn't silently signed
   out), tested with the native plugins mocked (5 Jest tests — the
   plugins themselves can't run outside a device/emulator). The
   `localStorage` mirror for the ~20 pre-existing pages that read
   `localStorage.getItem('nua_token')` directly is unchanged by this —
   see `MOBILE_DESKTOP_BACKLOG.md` item 2 for that separate, still-open
   gap. **Not yet verified**: this has not been exercised on a real
   device or emulator — e.g. a real login round-trip through the new
   plugin — only against mocked unit tests and a successful Gradle/SPM
   compile.
3. **Biometric reauthentication for sensitive actions** (refunds, voids,
   sensitive settings — directive Phase 5) — **the interface exists, no
   biometric hardware/API is wired into it; all three named categories
   now have at least one real call site gated.** `BiometricService`
   reports `isAvailable() === false` on every platform (no Face ID/Touch
   ID/BiometricPrompt/Windows Hello plugin is installed — same "don't
   fake an unsupported provider" discipline as `PaymentTerminalService`).
   What actually gates a sensitive action today is real and
   server-verified: `POST /api/auth/verify-sensitive-action` accepts
   either the acting user's own PIN or a manager/owner's PIN from the
   SAME business (tenant-checked independently of the role check — a PIN
   from another business is rejected regardless of how privileged its
   owner is in their own business), mirroring the existing off-roster-
   login approval pattern. Wired in: `RefundDialog.jsx` (refund);
   `CompVoid.jsx` and `POSTerminal.jsx`'s quick comp/void dialog (void);
   `SecurityCompliance.jsx`'s 2FA-disable and GDPR erase, and
   `EFTPOSTerminals.jsx`'s terminal removal (sensitive settings). This is
   a deliberately bounded set, not an exhaustive audit of every settings
   page — see `MOBILE_DESKTOP_BACKLOG.md` item 27 for what's still
   unreviewed.
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

5. **Minimum-client-version gate** (directive Phase 11) — `GET /api/version`
   is public; `VersionGateMiddleware` rejects a request carrying an
   `X-App-Version` header below `version.MIN_SUPPORTED_APP_VERSION` with
   426, checked before auth/rate-limit/license do any work. Fails open
   on a missing header — no client in production sends one yet, so this
   changes nothing for anything already deployed; it's a real gate for
   whenever a native build starts reporting its version, not a
   retroactive enforcement switched on for everyone.
6. **Client telemetry never persists sensitive fields, even if sent** —
   `record_client_event` (`services/observability.py`) redacts any key
   that looks like a password/token/PIN/card field in its `data` payload
   before writing `client_event_log`, independent of whether any current
   frontend call site would ever send one (none do). Event `type` is
   checked against a fixed, known set — an unrecognized type is silently
   dropped, not stored — so a client bug (or something worse) can't
   smuggle an arbitrary label into a collection an owner reads back.

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

- **Encryption-at-rest for the stored token, on Android or iOS** — item 2
  above now closes this; `capacitor-secure-storage-plugin` is installed
  and wired into `SecureStorageService`, verified at the native-source
  level. What remains open: it hasn't run on a real device/emulator yet,
  only against mocked unit tests and a successful compile.
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
