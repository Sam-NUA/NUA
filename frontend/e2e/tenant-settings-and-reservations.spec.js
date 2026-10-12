// @ts-check
const { test, expect } = require('@playwright/test');
const { loginAsOwner } = require('./helpers');

// Cross-business isolation for both of these fixes already has thorough,
// authoritative coverage at the backend level (tests/inprocess/
// test_kitchen_docket_tenant_scope.py, test_wallet_voucher_tenant_scope.py)
// using real two-business fixtures the Python suite can set up directly.
// This app has no self-serve "stand up an independent second tenant and
// log in as it" flow reachable from a plain browser session (the real one
// is the authenticated provisioning workflow in docs/OWNER_ACCESS.md) —
// so what a browser-level E2E test uniquely adds here is proving these
// endpoints actually work end to end through the real app, real HTTP and
// a real signed-in session, not re-proving the isolation boundary itself.

const BACKEND_URL = 'http://127.0.0.1:8123';

test.setTimeout(90_000);

test('reservation creation rejects a nonexistent table reference over the real HTTP stack', async ({ page, request }) => {
  await loginAsOwner(page);
  const ownerToken = await page.evaluate(() => localStorage.getItem('nua_token'));

  // Golden path: a normal reservation, no table reference, succeeds.
  const created = await request.post(`${BACKEND_URL}/api/reservations`, {
    headers: { Authorization: `Bearer ${ownerToken}` },
    data: { guestName: 'E2E Golden Path Guest', partySize: 2, date: '2027-08-01', time: '19:00' },
  });
  expect(created.ok()).toBeTruthy();
  expect((await created.json()).id).toBeTruthy();

  // A tableId that doesn't exist anywhere must be rejected, not silently
  // stored — the launch-audit fix this test exercises end to end.
  const rejected = await request.post(`${BACKEND_URL}/api/reservations`, {
    headers: { Authorization: `Bearer ${ownerToken}` },
    data: {
      guestName: 'E2E Rejected Guest', partySize: 2, date: '2027-08-01', time: '20:00',
      tableId: 'no-such-table-anywhere',
    },
  });
  expect(rejected.status()).toBe(404);
});

test('a signed-in owner can read and update their own kitchen docket config', async ({ page }) => {
  await loginAsOwner(page);
  const ownerToken = await page.evaluate(() => localStorage.getItem('nua_token'));

  const get1 = await page.request.get(`${BACKEND_URL}/api/kitchen/docket-config`, {
    headers: { Authorization: `Bearer ${ownerToken}` },
  });
  expect(get1.ok()).toBeTruthy();

  const put = await page.request.put(`${BACKEND_URL}/api/kitchen/docket-config`, {
    headers: { Authorization: `Bearer ${ownerToken}` },
    data: { fontSize: 'large' },
  });
  expect(put.ok()).toBeTruthy();
  expect((await put.json()).fontSize).toBe('large');

  const get2 = await page.request.get(`${BACKEND_URL}/api/kitchen/docket-config`, {
    headers: { Authorization: `Bearer ${ownerToken}` },
  });
  expect((await get2.json()).fontSize).toBe('large');

  // Leave the shared owner account's config as this suite found it, so a
  // later test run (or another spec in the same session) isn't affected.
  await page.request.put(`${BACKEND_URL}/api/kitchen/docket-config`, {
    headers: { Authorization: `Bearer ${ownerToken}` },
    data: { fontSize: 'medium' },
  });
});

test('a customer wallet is reachable end to end and reflects real customer data', async ({ page }) => {
  await loginAsOwner(page);
  const ownerToken = await page.evaluate(() => localStorage.getItem('nua_token'));

  const customerRes = await page.request.post(`${BACKEND_URL}/api/customers`, {
    headers: { Authorization: `Bearer ${ownerToken}` },
    data: { name: 'E2E Wallet Guest', email: `e2e-wallet-${Date.now()}@example.com`, phone: '+61400000111' },
  });
  expect(customerRes.ok()).toBeTruthy();
  const customer = await customerRes.json();

  const walletRes = await page.request.get(`${BACKEND_URL}/api/customers/${customer.id}/wallet`, {
    headers: { Authorization: `Bearer ${ownerToken}` },
  });
  expect(walletRes.ok()).toBeTruthy();
  const wallet = await walletRes.json();
  expect(wallet.customerId).toBe(customer.id);
  expect(wallet.storeCredit).toBe(0);
  expect(Array.isArray(wallet.vouchers)).toBeTruthy();
});
