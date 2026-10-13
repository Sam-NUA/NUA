# Tenant isolation test plan — multiplatform additions

The backend's existing tenant isolation is extensively tested already
(hundreds of cases across `backend/tests/inprocess/`, including a whole
prior session's audit pass — see `docs/launch-audit-2026-10-11/`). This
document covers only what's new in this pass: the device-identity surface.

## Covered this pass (`backend/tests/inprocess/test_device_identity.py`, 9 tests, all passing)

| Scenario | Expected | Test |
|---|---|---|
| Business B lists devices | Business A's devices never appear | `test_devices_are_tenant_isolated` |
| Business B revokes Business A's device | 404, device stays active | `test_devices_are_tenant_isolated` |
| Business B heartbeats Business A's device | 404 | `test_heartbeat_updates_last_seen_and_is_tenant_scoped` |
| Cashier (non-owner/manager) lists/revokes devices | 403 | `test_list_and_revoke_require_owner_or_manager` |
| Any authenticated staff registers a device | 200 — registration itself needs no elevated role | `test_register_device_requires_only_authentication_not_elevated_role` |
| Login with a revoked device's id | 403 at login, not a silent fallback | `test_login_with_a_revoked_device_id_header_is_rejected_outright` |
| Login with an unknown device id | 403 — fail-closed, not "treat as unregistered" | `test_login_with_an_unknown_device_id_header_is_rejected_failclosed` |
| Already-issued token, device revoked mid-session | Next request 401, not "works until expiry" | `test_revoked_device_is_rejected_on_its_very_next_request_not_just_next_login` |
| Token refresh after device binding | New access token still carries the binding; revocation still works post-refresh | `test_refresh_preserves_device_binding_so_revocation_survives_token_refresh` |
| `platform: "ios"` device, full cycle | Register→login→revoke works identically to `"android"` — `ALLOWED_PLATFORMS` listed it before anything tested it | `test_ios_platform_device_registers_and_enforces_revocation_identically_to_android` |
| `platform: "windows"` device, full cycle | Same, for `"windows"` | `test_windows_platform_device_registers_and_enforces_revocation_identically_to_android` |

## Windows's own identity-scoped queue tests (`packages/platform-core/test/queue.test.cjs`)

A second, frontend-side isolation surface, independent of the backend
suite above: `CashOrderQueue`'s scope key is `{businessId, userId,
deviceId}`, and its tests assert the same shape of guarantee the backend
tests assert server-side — "business A's queue never appears in
business B's reads, and switching identity mid-replay stops it" — at the
local-storage layer. Covered: cross-identity read isolation during an
in-flight flush, a foreign-tenant server response never marked synced, a
forbidden (403) response retained for recovery rather than silently
dropped, and `lock()` (logout) rejecting reads outright. Not yet
covered, because the queue isn't wired into the real app (see
`OFFLINE_SYNC_ARCHITECTURE.md`): an actual cross-account replay attempt
through the real POS UI, not just the queue's own unit-test harness.

## Pattern used (matching existing repo convention)

Every cross-tenant test in this file follows the same shape already used
throughout `backend/tests/inprocess/` (e.g.
`test_kitchen_docket_tenant_scope.py`'s `second_business_owner_headers`
fixture): a second, independently-seeded business with its own owner
account, asserting the first business's data/actions are invisible and
unreachable from it — not just "returns an error," but specifically
404/403 (never a 200 with filtered/empty data, which would leak the
distinction between "doesn't exist" and "exists but you can't see it").

## Not yet covered (backlog)

- **Local device storage partitioning** (directive: "Local device storage
  must also be partitioned by authorised business/account context") — no
  test exists for this on the frontend side. The offline queue
  (`lib/offlineQueue.js`) and read cache are a single IndexedDB database
  per app install, not per-business; a single Android tablet used for two
  different businesses (unusual but not impossible — a multi-venue
  consultant's own device, say) would share one offline queue across
  both. Not tested, not fixed — named as a real gap.
- **Device identity across locations** — `locationId` exists on the model
  but nothing enforces or tests location-level isolation within a single
  business yet (only business-level isolation is tested).
- End-to-end (real HTTP, real native app) cross-tenant device tests —
  everything above runs via FastAPI's `TestClient` against an in-memory
  Mongo, not against a deployed instance or a real Android build (no
  toolchain available this pass — see `CURRENT_ARCHITECTURE_AUDIT.md`).
