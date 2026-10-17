const fs = require('node:fs');
const { test, expect } = require('@playwright/test');
const { loginAsOwner } = require('./helpers');

test('owner can inspect terminals and export only the active business offline records', async ({ page }) => {
  test.setTimeout(90_000);
  await loginAsOwner(page);
  const token = await page.evaluate(() => localStorage.getItem('nua_token'));
  const headers = { Authorization: `Bearer ${token}` };
  const me = await page.request.get('http://127.0.0.1:8123/api/auth/me', { headers });
  expect(me.ok()).toBeTruthy();
  const owner = await me.json();
  const registered = await page.request.post('http://127.0.0.1:8123/api/devices/register', {
    headers, data: { platform: 'android', deviceName: 'QA review tablet', appVersion: '1.0.0' },
  });
  expect(registered.ok()).toBeTruthy();
  const device = await registered.json();
  await page.goto('/settings');
  await page.getByTestId('settings-tab-hardware').click();
  const panel = page.getByTestId('device-management-panel');
  await expect(panel).toContainText('QA review tablet');
  await expect(panel).toContainText('NUA POS 1.0.0');
  // A revoke click must enter PIN verification before making the write.
  let revokeCalls = 0;
  page.on('request', request => { if (request.url().endsWith(`/devices/${device.id}/revoke`)) revokeCalls++; });
  await page.getByTestId(`revoke-device-${device.id}`).click();
  await expect(page.getByTestId('sensitive-action-reauth-dialog')).toBeVisible();
  expect(revokeCalls).toBe(0);
  await page.getByTestId('sensitive-action-reauth-dialog').getByRole('button', { name: 'Cancel' }).click();
  const downloadPromise = page.waitForEvent('download');
  await page.getByTestId('export-offline-review').click();
  const download = await downloadPromise;
  const exported = JSON.parse(fs.readFileSync(await download.path(), 'utf8'));
  expect(exported.businessId).toBe(owner.businessId);
  expect(exported.sales).toEqual([]);
  expect(exported.kitchenActions).toEqual([]);
  expect(JSON.stringify(exported)).not.toContain(token);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(panel).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  await page.screenshot({ path: 'test-results/device-management-mobile.png', fullPage: true });
});
