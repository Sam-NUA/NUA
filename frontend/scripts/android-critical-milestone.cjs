#!/usr/bin/env node
'use strict';
/**
 * Drives the REAL, already-installed-and-launchable Android app (this
 * workflow's earlier steps built the APK and booted a real, if emulated,
 * AVD) through the one flow OFFLINE_SYNC_ARCHITECTURE.md has repeatedly
 * flagged as "not verified this pass": order -> offline -> restart ->
 * reconnect -> sync -> exactly one order — against a throwaway
 * backend+Mongo this same workflow starts (see docker-compose.yml), never
 * production, and never a real financial transaction.
 *
 * Runs on the CI runner's host (NOT inside the emulator). Talks to the
 * throwaway backend over localhost; the app-under-test on the emulator
 * reaches that same backend via 10.0.2.2, the emulator's documented alias
 * for the host loopback interface (baked into this job's APK build via
 * REACT_APP_BACKEND_URL — see the workflow).
 *
 * Drives the app's own real DOM (via data-testid hooks already used by
 * this project's Jest/e2e tests) over the WebView's Chrome DevTools
 * Protocol bridge — the same automation tier as apps/windows/scripts/
 * smoke.cjs uses for the Windows app, just reached through adb instead of
 * Playwright's built-in Electron support (Capacitor's Android WebView has
 * no such first-class automation library).
 */
const { execFileSync } = require('node:child_process');
const CDP = require('chrome-remote-interface');

const BACKEND = process.env.MILESTONE_BACKEND_URL || 'http://localhost:8001';
const PACKAGE_ID = 'com.nua.pos';
const FORWARD_PORT = 9333;

function log(msg) { console.log(`[milestone] ${msg}`); }
function wait(ms) { return new Promise((resolve) => setTimeout(resolve, ms)); }

function adb(args) {
  return execFileSync('adb', args, { encoding: 'utf8' });
}
function adbShell(cmd) {
  return execFileSync('adb', ['shell', cmd], { encoding: 'utf8' });
}

async function fetchJson(path, opts = {}) {
  const res = await fetch(`${BACKEND}${path}`, {
    ...opts,
    headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
  });
  const text = await res.text();
  const body = text ? JSON.parse(text) : null;
  if (!res.ok) throw new Error(`${opts.method || 'GET'} ${path} -> HTTP ${res.status}: ${text}`);
  return body;
}

async function seedBackend(runId) {
  const email = `ci-milestone-${runId}@example.invalid`;
  const password = 'Ci-Milestone-Password-1!';
  const name = `CI Milestone ${runId}`;
  log(`registering throwaway owner ${email}`);
  const registered = await fetchJson('/api/auth/register', {
    method: 'POST',
    body: JSON.stringify({ name, email, password, role: 'owner' }),
  });
  const token = registered.token;
  const price = 19.5;
  log('creating one throwaway product to sell');
  const product = await fetchJson('/api/products', {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify({
      name: `CI Milestone Item ${runId}`, category: 'Test', price, cost: 0, stock: 999, sku: `CI-${runId}`,
    }),
  });
  return { email, password, token, product };
}

async function currentPid() {
  try { return adbShell(`pidof ${PACKAGE_ID}`).trim().split(/\s+/)[0] || null; }
  catch { return null; }
}

async function waitForPid(timeoutMs = 20000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const pid = await currentPid();
    if (pid) return pid;
    await wait(500);
  }
  throw new Error('App process never appeared after launch');
}

// The WebView's devtools unix-domain socket is only registered once the
// Chromium engine inside the app has finished spinning up — a short poll
// after the process itself appears, not instant.
async function findDevtoolsSocket(pid, timeoutMs = 20000) {
  const deadline = Date.now() + timeoutMs;
  let lastListing = '';
  while (Date.now() < deadline) {
    let listing = '';
    try { listing = adbShell('cat /proc/net/unix'); } catch { /* retry */ }
    lastListing = listing;
    const lines = listing.split('\n').filter((l) => l.includes('devtools_remote'));
    const forThisPid = lines.find((l) => l.includes(`_${pid}`));
    const chosen = forThisPid || (lines.length === 1 ? lines[0] : null);
    if (chosen) {
      const name = chosen.trim().split(/\s+/).pop().replace(/^@/, '');
      return name;
    }
    await wait(500);
  }
  throw new Error(`No devtools socket found for pid ${pid} within ${timeoutMs}ms. Last listing:\n${lastListing}`);
}

async function connectToAppPage() {
  const pid = await waitForPid();
  log(`app process pid=${pid}, locating its WebView devtools socket`);
  const socketName = await findDevtoolsSocket(pid);
  log(`forwarding tcp:${FORWARD_PORT} -> localabstract:${socketName}`);
  try { adb(['forward', '--remove', `tcp:${FORWARD_PORT}`]); } catch { /* nothing to remove yet */ }
  adb(['forward', `tcp:${FORWARD_PORT}`, `localabstract:${socketName}`]);
  let targets = [];
  const deadline = Date.now() + 15000;
  while (Date.now() < deadline) {
    targets = await CDP.List({ port: FORWARD_PORT });
    if (targets.length) break;
    await wait(500);
  }
  if (!targets.length) throw new Error('WebView devtools endpoint had no page targets');
  const client = await CDP({ port: FORWARD_PORT, target: targets[0].id });
  await client.Runtime.enable();
  return client;
}

function makePageDriver(client) {
  async function evalPage(expression) {
    const { result, exceptionDetails } = await client.Runtime.evaluate({
      expression, awaitPromise: true, returnByValue: true,
    });
    if (exceptionDetails) {
      throw new Error(`Page eval failed: ${exceptionDetails.exception?.description || exceptionDetails.text}\n${expression}`);
    }
    return result.value;
  }
  async function waitForSelector(selector, timeoutMs = 30000) {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      if (await evalPage(`!!document.querySelector(${JSON.stringify(selector)})`)) return;
      await wait(500);
    }
    throw new Error(`Timed out waiting for selector ${selector}`);
  }
  async function setValue(selector, value) {
    await evalPage(`(function(){
      const el = document.querySelector(${JSON.stringify(selector)});
      if (!el) throw new Error('missing ${selector}');
      const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el), 'value').set;
      setter.call(el, ${JSON.stringify(value)});
      el.dispatchEvent(new Event('input', { bubbles: true }));
    })();`);
  }
  async function click(selector) {
    await evalPage(`(function(){
      const el = document.querySelector(${JSON.stringify(selector)});
      if (!el) throw new Error('missing ${selector}');
      el.click();
    })();`);
  }
  return { evalPage, waitForSelector, setValue, click };
}

// Counts rows in the business-scoped offline queue's pending_transactions
// store directly via IndexedDB — the real durable state offlineQueue.js
// writes to (see lib/offlineQueue.js's dbNameFor/activate), independent of
// whatever the UI happens to be showing right now.
async function countPendingTransactions(evalPage) {
  return evalPage(`(async function(){
    const names = (await indexedDB.databases()).map(d => d.name).filter(n => n.startsWith('nua-offline-biz-'));
    if (!names.length) return 0;
    let total = 0;
    for (const name of names) {
      const db = await new Promise((resolve, reject) => {
        const req = indexedDB.open(name);
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => reject(req.error);
      });
      if (db.objectStoreNames.contains('pending_transactions')) {
        total += await new Promise((resolve, reject) => {
          const tx = db.transaction('pending_transactions', 'readonly');
          const countReq = tx.objectStore('pending_transactions').count();
          countReq.onsuccess = () => resolve(countReq.result);
          countReq.onerror = () => reject(countReq.error);
        });
      }
      db.close();
    }
    return total;
  })();`);
}

async function setNetwork(enabled) {
  const action = enabled ? 'enable' : 'disable';
  log(`turning network ${action} on the device (svc wifi/data)`);
  adbShell(`svc wifi ${action}`);
  adbShell(`svc data ${action}`);
  await wait(3000); // propagation isn't instant
}

async function main() {
  const runId = Date.now().toString(36);
  const { email, password, token, product } = await seedBackend(runId);
  log(`seeded owner ${email}, product ${product.id} at $${product.price}`);

  try { adb(['root']); } catch { log('adb root unavailable/unneeded on this image — continuing as shell user'); }

  log('clearing any previous app state and launching the app fresh');
  try { adbShell(`pm clear ${PACKAGE_ID}`); } catch { /* fine on a first install */ }
  adbShell(`am start -n ${PACKAGE_ID}/.MainActivity`);

  let client = await connectToAppPage();
  let page = makePageDriver(client);

  log('waiting for the login screen');
  await page.waitForSelector('[data-testid="login-email"]');
  await page.setValue('[data-testid="login-email"]', email);
  await page.setValue('[data-testid="login-password"]', password);
  await page.click('[data-testid="login-submit"]');

  // Owners land on /owner-dashboard after login (App.js's `home` redirect),
  // not on the POS terminal directly — navigate there the same way a real
  // user would, via the sidebar's own nav link.
  log('navigating from the owner dashboard to the POS terminal');
  await page.waitForSelector('[data-testid="nav-pos"]', 45000);
  await page.click('[data-testid="nav-pos"]');
  await page.waitForSelector('[data-testid="pos-terminal"]', 20000);
  await page.waitForSelector(`[data-testid="product-${product.id}"]`, 20000);

  await setNetwork(false);
  const isOnline = await page.evalPage('navigator.onLine');
  log(`navigator.onLine after disabling network: ${isOnline}`);

  log('ringing up one cash sale while offline');
  await page.click(`[data-testid="product-${product.id}"]`);
  await page.click('[data-testid="pos-proceed-payment"]');
  await page.click('[data-testid="pay-cash"]');
  await page.click('[data-testid="cash-exact"]');
  await page.click('[data-testid="cash-complete"]');

  log('confirming the sale actually landed in durable offline storage');
  let pendingBeforeRestart = 0;
  {
    const deadline = Date.now() + 15000;
    while (Date.now() < deadline) {
      pendingBeforeRestart = await countPendingTransactions(page.evalPage);
      if (pendingBeforeRestart > 0) break;
      await wait(500);
    }
  }
  if (pendingBeforeRestart !== 1) {
    throw new Error(`Expected exactly 1 queued offline transaction before restart, found ${pendingBeforeRestart}`);
  }
  log('exactly 1 transaction is queued offline, as expected');

  log('killing the app process — a real restart, not a reload');
  adbShell(`am force-stop ${PACKAGE_ID}`);
  await wait(2000);
  adbShell(`am start -n ${PACKAGE_ID}/.MainActivity`);

  client = await connectToAppPage();
  page = makePageDriver(client);

  log('confirming the queued sale survived the restart while still offline');
  let pendingAfterRestart = 0;
  {
    const deadline = Date.now() + 20000;
    while (Date.now() < deadline) {
      pendingAfterRestart = await countPendingTransactions(page.evalPage);
      if (pendingAfterRestart > 0) break;
      await wait(1000);
    }
  }
  if (pendingAfterRestart !== 1) {
    throw new Error(`Expected the queued transaction to survive the restart (1), found ${pendingAfterRestart}`);
  }
  log('the queued transaction survived a real app restart while offline');

  await setNetwork(true);

  log('waiting for the queue to auto-flush now that the device is back online');
  let synced = false;
  {
    const deadline = Date.now() + 90000; // useOfflineQueue's own 30s safety-net poll, with margin
    while (Date.now() < deadline) {
      const pendingNow = await countPendingTransactions(page.evalPage);
      if (pendingNow === 0) { synced = true; break; }
      await wait(3000);
    }
  }
  if (!synced) throw new Error('Offline queue never drained after reconnecting within the timeout');
  log('offline queue drained — verifying against the backend itself, not just the client');

  const transactions = await fetchJson('/api/transactions?payment_method=Cash', {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (transactions.length !== 1) {
    throw new Error(`Expected exactly 1 server-side transaction after sync, found ${transactions.length}: ${JSON.stringify(transactions)}`);
  }
  const [txn] = transactions;
  if (Math.abs(txn.total - product.price) > 0.01) {
    throw new Error(`Synced transaction total $${txn.total} doesn't match the expected $${product.price}`);
  }
  log(`exactly one server-side transaction exists: id=${txn.id} total=$${txn.total} clientOpId=${txn.clientOpId || '(none)'}`);

  log('PASS: order -> offline -> restart -> reconnect -> sync -> exactly one order, verified for real on a real (emulated) Android WebView.');
  await client.close();
}

main().catch((error) => {
  console.error(`[milestone] FAIL: ${error.stack || error.message}`);
  try { console.error(execFileSync('adb', ['logcat', '-d'], { encoding: 'utf8', maxBuffer: 1024 * 1024 * 20 }).split('\n').slice(-200).join('\n')); } catch {}
  process.exit(1);
});
