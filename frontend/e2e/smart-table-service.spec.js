const { test, expect } = require('@playwright/test');
const { loginAsOwner } = require('./helpers');
// Ensure network mocks are intercepted rather than served by the PWA worker.
test.use({ serviceWorkers: 'block' });

test.setTimeout(90000);

test('smart table reminders support popup, acknowledgement and owner timing settings', async ({ page }) => {
  let status = 'open';
  let savedSettings = null;
  const rules = Object.fromEntries([
    ['seated_no_order', 5, 8],
    ['drinks_no_food', 8, 12],
    ['mains_not_fired', 10, 15],
    ['kitchen_delayed', 20, 30],
    ['food_waiting', 3, 5],
    ['post_mains_check', 12, 18],
    ['bill_waiting', 5, 8],
  ].map(([name, minutes, escalateMinutes]) =>
    [name, { enabled: true, minutes, escalateMinutes }]));
  const fixture = {
    id: 'e2e-service-alert', tableId: 'e2e-table-12', tableNumber: '12',
    title: 'Mains not fired', message: 'Mains are still on hold. Check table first.',
    rule: 'mains_not_fired', category: 'floor', priority: 'urgent',
    elapsedMinutes: 18, status: 'open', serverId: null,
  };
  await page.route('**/api/table-service/alerts', route => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({ enabled: true, openCount: status === 'open' ? 1 : 0,
      alerts: [{ ...fixture, status }] }),
  }));
  await page.route('**/api/table-service/alerts/*/action', async route => {
    const body = route.request().postDataJSON();
    status = body.action === 'acknowledge' ? 'acknowledged' :
      body.action === 'resolve' ? 'resolved' : 'snoozed';
    await route.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify({ id: fixture.id, status }) });
  });
  await page.route('**/api/table-service/settings', async route => {
    if (route.request().method() === 'PUT') {
      savedSettings = route.request().postDataJSON();
      await route.fulfill({ status: 200, contentType: 'application/json',
        body: JSON.stringify(savedSettings) });
    } else {
      await route.fulfill({ status: 200, contentType: 'application/json',
        body: JSON.stringify({ enabled: false, rules }) });
    }
  });

  await loginAsOwner(page);
  const popup = page.getByTestId('smart-table-popup');
  await expect(popup).toBeVisible({ timeout: 20000 });
  await expect(popup).toContainText('Mains not fired');
  await popup.getByRole('button', { name: 'Acknowledge' }).click();
  await expect(popup).toHaveCount(0);
  await page.getByTestId('table-service-attention-button').click();
  await expect(page.getByRole('dialog', { name: 'Table attention queue' })).toBeVisible();
  await expect(page.getByRole('dialog', { name: 'Table attention queue' }))
    .toContainText('Acknowledged');
  await page.getByRole('button', { name: 'Configure alert timings' }).click();
  await expect(page.getByRole('dialog', { name: 'Service alert settings' })).toBeVisible();
  await page.getByTestId('table-service-enabled').check();
  await page.getByRole('dialog', { name: 'Service alert settings' })
    .getByRole('button', { name: 'Save settings' }).click();
  await expect.poll(() => savedSettings?.enabled).toBe(true);
});

test('POS terminal shows a reminder at its exact service deadline and refreshes during order activity', async ({ page }) => {
  const dueTime = Date.now() + 5000;
  let checks = 0;
  await page.route('**/api/table-service/alerts', route => {
    checks += 1;
    const due = Date.now() >= dueTime;
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
      enabled: true,
      nextCheckAt: due ? null : new Date(dueTime).toISOString(),
      openCount: due ? 1 : 0,
      alerts: due ? [{
        id: 'e2e-pos-alert', tableId: 'e2e-pos-table', tableNumber: '16',
        title: 'Order not taken', message: 'Guests waiting for their order.',
        rule: 'seated_no_order', category: 'floor', priority: 'normal',
        elapsedMinutes: 5, status: 'open', serverId: null,
      }] : [],
    }) });
  });
  await loginAsOwner(page);
  await page.goto('/pos');
  await expect(page.getByTestId('pos-cart-panel')).toBeVisible();
  const beforeInteraction = checks;
  await page.getByTestId('cart-tab-cart').click();
  await expect.poll(() => checks, { timeout: 6000 }).toBeGreaterThan(beforeInteraction);
  const popup = page.getByTestId('smart-table-popup');
  await expect(popup).toBeVisible({ timeout: 15000 });
  await expect(popup).toContainText('Table 16');
  await expect(page.getByTestId('pos-proceed-payment')).toBeVisible();
});
