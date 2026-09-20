// @ts-check

async function loginAsOwner(page) {
  await page.goto('/login');
  // Letting the page settle (fonts, chunk loads) before the first submit
  // reduces contention with the login POST on this harness's single-worker
  // uvicorn process — under a real deploy this doesn't matter, but here a
  // browser downloading its own JS/font requests at the same moment as the
  // login call has occasionally starved the login connection outright.
  await page.waitForLoadState('networkidle').catch(() => {});

  // Login.jsx defaults to the PIN-code mode (staff terminals' priority login
  // method — see Login.jsx's own "Mode Toggle" comment) unless
  // localStorage's nua_login_mode already says 'email', which a fresh
  // browser context never has. Switch to email mode explicitly instead of
  // assuming login-email is already on screen.
  await page.getByTestId('mode-email').click();

  // Even so, the very first login attempt against a webServer that just
  // finished booting can hit a transient "couldn't reach the server" — the
  // backend process is up (its /api/health readiness check passed) but a
  // specific request lands in a bad window. That's a real, user-facing case
  // (see Login.jsx's loginErrorMessage — this is exactly the network-failure
  // branch, not "wrong password"), and a real user's answer is the same one
  // this does: try again.
  let lastError;
  for (let attempt = 1; attempt <= 5; attempt++) {
    await page.getByTestId('login-email').fill('owner@nua.com');
    await page.getByTestId('login-password').fill('NuaOwner2026!');
    await page.getByTestId('login-submit').click();
    try {
      await page.waitForURL((url) => !url.pathname.startsWith('/login'), { timeout: 8_000 });
      return;
    } catch (e) {
      lastError = e;
      await page.waitForTimeout(2_000);
    }
  }
  throw lastError;
}

module.exports = { loginAsOwner };
