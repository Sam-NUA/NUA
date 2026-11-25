'use strict';
// Real Electron on Windows CI; no production API, login or financial actions.
const assert = require('node:assert/strict');
const path = require('node:path');
const { _electron } = require('../../../frontend/node_modules/playwright-core');
(async () => {
  const host = await _electron.launch({ executablePath: require('electron'), args: [path.resolve(__dirname, '..'), '--touch'] });
  try {
    const page = await host.firstWindow();
    await page.locator('#nua-desktop-bar').waitFor();
    await page.getByTestId('login-page').waitFor();
    const info = await page.evaluate(() => window.nuaDesktop.getInfo());
    assert.equal(info.inputMode,'touch'); assert.equal(info.bridgeVersion,1);
    assert.equal(await page.evaluate(() => typeof window.require),'undefined');
    assert.equal(await page.evaluate(() => typeof window.nuaDesktop.invoke),'undefined');
    assert.equal(await page.locator('html').getAttribute('data-nua-input'),'touch');
    await page.evaluate(() => { window.open('https://example.com'); });
    assert.equal(host.windows().length,1);
    await page.evaluate(() => { location.href = 'https://example.com'; });
    assert.ok(page.url().startsWith('nua://app'));
    await page.goto('nua://app/login');
    await page.locator('#nua-desktop-bar').waitFor();
    const preferences = await host.evaluate(({BrowserWindow}) => BrowserWindow.getAllWindows()[0].webContents.getLastWebPreferences());
    assert.equal(preferences.sandbox,true); assert.equal(preferences.contextIsolation,true); assert.equal(preferences.nodeIntegration,false);
    const encryption = await host.evaluate(async ({safeStorage}) => {
      if (!safeStorage.isEncryptionAvailable()) return false;
      const encrypted = safeStorage.encryptString('non-secret-test-value');
      return safeStorage.decryptString(encrypted) === 'non-secret-test-value';
    });
    assert.equal(encryption,true);
    // Poll via Playwright's normal page.evaluate() bridge, not
    // waitForFunction's isolated execution context; preload methods are
    // exposed by Electron contextBridge to the application main world.
    const waitForWindow = async (expected, stage) => {
      let last;
      for (let attempt = 0; attempt < 50; attempt++) {
        last = await page.evaluate(async () => ({
          state: await window.nuaDesktop.getWindowState(),
          toolbar: document.querySelector('#nua-desktop-bar button')?.getAttribute('aria-pressed'),
        }));
        if (last.state.fullscreen === expected && last.toolbar === String(expected)) return;
        await new Promise(resolve => setTimeout(resolve, 100));
      }
      throw new Error(`Window state did not settle after ${stage}: ${JSON.stringify(last)}`);
    };
    // Native toggle and keyboard access must roundtrip through the window
    // state and toolbar. No hardware/device APIs are invoked by this test.
    await page.locator('#nua-desktop-bar button').first().click();
    await waitForWindow(true, 'toolbar full screen');
    await page.keyboard.press('Escape');
    await waitForWindow(false, 'Escape');
    await page.keyboard.press('F11');
    await waitForWindow(true, 'F11 fullscreen');
    await page.keyboard.press('F11');
    await waitForWindow(false, 'F11 restore');
    console.log('PASS: Windows Electron bridge, touch mode, routing, sandbox, popup/navigation denial and OS crypto roundtrip');
  } finally { await host.close(); }
})().catch(error => { console.error(error.message); process.exitCode=1; });
