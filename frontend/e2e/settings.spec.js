const { test, expect } = require('@playwright/test');
const { loginAsOwner } = require('./helpers');

test('settings are searchable, grouped and usable on mobile', async ({ page }) => {
  test.setTimeout(120_000);
  await loginAsOwner(page);
  await page.goto('/settings');
  await expect(page.getByTestId('settings-overview')).toBeVisible();
  await expect(page.getByTestId('settings-overview').getByRole('button')).toHaveCount(20);
  await page.screenshot({ path: 'test-results/settings-desktop.png', fullPage: true });

  // PINs should be discoverable without knowing the old Staff tab name.
  await page.getByLabel('Find a setting').fill('PIN');
  await page.getByTestId('settings-open-users').click();
  await expect(page.getByTestId('staff-table')).toBeVisible();
  await expect(page.getByLabel('Find a setting')).toHaveValue('');

  // Search must not discard an unsaved form edit.
  await page.getByTestId('settings-tab-business').click();
  const businessInput = page.getByTestId('settings-content').locator('input').first();
  await businessInput.fill('Unsaved venue draft');
  await page.getByLabel('Find a setting').fill('no-matching-setting-xyz');
  await expect(page.getByText('No settings found.', { exact: false })).toBeVisible();
  await page.getByRole('button', { name: 'Clear search', exact: true }).click();
  await expect(businessInput).toHaveValue('Unsaved venue draft');

  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByLabel('Go to section').selectOption('overview');
  await expect(page.getByRole('navigation', { name: 'Settings sections' })).toBeHidden();
  await page.screenshot({ path: 'test-results/settings-mobile.png', fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await page.getByLabel('Go to section').selectOption('session');
  await expect(page.getByTestId('save-pos-session-btn')).toBeVisible();
  await page.getByLabel('Go to section').selectOption('security');
  await expect(page.getByTestId('settings-content')).toBeVisible();
});
