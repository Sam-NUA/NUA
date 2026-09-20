// @ts-check
const { test, expect } = require('@playwright/test');
const { loginAsOwner } = require('./helpers');

// loginAsOwner retries up to 3x against the webServer's own cold-start
// window (see helpers.js) — give the test enough total runway to actually
// use those retries instead of hitting the suite's 30s default first.
test.setTimeout(90_000);

test('owner can log in and land on an authenticated screen', async ({ page }) => {
  await loginAsOwner(page);

  // Login redirects away from /login once the token lands — the exact
  // landing page depends on role-based routing, so assert on "not on the
  // login screen anymore" rather than pinning one destination.
  await expect(page).not.toHaveURL(/\/login/);
  await expect(page.getByTestId('login-page')).not.toBeVisible();
});

test('a bad password is rejected with a visible error, not a silent failure', async ({ page }) => {
  await page.goto('/login');
  // Same PIN-is-the-default-mode reasoning as helpers.js's loginAsOwner.
  await page.getByTestId('mode-email').click();
  await page.getByTestId('login-email').fill('owner@nua.com');
  await page.getByTestId('login-password').fill('definitely-wrong');
  await page.getByTestId('login-submit').click();

  await expect(page.getByTestId('login-error')).toBeVisible();
  await expect(page).toHaveURL(/\/login/);
});
