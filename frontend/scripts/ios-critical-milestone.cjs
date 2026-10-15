#!/usr/bin/env node
'use strict';
/**
 * iOS equivalent of scripts/android-critical-milestone.cjs — the same flow
 * OFFLINE_SYNC_ARCHITECTURE.md has repeatedly flagged as "not verified this
 * pass": order -> offline -> restart -> reconnect -> sync -> exactly one
 * order. Drives the real, already-built Capacitor app on a real (if
 * simulated) iOS Simulator, against a throwaway backend+Mongo this same
 * workflow starts (no Docker on GitHub's macOS runners — see ios.yml's
 * critical-acceptance-milestone job for how Mongo/uvicorn are started
 * directly instead), never production, and never a real financial
 * transaction.
 *
 * Automation tier: Capacitor's iOS WKWebView has no Chrome DevTools
 * Protocol bridge the way Android's WebView does (android-critical-
 * milestone.cjs's own comments cover why) — WebKit speaks its own Remote
 * Inspector protocol instead. Rather than hand-roll a client for that
 * protocol, this drives the app through Appium's XCUITest driver (which
 * already wraps WebKit's protocol via WebDriverAgent), using WebdriverIO's
 * standard `$(selector)`/`.setValue()`/`.click()` element API in the
 * WEBVIEW_* context instead of Android's CDP Runtime.evaluate-based
 * evalPage helper. IndexedDB reads still need `executeAsync` (the W3C
 * WebDriver "synchronous script" endpoint doesn't await promises).
 *
 * "Offline" is simulated the same way Android's script settled on after
 * several failed attempts (see its own setNetwork() comments): stop the
 * real backend process so already-open keep-alive sockets actually die,
 * not just a device-level radio/airplane-mode toggle. lib/offlineQueue.js's
 * own queuing decision is a plain fetch() try/catch, not gated on
 * navigator.onLine (confirmed by reading it directly) — so unlike Android,
 * no device-side network toggle is needed here at all; killing/respawning
 * this script's own uvicorn child process is sufficient and simpler.
 */
const { execFileSync, spawn } = require('node:child_process');
const path = require('node:path');
const { remote } = require('webdriverio');

// The literal loopback IP, not "localhost" -- see ios.yml's own comment on
// REACT_APP_BACKEND_URL: iOS App Transport Security's NSAllowsLocalNetworking
// exception covers numeric loopback/link-local addresses and .local, but not
// the "localhost" hostname string itself, so the real built app's WKWebView
// needs this exact value to reach the backend over plain HTTP at all.
const BACKEND = process.env.MILESTONE_BACKEND_URL || 'http://127.0.0.1:8001';
const BUNDLE_ID = 'com.nua.pos';
const UDID = process.env.SIMULATOR_UDID;
const APP_PATH = process.env.APP_PATH;
const APPIUM_PORT = Number(process.env.APPIUM_PORT || 4723);
const BACKEND_DIR = path.join(__dirname, '..', '..', 'backend');

if (!UDID) throw new Error('SIMULATOR_UDID env var is required');
if (!APP_PATH) throw new Error('APP_PATH env var is required');

function log(msg) { console.log(`[ios-milestone] ${msg}`); }
function wait(ms) { return new Promise((resolve) => setTimeout(resolve, ms)); }

function simctl(args) {
  return execFileSync('xcrun', ['simctl', ...args], { encoding: 'utf8' });
}

async function fetchJson(pathname, opts = {}) {
  const res = await fetch(`${BACKEND}${pathname}`, {
    ...opts,
    headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
  });
  const text = await res.text();
  const body = text ? JSON.parse(text) : null;
  if (!res.ok) throw new Error(`${opts.method || 'GET'} ${pathname} -> HTTP ${res.status}: ${text}`);
  return body;
}

async function seedBackend(runId) {
  // Same RFC 2606 reasoning as android-critical-milestone.cjs's seedBackend:
  // example.com is real, resolvable, and not on email-validator's
  // reserved-name denylist (.invalid/.test/.example/.local all are).
  const email = `ci-ios-milestone-${runId}@example.com`;
  const password = 'Ci-Milestone-Password-1!';
  const name = `CI iOS Milestone ${runId}`;
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
      name: `CI iOS Milestone Item ${runId}`, category: 'Test', price, cost: 0, stock: 999, sku: `CI-IOS-${runId}`,
    }),
  });
  return { email, password, token, product };
}

// This script owns the throwaway backend's actual process lifecycle (not
// just a tunnel to it, unlike Android's adb-reverse approach) so it can
// kill it outright to simulate a real dropped connection, and respawn it
// to simulate reconnection — see this file's own header comment for why a
// device-level network toggle isn't needed here.
let backendProc = null;

function spawnBackend() {
  const proc = spawn('uvicorn', ['server:app', '--host', '0.0.0.0', '--port', '8001'], {
    cwd: BACKEND_DIR,
    env: {
      ...process.env,
      MONGO_URL: 'mongodb://localhost:27017/?replicaSet=nua-local',
      DB_NAME: 'nua_restaurant',
      JWT_SECRET: 'dev-only-not-for-production-please-rotate',
      // capacitor.config.json sets iosScheme: "https", which should make the
      // WKWebView's real origin "https://localhost" (matching Android's own
      // "https://localhost" under androidScheme: "https") -- but an earlier
      // RemoteDebugger trace in this same effort once showed the live
      // WebView title/url as "capacitor://localhost" instead, and a real CI
      // run saw even a plain fetch() GET fail with a generic WebKit
      // "Load failed" TypeError (the same opaque error a CORS-origin
      // mismatch produces, not just App Transport Security). Backend
      // supports comma-separated origins -- listing both candidates here is
      // strictly widening an allowlist, never a security loosening relative
      // to this throwaway, localhost-only CI backend. main() below also logs
      // window.location.origin directly, so the next real run confirms
      // which one it actually is.
      FRONTEND_URL: 'https://localhost,capacitor://localhost',
    },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  proc.stdout.on('data', (d) => process.stdout.write(`[backend] ${d}`));
  proc.stderr.on('data', (d) => process.stderr.write(`[backend] ${d}`));
  return proc;
}

async function waitForBackendReady(timeoutMs = 30000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(`${BACKEND}/api/ready`);
      if (res.ok) return true;
    } catch { /* still coming up */ }
    await wait(1000);
  }
  return false;
}

async function setNetwork(enabled) {
  if (enabled) {
    log('respawning the throwaway backend process — the sale\'s next retry has somewhere to land');
    backendProc = spawnBackend();
    const ready = await waitForBackendReady();
    log(`throwaway backend reachable again: ${ready}`);
    if (!ready) throw new Error('Backend never became ready again after respawning');
  } else {
    log('killing the throwaway backend process — any reused keep-alive socket now gets a real connection failure');
    if (backendProc) {
      backendProc.kill('SIGTERM');
      backendProc = null;
    }
  }
  await wait(2000); // propagation isn't instant, same margin android-critical-milestone.cjs uses
}

async function connectWebviewContext(driver, timeoutMs = 60000) {
  const deadline = Date.now() + timeoutMs;
  let lastContexts = [];
  while (Date.now() < deadline) {
    lastContexts = await driver.getContexts();
    const names = lastContexts.map((c) => (typeof c === 'string' ? c : c.id));
    const webview = names.find((n) => n && n.startsWith('WEBVIEW'));
    if (webview) {
      await driver.switchContext(webview);
      return webview;
    }
    await wait(500);
  }
  throw new Error(`No WEBVIEW context appeared within ${timeoutMs}ms. Last contexts: ${JSON.stringify(lastContexts)}`);
}

function makePageDriver(driver) {
  // W3C WebDriver's "execute script" endpoint runs synchronously and never
  // awaits a returned promise — executeAsync (the "execute async script"
  // endpoint) is the one that does, via the extra callback argument every
  // script implicitly receives as its last argument.
  async function evalPage(expression) {
    const outcome = await driver.executeAsync(`
      var done = arguments[arguments.length - 1];
      (async function(){ return (${expression}); })()
        .then((value) => done({ ok: true, value: value }))
        .catch((error) => done({ ok: false, message: (error && error.message) || String(error) }));
    `);
    if (!outcome.ok) throw new Error(`Page eval failed: ${outcome.message}\n${expression}`);
    return outcome.value;
  }
  async function waitForSelector(selector, timeoutMs = 60000) {
    const el = await driver.$(selector);
    await el.waitForExist({ timeout: timeoutMs, timeoutMsg: `Timed out waiting for selector ${selector}` });
  }
  async function setValue(selector, value) {
    const el = await driver.$(selector);
    await el.setValue(value);
  }
  async function click(selector) {
    const el = await driver.$(selector);
    await el.click();
  }
  return { evalPage, waitForSelector, setValue, click };
}

// Identical logic to android-critical-milestone.cjs's own — reads
// lib/offlineQueue.js's real durable state directly, independent of
// whatever the UI happens to be showing.
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
  })()`);
}

async function main() {
  log('starting the throwaway backend process for the first time (mongod is already up — see ios.yml)');
  backendProc = spawnBackend();
  if (!(await waitForBackendReady())) throw new Error('Throwaway backend never became ready');

  const runId = Date.now().toString(36);
  const { email, password, token, product } = await seedBackend(runId);
  log(`seeded owner ${email}, product ${product.id} at $${product.price}`);

  log(`launching the real built app (${APP_PATH}) on simulator ${UDID} via Appium/WebDriverAgent`);
  const driver = await remote({
    hostname: 'localhost',
    port: APPIUM_PORT,
    path: '/',
    logLevel: 'warn',
    // webdriverio's own defaults (connectionRetryCount: 3, each retry
    // timing out at 120s) fired three overlapping POST /session requests
    // in a real CI run, each stepping on the previous one's WebDriverAgent
    // startup ("Session ID is required but was not set", "WebDriverAgent
    // is not initialized") — because a cold-cache WDA build alone took
    // ~80s, and the whole createSession round trip took over 4 minutes
    // once those collisions piled up. One attempt with a generous timeout
    // beats three that fight each other.
    connectionRetryCount: 0,
    // A real CI run timed out right at the 300000ms (5 min) ceiling above
    // -- cold WebDriverAgent build/launch time varies with CI load and
    // isn't always the ~80s seen on a faster run. Since connectionRetryCount
    // is 0 (a single attempt, never a collision), there's no downside to
    // a generous ceiling here.
    connectionRetryTimeout: 600000,
    capabilities: {
      platformName: 'iOS',
      'appium:automationName': 'XCUITest',
      'appium:udid': UDID,
      'appium:app': APP_PATH,
      'appium:autoAcceptAlerts': true,
      'appium:newCommandTimeout': 180,
      'appium:webviewConnectTimeout': 30000,
      // WDA's own internal launch attempts (xcodebuild build-for-testing)
      // default to 60000ms each -- also raise this so a slow cold build
      // doesn't get cut off by WDA itself before our outer timeout above
      // even gets a chance to matter.
      'appium:wdaLaunchTimeout': 300000,
      // Without this, the XCUITest driver sees the simulator already
      // booted "headless" (by this workflow's own earlier `xcrun simctl
      // boot` step) and tries to restart it with a visible Simulator.app
      // window before starting the session — a real CI run showed that
      // restart never finishing ("Device did not finish booting within
      // 120000ms"), which has no real display/window server to render
      // into on this CI runner. isHeadless skips that restart entirely.
      'appium:isHeadless': true,
      // The actual root cause of "No WEBVIEW context appeared" (a real CI
      // run's own RemoteDebugger log proved this directly): the app's
      // WebView genuinely loaded (title "NUA POS", url
      // "capacitor://localhost") the whole time — Appium's WebKit remote
      // debugger just never matched it, because it only checks a fixed
      // bundle-id list (com.apple.WebKit.WebContent, the app's own
      // `appium:app` CFBundleIdentifier, etc.) and this CODE_SIGNING_
      // ALLOWED=NO debug build reports itself to the remote debugger as
      // "process-App" (its Xcode product/scheme name), not "com.nua.pos".
      'appium:additionalWebviewBundleIds': ['process-App'],
    },
  });

  try {
    // W3C WebDriver sessions default their "script" timeout to something
    // near zero unless explicitly set — a real CI run's very first
    // executeAsync() call (the login-screen reachability check) failed
    // immediately: "Timed out waiting for asynchronous script result
    // after 1 ms". Every evalPage() call below goes through executeAsync.
    await driver.setTimeout({ script: 60000 });
    await connectWebviewContext(driver);
    const page = makePageDriver(driver);

    log('waiting for the login screen');
    await page.waitForSelector('[data-testid="login-email"]');

    const origin = await page.evalPage('window.location.origin');
    log(`WebView's real origin (decides which FRONTEND_URL entry CORS must match): ${origin}`);

    const reachability = await page.evalPage(`
      fetch(${JSON.stringify(BACKEND)} + '/api/ready')
        .then(r => ({ ok: true, status: r.status }))
        .catch(e => ({ ok: false, message: e.message, name: e.name }))
    `);
    log(`direct fetch() reachability check from inside the WebView: ${JSON.stringify(reachability)}`);

    // The backend can return 200 on /api/auth/login while the UI still
    // shows "Couldn't reach the server" -- Login.jsx's catch-all collapses
    // ANY error without an axios `.response` into that one network-sounding
    // message (see its own comment on loginErrorMessage()), which is also
    // exactly what a non-axios throw after the request -- e.g. from
    // SecureStorageService.setToken()'s uncaught SecureStoragePlugin.set()
    // call -- looks like. Capture the real error instead of trusting the
    // rendered text.
    await page.evalPage(`(function(){
      window.__milestoneErrors = [];
      window.addEventListener('unhandledrejection', (e) => {
        window.__milestoneErrors.push({ kind: 'unhandledrejection', message: (e.reason && e.reason.message) || String(e.reason) });
      });
      window.addEventListener('error', (e) => {
        window.__milestoneErrors.push({ kind: 'error', message: e.message });
      });
      true;
    })()`);

    await page.setValue('[data-testid="login-email"]', email);
    await page.setValue('[data-testid="login-password"]', password);
    await page.click('[data-testid="login-submit"]');

    // Mirrors android-critical-milestone.cjs's own post-submit diagnosis —
    // that script's real root cause the first time round was a stale
    // selector (nav-pos vs dock-pos), found only by dumping exactly this.
    {
      const deadline = Date.now() + 15000;
      let outcome = 'timed-out-waiting';
      while (Date.now() < deadline) {
        const hasError = await page.evalPage(`!!document.querySelector('[data-testid="login-error"]')`);
        if (hasError) { outcome = 'login-error'; break; }
        const hasNav = await page.evalPage(`!!document.querySelector('[data-testid="dock-pos"]')`);
        if (hasNav) { outcome = 'nav-pos-visible'; break; }
        const stillOnLogin = await page.evalPage(`!!document.querySelector('[data-testid="login-page"]')`);
        if (!stillOnLogin) { outcome = 'left-login-page-no-nav-yet'; break; }
        await wait(500);
      }
      const pathname = await page.evalPage('window.location.pathname');
      const errorText = await page.evalPage(`(document.querySelector('[data-testid="login-error"]') || {}).innerText || null`);
      const capturedErrors = await page.evalPage('window.__milestoneErrors || []');
      log(`post-submit diagnosis: outcome=${outcome} pathname=${pathname} loginErrorText=${JSON.stringify(errorText)} capturedErrors=${JSON.stringify(capturedErrors)}`);
    }

    log('navigating to the POS terminal via the bottom dock');
    try {
      await page.waitForSelector('[data-testid="dock-pos"]', 45000);
    } catch (error) {
      const dump = await page.evalPage(`({
        pathname: window.location.pathname,
        readyState: document.readyState,
        bodyTextHead: document.body.innerText.slice(0, 300),
        testids: [...document.querySelectorAll('[data-testid]')].map(e => e.getAttribute('data-testid')).slice(0, 80),
      })`).catch((e) => ({ evalPageFailed: e.message }));
      log(`page dump when dock-pos never appeared: ${JSON.stringify(dump)}`);
      throw error;
    }
    await page.click('[data-testid="dock-pos"]');
    await page.waitForSelector('[data-testid="pos-terminal"]', 20000);
    await page.waitForSelector(`[data-testid="product-${product.id}"]`, 20000);

    await setNetwork(false);

    log('ringing up one cash sale while offline');
    await page.click(`[data-testid="product-${product.id}"]`);
    await page.click('[data-testid="pos-proceed-payment"]');
    await page.click('[data-testid="pay-cash"]');
    await page.click('[data-testid="cash-exact"]');
    await page.click('[data-testid="cash-complete"]');

    await wait(1500);

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
      const dbDump = await page.evalPage(`(async function(){
        const dbs = await indexedDB.databases();
        const out = [];
        for (const d of dbs) {
          const db = await new Promise((resolve, reject) => {
            const req = indexedDB.open(d.name);
            req.onsuccess = () => resolve(req.result);
            req.onerror = () => reject(req.error);
          });
          const stores = {};
          for (const storeName of db.objectStoreNames) {
            stores[storeName] = await new Promise((resolve) => {
              const countReq = db.transaction(storeName, 'readonly').objectStore(storeName).count();
              countReq.onsuccess = () => resolve(countReq.result);
              countReq.onerror = () => resolve('?');
            });
          }
          out.push({ name: d.name, version: d.version, stores });
          db.close();
        }
        return out;
      })()`);
      log(`every IndexedDB database that actually exists: ${JSON.stringify(dbDump)}`);
      throw new Error(`Expected exactly 1 queued offline transaction before restart, found ${pendingBeforeRestart}`);
    }
    log('exactly 1 transaction is queued offline, as expected');

    log('restarting the app process — a real terminate+relaunch, not a reload');
    await driver.execute('mobile: terminateApp', { bundleId: BUNDLE_ID });
    await wait(2000);
    await driver.execute('mobile: launchApp', { bundleId: BUNDLE_ID });

    await connectWebviewContext(driver);
    const page2 = makePageDriver(driver);

    log('confirming the queued sale survived the restart while still offline');
    let pendingAfterRestart = 0;
    {
      const deadline = Date.now() + 20000;
      while (Date.now() < deadline) {
        try {
          pendingAfterRestart = await countPendingTransactions(page2.evalPage);
        } catch (error) {
          log(`countPendingTransactions failed right after restart (${error.message}) — retrying`);
          await wait(1000);
          continue;
        }
        if (pendingAfterRestart > 0) break;
        await wait(1000);
      }
    }
    if (pendingAfterRestart !== 1) {
      throw new Error(`Expected the queued transaction to survive the restart (1), found ${pendingAfterRestart}`);
    }
    log('the queued transaction survived a real app restart while offline');

    await setNetwork(true);

    // Same real finding android-critical-milestone.cjs's own comments
    // document: the restart above happened WHILE STILL OFFLINE, so
    // AuthContext's mount-time checkAuth() genuinely failed and parked on
    // App.js's ProtectedRoutes authError screen. Do what a cashier would:
    // tap "Try again" if it's there.
    const triedAgain = await page2.evalPage(`(function(){
      const btn = [...document.querySelectorAll('button')].find(b => b.textContent.trim() === 'Try again');
      if (!btn) return false;
      btn.click();
      return true;
    })()`);
    if (triedAgain) {
      log('hit the "Unable to check your session" screen (app restarted while still offline) — tapped Try again');
      await wait(2000);
    }

    log('navigating back to the POS terminal so useOfflineQueue is actually mounted');
    await page2.waitForSelector('[data-testid="dock-pos"]', 45000);
    await page2.click('[data-testid="dock-pos"]');
    await page2.waitForSelector('[data-testid="pos-terminal"]', 20000);

    log('waiting for the queue to auto-flush now that the backend is back online');
    let synced = false;
    {
      const deadline = Date.now() + 90000; // useOfflineQueue's own 30s safety-net poll, with margin
      while (Date.now() < deadline) {
        let pendingNow;
        try {
          pendingNow = await countPendingTransactions(page2.evalPage);
        } catch (error) {
          log(`webview eval failed mid-poll (${error.message}) — retrying`);
          await wait(1000);
          continue;
        }
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

    log('PASS: order -> offline -> restart -> reconnect -> sync -> exactly one order, verified for real on a real (simulated) iOS WKWebView.');
  } finally {
    try { await driver.deleteSession(); } catch { /* best-effort cleanup */ }
    if (backendProc) { try { backendProc.kill('SIGTERM'); } catch { /* already gone */ } }
  }
}

// A real CI run's own log capture lost every one of this script's console.log
// lines outright (even the PASS/FAIL line), despite the run demonstrably
// getting deep into the flow (backend index creation, Appium session, real
// RemoteDebugger output all showed up) — macOS Node's stdout to a piped,
// non-TTY destination can be non-blocking, so a same-tick process.exit()
// truncates whatever's still queued. fs.writeSync bypasses that queue
// entirely (a real, synchronous fd write), and the setTimeout before exit
// gives any already-queued async writes (every earlier log() call) a turn
// to flush first.
function exitWith(code, message) {
  if (message) { try { require('node:fs').writeSync(2, `${message}\n`); } catch { /* best-effort */ } }
  setTimeout(() => process.exit(code), 500);
}

main().then(() => {
  exitWith(0);
}).catch((error) => {
  let appLog = '';
  try { appLog = `\n${simctl(['spawn', UDID, 'log', 'show', '--last', '2m', '--predicate', 'process == "App"'])}`; } catch { /* best-effort diagnostics */ }
  exitWith(1, `[ios-milestone] FAIL: ${error.stack || error.message}${appLog}`);
});
