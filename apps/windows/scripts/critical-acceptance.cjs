'use strict';
// Real Windows Electron + bundled React + real FastAPI routes. In-memory test
// Mongo; real replica-set coordination remains the separate mandatory CI job.
const assert = require('node:assert/strict');
const https = require('node:https');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const { randomBytes } = require('node:crypto');
const { spawn, execFileSync } = require('node:child_process');
const { _electron } = require('../../../frontend/node_modules/playwright-core');
const origin = 'https://127.0.0.1:8443';
assert.equal(process.env.NUA_WINDOWS_API_ORIGIN, origin, 'Acceptance must target loopback only');
assert.equal(process.platform, 'win32');
const email = 'windows-acceptance@example.com', otherEmail = 'windows-other@example.com';
const password = randomBytes(24).toString('hex');
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
let backend, host, proxy, page;
async function api(route, token, body) {
  const response = await fetch('http://127.0.0.1:8123/api' + route, {
    method: body ? 'POST' : 'GET', headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    ...(body ? { body: JSON.stringify(body) } : {}), signal: AbortSignal.timeout(10000),
  });
  if (!response.ok) throw new Error(`Test API ${route}: HTTP ${response.status}`);
  return response.json();
}
async function connect() {
  proxy = https.createServer({ key: fs.readFileSync(path.join(process.env.RUNNER_TEMP, 'nua-acceptance-key.pem')),
    cert: fs.readFileSync(path.join(process.env.RUNNER_TEMP, 'nua-acceptance-cert.pem')) }, (request, response) => {
    const upstream = http.request({ hostname: '127.0.0.1', port: 8123, path: request.url, method: request.method,
      headers: request.headers }, result => { response.writeHead(result.statusCode, result.headers); result.pipe(response); });
    upstream.on('error', () => { response.writeHead(502); response.end(); });
    request.pipe(upstream);
  });
  await new Promise(resolve => proxy.listen(8443, '127.0.0.1', resolve));
}
async function disconnect() {
  if (!proxy) return;
  proxy.closeAllConnections(); await new Promise(resolve => proxy.close(resolve)); proxy = null;
}
async function launch() {
  host = await _electron.launch({ executablePath: require('electron'), args: [path.resolve(__dirname, '..')] });
  return host.firstWindow();
}
async function signIn(page, address) {
  await page.getByTestId('login-email').fill(address);
  await page.getByTestId('login-password').fill(password);
  await page.getByTestId('login-submit').click();
  await page.getByTestId('dock-pos').waitFor({ timeout: 60000 });
}
async function signOut(page) {
  // The UI's local logout clears storage before server cleanup; sign out via
  // the visible account control (same hook as ordinary browser acceptance).
  await page.getByTestId('dock-logout').click();
  await page.getByTestId('login-email').waitFor();
}
(async () => {
  const log = fs.openSync(path.join(process.env.RUNNER_TEMP, 'nua-windows-backend.log'), 'w');
  backend = spawn('python', ['scripts/run_terminal_acceptance_server.py'], {
    cwd: path.resolve(__dirname, '../../../backend'), stdio: ['ignore', log, log],
    env: { ...process.env, ADMIN_EMAIL: email, ADMIN_PASSWORD: password, NUA_ACCEPTANCE_OTHER_EMAIL: otherEmail,
      JWT_SECRET: randomBytes(32).toString('hex'), FRONTEND_URL: 'nua://app', SEED_DEMO_STAFF: 'false' },
  });
  for (let i = 0; ; i++) {
    try { await api('/health'); break; } catch (error) { if (i > 120) throw error; await sleep(1000); }
  }
  const login = await api('/auth/login', null, { email, password });
  console.log('Acceptance: throwaway backend ready and authenticated');
  const businessId = login.user.businessId;
  const product = await api('/products', login.token, { name: 'Windows durable cash test', category: 'Test', price: 19.5, cost: 0, stock: 10, sku: 'WINDOWS-DURABLE-CASH' });
  await connect();
  page = await launch(); await signIn(page, email);
  console.log('Acceptance: first native session registered and bound');
  await page.getByTestId('dock-pos').click();
  await page.getByTestId(`product-${product.id}`).waitFor();
  await disconnect(); // Closes sockets too; no surviving keep-alive false outage.
  await page.getByTestId(`product-${product.id}`).click();
  await page.getByTestId('pos-proceed-payment').click();
  await page.getByTestId('pay-cash').click();
  await page.getByTestId('cash-exact').click();
  await page.getByTestId('cash-complete').click();
  let rows;
  for (let i = 0; i < 30; i++) {
    rows = await page.evaluate(business => window.nuaDesktop.readOffline('pending_transactions', business), businessId);
    if (rows.length) break; await sleep(500);
  }
  assert.equal(rows.length, 1); const operation = rows[0].payload.clientOpId;
  assert.ok(operation); assert.equal(rows[0].businessId, businessId);
  console.log('Acceptance: one cash intent persisted before process termination');
  const pid = host.process().pid;
  execFileSync('taskkill', ['/PID', String(pid), '/T', '/F']); host = null;
  await sleep(1000);
  page = await launch();
  await page.getByRole('button', { name: 'Try again' }).waitFor({ timeout: 30000 });
  assert.equal(await page.getByTestId('pos-terminal').count(), 0);
  console.log('Acceptance: restarted offline with protected operations locked');
  await connect(); await page.getByRole('button', { name: 'Try again' }).click();
  await page.getByTestId('dock-pos').waitFor({ timeout: 60000 });
  // Switch before POS mounts/flushes, proving B cannot see A's durable sale.
  await signOut(page); await signIn(page, otherEmail);
  const foreignRows = await page.evaluate(() => window.nuaDesktop.readOffline('pending_transactions', 'acceptance-other-venue'));
  assert.deepEqual(foreignRows, []);
  await assert.rejects(page.evaluate(business => window.nuaDesktop.readOffline('pending_transactions', business), businessId));
  console.log('Acceptance: other business cannot read the original terminal queue');
  await signOut(page); await signIn(page, email);
  await page.getByTestId('dock-pos').click();
  for (let i = 0; i < 90; i++) {
    const transactions = await api('/transactions', login.token);
    const matches = transactions.filter(row => row.clientOpId === operation);
    if (matches.length) {
      assert.equal(matches.length, 1); assert.equal(matches[0].businessId, businessId); assert.equal(matches[0].total, 19.5);
      const pending = await page.evaluate(business => window.nuaDesktop.readOffline('pending_transactions', business), businessId);
      if (!pending.length) { console.log('PASS: real Windows cash sale survives process kill, remains isolated during A/B/A login, and syncs exactly once'); return; }
    }
    await sleep(1000);
  }
  throw new Error('Durable sale did not reconcile');
})().catch(async error => {
  console.error(error.message); process.exitCode = 1;
  if (page && !page.isClosed()) {
    console.error('Acceptance screen:', (await page.locator('body').innerText().catch(() => '')).slice(0, 4000));
    await page.screenshot({ path: path.join(process.env.RUNNER_TEMP, 'nua-windows-acceptance.png'), fullPage: true }).catch(() => {});
  }
}).finally(async () => {
  if (host) await host.close();
  await disconnect();
  if (backend) backend.kill();
});
