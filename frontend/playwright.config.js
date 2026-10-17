// @ts-check
const path = require('path');
const { defineConfig, devices } = require('@playwright/test');

const BACKEND_PORT = 8123;
const FRONTEND_PORT = 3100;
const BACKEND_URL = `http://127.0.0.1:${BACKEND_PORT}`;

/**
 * Golden-path smoke suite — not a full regression pack. The goal is a fast
 * "did we break the thing a real shift depends on" signal: log in, ring up
 * a sale, take payment; a guest places an order and can track it.
 *
 * Runs against the app's own production build, served statically, talking
 * to scripts/run_e2e_server.py — the real FastAPI app backed by mongomock
 * (in-memory), the same swap tests/inprocess/conftest.py uses. That means
 * CI needs no database service container: `npx playwright test` here boots
 * both halves of the stack itself via `webServer` below.
 */
module.exports = defineConfig({
  testDir: './e2e',
  fullyParallel: false,   // shared mongomock backend — tests share state deliberately
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  timeout: 30_000,
  // The very first navigation against a webServer that just finished
  // booting (backend still finishing its startup seed, browser's first
  // paint of a large bundle) is measurably slower than every navigation
  // after it — a 5s default assertion timeout flakes on exactly that one,
  // not on anything the app is actually doing wrong. Give assertions more
  // runway rather than chase a race that isn't a real bug.
  expect: { timeout: 15_000 },
  use: {
    baseURL: `http://127.0.0.1:${FRONTEND_PORT}`,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        // This sandbox's pre-installed browser doesn't line up with whatever
        // revision @playwright/test currently pins — point at it explicitly
        // instead of letting Playwright try to download its expected build.
        // CI environments with a matching `npx playwright install` don't
        // need this; harmless there too since the path just needs to exist.
        launchOptions: process.env.PLAYWRIGHT_CHROMIUM_PATH
          ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH }
          : {},
      },
    },
  ],
  webServer: [
    {
      command: `python3 scripts/run_e2e_server.py ${BACKEND_PORT}`,
      cwd: path.resolve(__dirname, '..', 'backend'),
      url: `${BACKEND_URL}/api/health`,
      timeout: 30_000,
      reuseExistingServer: !process.env.CI,
    },
    {
      // The build has to happen with REACT_APP_BACKEND_URL pointed at the
      // e2e backend above — CRA bakes REACT_APP_* vars in at build time,
      // there's no runtime config file to point a pre-built bundle at a
      // different backend after the fact.
      command: `sh -c "REACT_APP_BACKEND_URL=${BACKEND_URL} CI=false npm run build && npm run preview -- --port ${FRONTEND_PORT}"`,
      cwd: __dirname,
      url: `http://127.0.0.1:${FRONTEND_PORT}`,
      timeout: 180_000,
      reuseExistingServer: !process.env.CI,
    },
  ],
});
