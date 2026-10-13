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
    const info = await page.evaluate(() => window.nuaDesktop.getInfo());
    assert.equal(info.inputMode,'touch'); assert.equal(info.bridgeVersion,1);
    assert.equal(await page.evaluate(() => typeof window.require),'undefined');
    assert.equal(await page.evaluate(() => window.nuaDesktop.invoke),'undefined');
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
    console.log('PASS: Windows Electron bridge, touch mode, routing, sandbox, popup/navigation denial and OS crypto roundtrip');
  } finally { await host.close(); }
})().catch(error => { console.error(error.message); process.exitCode=1; });
