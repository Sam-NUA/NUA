# Test Credentials

## Staff Accounts (JWT Auth)
- **Owner**: owner@nua.com / NuaOwner2026! (full access)
- **Manager**: manager@nua.com / Staff2026! (name: Tina)
- **Cashier**: cashier@nua.com / Staff2026! (name: Vik)
- **Kitchen**: kitchen@nua.com / Staff2026! (name: Jim)

## PIN Login
- Owner PIN: 0311 (updated 2026-10-02, was 25)
- Manager PIN: 00
- Cashier PIN: 11
- Kitchen PIN: 22
- Maria (barista) PIN: 99

## Operator-only owner recovery (local pod only — never commit real values)
- `OWNER_RECOVERY_KEY` set in `backend/.env` for local testing: `FF3Fb3VlHwltio0eDby9Xrqo9Eomzna3I1_200OunGc`
- Flow: `POST /api/auth/owner-recovery/initiate` `{recoveryKey, email}` -> `POST /api/auth/owner-recovery/complete` `{token, password}`
- On real Vercel staging, `OWNER_RECOVERY_KEY` must be set separately by the operator directly in Vercel — never share or print its value in chat.
