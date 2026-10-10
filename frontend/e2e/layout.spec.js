const { test, expect } = require('@playwright/test');
const { loginAsOwner } = require('./helpers');

const widths = [390, 768, 1280];
test('navigation search, keyboard dismissal and responsive service screens', async ({ page }) => {
  test.setTimeout(180_000);
  await loginAsOwner(page);
  await page.getByTestId('dock-more').click();
  const dialog = page.getByRole('dialog', { name: 'All Features' });
  await expect(dialog).toBeVisible();
  await page.getByLabel('Find a feature').fill('inventory');
  await expect(dialog.getByRole('button', { name: 'Inventory', exact: true })).toBeVisible();
  await expect(dialog.getByRole('button', { name: 'Kitchen Display', exact: true })).toHaveCount(0);
  await page.keyboard.press('Escape');
  await expect(dialog).toBeHidden();
  await expect(page.getByTestId('dock-more')).toBeFocused();
  for (const width of widths) {
    await page.setViewportSize({ width, height: 900 });
    for (const route of ['/today', '/pos', '/kitchen', '/staff-roster', '/reservations', '/customers', '/settings']) {
      await page.goto(route);
      await expect(page.getByTestId('bottom-dock')).toBeVisible();
      await expect(page.locator('main')).toBeVisible();
      await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), { message: `${route} fits ${width}px` }).toBeTruthy();
    }
    await page.getByTestId('dock-more').click();
    await expect(dialog).toBeVisible();
    await expect(page.getByLabel('Find a feature')).toHaveValue('');
    await page.getByLabel('Find a feature').fill('no-such-feature-xyz');
    await expect(dialog.getByText('No features found.')).toBeVisible();
    await dialog.getByRole('button', { name: 'Clear search' }).click();
    await page.screenshot({ path: `test-results/navigation-${width}.png` });
    const bounds = await dialog.boundingBox();
    expect(bounds.x).toBeGreaterThanOrEqual(0);
    expect(bounds.x + bounds.width).toBeLessThanOrEqual(width);
    await page.keyboard.press('Escape');
  }
});

test('every registered staff screen mounts without a rendering exception', async ({ page }) => {
  test.setTimeout(600_000);
  const fs = require('fs');
  const path = require('path');
  const app = fs.readFileSync(path.join(__dirname, '../src/App.js'), 'utf8');
  const staffRoutes = app.split('<StaffLayout>')[1].split('</StaffLayout>')[0];
  const routes = [...new Set([...staffRoutes.matchAll(/<Route path="([^"]+)" element=\{(?!<Navigate)/g)].map(match => match[1]))];
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await loginAsOwner(page);
  for (const route of routes) {
    await test.step(route, async () => {
      errors.length = 0;
      await page.goto(route);
      await expect(page.locator('main')).toBeVisible();
      await expect.poll(async () => (await page.locator('main').innerText()).trim().length).toBeGreaterThan(8);
      expect(errors, `Rendering errors on ${route}`).toEqual([]);
      await page.screenshot({ path: `test-results/routes/${route.slice(1)}.png` });
    });
  }
});
