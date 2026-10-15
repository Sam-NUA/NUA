# Device identity and terminal sessions

Current implementation: [15 October review](TERMINAL_DURABILITY_REVIEW_2026-10-15.md), stacked PR #24. A business owns its device registry; a terminal is shared across staff shifts. Device IDs are server-assigned registry identifiers, not cryptographic hardware attestation.

## Registration and first-session binding

Native sign-in verifies credentials and required MFA first. The server issues a unique `sessionId`. Before protected screens or financial queue activation, AuthContext registers an unknown terminal for the authenticated business, calls `POST /auth/bind-device`, stores the returned bound token in OS storage, and activates that business's offline scope.

Binding checks the device's exact business and active status. Its immutable `terminal_sessions` record uses the session ID as Mongo `_id`; it cannot be moved to another device. Already-issued access/refresh tokens with that session ID consult the same binding, so the original first-login token cannot evade later device revocation. Password, MFA and PIN login all enforce device ownership. A manager-approved PIN login checks the device before recording its roster override.

Every access and refresh rechecks the device's active status and current account membership. A revoked, missing or foreign device is rejected. A moved account's old bound session cannot become authority in its new business. No role, permission or MFA requirement is widened.

## Multiple businesses and compatibility

Each adapter stores a business→device map. `X-Device-Map` is only a local routing hint: after credentials/MFA, the server selects and validates the current business's entry. Another business's ID never selects a tenant. A selected revoked/unknown ID fails closed; the client does not automatically replace it.

`X-Device-Id` remains a strict single-device compatibility header. A legacy native token without a session ID requires fresh login; a successful original-business login remembers the validated device in the new map. Reassignment when that business is no longer accessible requires operator-assisted ownership verification. Clearing a revoked ID automatically is deliberately unsupported.

## Endpoints

| Endpoint | Who / effect |
|---|---|
| `POST /api/devices/register` | Authenticated staff; stamps the verified business. |
| `POST /api/auth/bind-device` | Authenticated session; binds only an owned, active device. |
| `GET /api/devices` | Owner/manager; current-business terminals only. |
| `POST /api/devices/{id}/heartbeat` | Authenticated staff; owned active device timestamp only. |
| `POST /api/devices/{id}/revoke` | Owner/manager; owned device only. |

Settings → Devices & printing lists/revokes terminals and exports only the active business's offline review records. Heartbeats run every five minutes after session binding; they no longer create best-effort unbound sessions.

## Offline boundary

A running, server-verified session may preserve eligible cash intents during a connection outage until its access token expires. Native cold restart always waits for online server re-verification before protected operations or replay. Queues remain durable; cached user profiles never become login authority. Windows uses OS-encrypted main-process persistence scoped by business and device; browser/Capacitor queue storage remains IndexedDB.

Physical hardware attestation, terminal reassignment UI, secure offline cold-start authorisation and full iOS financial acceptance remain open. See the linked review for validation and precise limits.
