# Device identity model

Implemented this pass: `backend/models/device.py`, `backend/routes/devices.py`,
`backend/services/device_auth.py`, wiring in `backend/routes/auth.py`,
`backend/routes/staff_management.py`, `backend/server.py`. Frontend:
`frontend/src/platform/*/DeviceIdentityService.js`,
`frontend/src/hooks/useDeviceRegistration.js`.

## Hierarchy

```text
business (businessId)
   │
 location (locationId, optional)
   │
 device  (this doc)
   │
 staff session (the JWT issued once this device, if registered, signs in)
```

A device is not tied to one staff member — it's the physical
tablet/terminal, shared across shifts. `terminalId` (optional, on the
`Device` model) is for the case where a venue wants to additionally name
*which* POS register/till a device is, distinct from the device itself
(e.g. redeploying the same physical tablet to a different till).

## Schema (`backend/models/device.py`)

```text
id, businessId, locationId?, platform (android|ios|windows|web),
deviceName, deviceModel?, osVersion?, appVersion?, terminalId?,
capabilities: [str], status (active|revoked),
registeredBy, registeredByName?, createdAt, lastSeenAt?,
revokedAt?, revokedBy?
```

## Endpoints (`backend/routes/devices.py`)

| Endpoint | Who |
|---|---|
| `POST /api/devices/register` | Any authenticated staff member — a cashier opening the app on a new tablet must be able to claim it; the device then belongs to the business, not to them personally. |
| `GET /api/devices` | Owner/manager only. |
| `POST /api/devices/{id}/heartbeat` | Any authenticated staff member whose business owns the device. Cheap — just a timestamp. |
| `POST /api/devices/{id}/revoke` | Owner/manager only. |

All four are tenant-scoped via `tenant_scope_filter`/`tenant_owns_strict`,
same as every other collection in this codebase.

## Login-time device check

`routes/auth.py`'s `_resolve_device_id(request)` reads an optional
`X-Device-Id` header on **both** `/auth/login` and `/auth/2fa/challenge`,
and `routes/staff_management.py`'s `pin_login`/`approve_pin_login` do the
same. If present:
- **Revoked or unknown → the login itself is rejected (403)**, fail-closed,
  matching `tenant_scope_filter`'s own philosophy elsewhere in this
  codebase (an unrecognized id is never treated as "no device claim" —
  that would let a stale/garbage header silently bypass the check).
- **Active and known → embedded into both the access token and the
  refresh token** (`deviceId` claim).

A session with no `X-Device-Id` header at all (web, or a device before its
first registration) behaves exactly as if this feature didn't exist —
nothing about existing login behavior changed for those sessions.

## Revocation is real-time, not "on next login"

This is the part that's easy to build incompletely: a registry that
tracks devices but doesn't actually gate anything already-issued isn't a
revocation system, it's a list.

- `server.py`'s `RequireAuthMiddleware` and `routes/auth.py`'s
  `get_current_user` (the two places that validate an access token on
  every request) both check `deviceId` against `services/device_auth.py`'s
  `is_device_revoked_or_missing()` — **on that token's very next request**,
  not when it next expires (up to 8 hours later) or next refreshes.
- `routes/auth.py`'s `/refresh` endpoint also carries `deviceId` through
  from the refresh token into the newly-minted access token, and checks
  revocation itself before minting. Without this, a revoked device's
  session would silently regain a valid access token on its very next
  refresh — up to 7 more days of the revocation being meaningless. This
  was caught and fixed during this pass, not assumed correct — see
  `backend/tests/inprocess/test_device_identity.py::test_refresh_preserves_device_binding_so_revocation_survives_token_refresh`.

## Frontend wiring

`frontend/src/hooks/useDeviceRegistration.js`, wired into `App.js`'s
`ProtectedRoutes`: on native platforms only (`isNative()` — Android, iOS,
or the Windows desktop shell), once a session exists, registers the
device if it hasn't already and sends a heartbeat every 5 minutes. A
no-op on web — exactly pre-existing behavior there.

- Android/iOS (`platform/capacitor/DeviceIdentityService.js`): real
  OS-reported info via `@capacitor/device`'s `Device.getInfo()`, not
  anything the UI has to ask the user to type in.
- Windows (`platform/electron/DeviceIdentityService.js`): the id itself
  is assigned by the backend exactly as for every other platform; there's
  no OS-device-info API exposed by `apps/windows`'s bridge to pull a real
  model/manufacturer string from, so `deviceName` falls back to the
  machine's real hostname (`os.hostname()`, returned by `nua:info`) rather
  than anything fabricated. The returned id persists via `nua:device-id-*`
  — the same OS-encrypted store as the auth token (see
  `SECURITY_MODEL.md`), not the host's in-memory Chromium session.

## What's NOT done this pass (see MOBILE_DESKTOP_BACKLOG.md)

- No UI surface for owners to see/revoke devices from Settings yet — the
  API exists, a page calling it doesn't.
- No `locationId` assignment flow — the field exists on the model, nothing
  sets it yet (multi-location businesses would need this before revocation
  is meaningful per-venue rather than per-business).
- Windows device registration has never run against a real packaged
  build — verified only by local Node unit tests and the frontend/backend
  test suites, plus CI's `windows-latest` runner exercising the host
  shell itself (not a full login→register flow end to end yet).
