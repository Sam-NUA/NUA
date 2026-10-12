// @ts-check
const crypto = require('crypto');
const { test, expect } = require('@playwright/test');
const { loginAsOwner } = require('./helpers');

const BACKEND_URL = 'http://127.0.0.1:8123';

// Standard RFC 6238 TOTP (SHA1, 6 digits, 30s step) — the same defaults
// pyotp.TOTP() uses server-side (services/two_factor.py). No TOTP library
// is already a frontend dependency, and pulling one in just for this one
// E2E spec isn't worth it for ~25 lines of RFC-standard math.
function base32Decode(base32) {
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
  let bits = '';
  for (const char of base32.replace(/=+$/, '').toUpperCase()) {
    const idx = alphabet.indexOf(char);
    if (idx === -1) continue;
    bits += idx.toString(2).padStart(5, '0');
  }
  const bytes = [];
  for (let i = 0; i + 8 <= bits.length; i += 8) {
    bytes.push(parseInt(bits.slice(i, i + 8), 2));
  }
  return Buffer.from(bytes);
}

function totpCode(secretBase32, stepOffset = 0) {
  const key = base32Decode(secretBase32);
  const counter = Math.floor(Date.now() / 1000 / 30) + stepOffset;
  const counterBuf = Buffer.alloc(8);
  counterBuf.writeBigUInt64BE(BigInt(counter));
  const hmac = crypto.createHmac('sha1', key).update(counterBuf).digest();
  const offset = hmac[hmac.length - 1] & 0x0f;
  const binCode = (hmac.readUInt32BE(offset) & 0x7fffffff) % 1_000_000;
  return binCode.toString().padStart(6, '0');
}

test.setTimeout(90_000);

test('a 2FA-enrolled account cannot sign in with just a password — correct code required', async ({ page, request }) => {
  await loginAsOwner(page);
  const ownerToken = await page.evaluate(() => localStorage.getItem('nua_token'));

  const email = `e2e-2fa-${Date.now()}@example.com`;
  const password = 'TwoFactorE2E2026!';
  const registerRes = await request.post(`${BACKEND_URL}/api/auth/register`, {
    headers: { Authorization: `Bearer ${ownerToken}` },
    data: { name: 'E2E 2FA Tester', email, password, role: 'cashier' },
  });
  expect(registerRes.ok()).toBeTruthy();
  const { token: newUserToken } = await registerRes.json();

  const setupRes = await request.post(`${BACKEND_URL}/api/auth/2fa/setup`, {
    headers: { Authorization: `Bearer ${newUserToken}` },
  });
  expect(setupRes.ok()).toBeTruthy();
  const { secret } = await setupRes.json();

  const verifyRes = await request.post(`${BACKEND_URL}/api/auth/2fa/verify`, {
    headers: { Authorization: `Bearer ${newUserToken}` },
    data: { code: totpCode(secret) },
  });
  expect(verifyRes.ok()).toBeTruthy();

  // Fresh browser context's worth of local storage — log out the owner
  // before attempting the new account's own login.
  await page.evaluate(() => localStorage.removeItem('nua_token'));
  await page.goto('/login');
  await page.getByTestId('mode-email').click();
  await page.getByTestId('login-email').fill(email);
  await page.getByTestId('login-password').fill(password);
  await page.getByTestId('login-submit').click();

  // A correct password alone must never be enough — the account is now
  // 2FA-enrolled, so the backend answers with a challenge, not a token.
  await expect(page.getByTestId('twofactor-step')).toBeVisible();
  await expect(page.getByTestId('login-page')).toBeVisible();

  await page.getByTestId('twofactor-code').fill('000000');
  await page.getByTestId('twofactor-submit').click();
  await expect(page.getByTestId('twofactor-error')).toBeVisible();
  await expect(page.getByTestId('twofactor-step')).toBeVisible();

  // Used codes are burned against replay (services/two_factor.py) — the
  // exact code value just used to confirm enrolment above is still inside
  // its own 30s step, so a login attempt moments later needs the NEXT
  // step's code, not a recomputed-but-identical one, or the server
  // correctly (and confusingly, for this test) rejects it as a replay of
  // the code already consumed at enrolment.
  await page.getByTestId('twofactor-code').fill(totpCode(secret, 1));
  await page.getByTestId('twofactor-submit').click();
  await expect(page.getByTestId('login-page')).not.toBeVisible();
});
