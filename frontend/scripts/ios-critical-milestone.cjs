#!/usr/bin/env node
'use strict';
/**
 * iOS financial/offline/device-binding acceptance — per docs/platform/
 * CLAUDE_IOS_DEPENDENCY_HANDOFF_2026-10-15.md. Drives the real, already-
 * built Capacitor app on a real (if simulated) iOS Simulator, against a
 * throwaway backend+Mongo this same workflow starts (no Docker on GitHub's
 * macOS runners — see ios.yml's critical-acceptance-milestone job), never
 * production, and never a real financial transaction.
 *
 * Proves, against this branch's terminal-session-binding contract
 * (backend/routes/auth.py's /auth/bind-device, services/device_auth.py's
 * validate_session_device/is_device_revoked_or_missing, frontend/src/
 * services/terminalSession.js):
 *   1. Password login + first-session device binding (one Device row,
 *      platform "ios", bound to the session).
 *   2. PIN login reuses the SAME bound device (no duplicate registration).
 *   3. Cash checkout -> real outage (backend process killed, not just a
 *      tunnel) -> durable pending record -> process terminate+relaunch
 *      while offline -> blocked protected screens until server
 *      re-verification -> reconnection -> exactly one server transaction
 *      with a nonempty clientOpId and the correct businessId.
 *   4. Business A's pending offline record is inaccessible from business
 *      B's session on the same physical device/app install.
 *   5. Owner revocation of the bound device rejects both the existing
 *      access token's next request and a refresh attempt.
 *
 * Automation tier: Capacitor's iOS WKWebView has no Chrome DevTools
 * Protocol bridge — WebKit speaks its own Remote Inspector protocol
 * instead. This drives the app through Appium's XCUITest driver (which
 * wraps that protocol via WebDriverAgent), using WebdriverIO's standard
 * element API in the WEBVIEW_* context. IndexedDB reads go through
 * executeAsync (the W3C "synchronous script" endpoint doesn't await
 * promises).
 *
 * "Offline" is simulated by stopping the real backend process so already-
 * open keep-alive sockets actually die, not just a device-level radio/
 * airplane-mode toggle — lib/offlineQueue.js's queuing decision is a plain
 * fetch() try/catch, not gated on navigator.onLine.
 *
 * A second, genuinely independent business (for the isolation proof) can't
 * be created through the public API: /auth/register forces any second
 * registration onto the acting owner's own businessId once an owner
 * exists anywhere (confirmed by reading routes/auth.py's register()
 * directly — this is a documented, real product gap, not a script bug;
 * see docs/COLLABORATION_HANDOFF.md's smoke-test section). This script
 * takes the same shortcut that document says the existing
 * tests/inprocess/*_tenant_isolation.py suite and smoke_test_live_edge.py
 * already take internally: enroll the second owner as an ordinary staff
 * member through the real API (so its password hash is real, backend-
 * generated), then patch only that one user's role/businessId directly in
 * the throwaway Mongo this script itself started — never touching
 * anything the real app's UI flow doesn't already produce.
 */
const { execFileSync, spawn } = require('node:child_process');
const path = require('node:path');
const { remote } = require('webdriverio');
const { randomBytes } = require('node:crypto');

// The literal loopback IP, not "localhost" -- iOS App Transport Security's
// NSAllowsLocalNetworking exception covers numeric loopback/link-local
// addresses and .local, but not the "localhost" hostname string itself.
const BACKEND = process.env.MILESTONE_BACKEND_URL || 'http://127.0.0.1:8001';
const BUNDLE_ID = 'com.nua.pos';
const UDID = process.env.SIMULATOR_UDID;
const APP_PATH = process.env.APP_PATH;
const APPIUM_PORT = Number(process.env.APPIUM_PORT || 4723);
const BACKEND_DIR = path.join(__dirname, '..', '..', 'backend');
const DB_NAME = 'nua_restaurant';
const TEST_JWT_SECRET = randomBytes(48).toString('hex');
const MONGO_URL = 'mongodb://localhost:27017/?replicaSet=nua-local';

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

async function registerOwner(runId, suffix = '') {
  // Same RFC 2606 reasoning as android-critical-milestone.cjs's seedBackend:
  // example.com is real, resolvable, and not on email-validator's
  // reserved-name denylist (.invalid/.test/.example/.local all are).
  const email = `ci-ios-milestone-${runId}${suffix}@example.com`;
  const password = 'Ci-Milestone-Password-1!';
  const name = `CI iOS Milestone ${runId}${suffix}`;
  log(`registering throwaway owner ${email}`);
  const registered = await fetchJson('/api/auth/register', {
    method: 'POST',
    body: JSON.stringify({ name, email, password, role: 'owner' }),
  });
  return { email, password, name, token: registered.token, user: registered.user };
}

async function seedProduct(token, runId, suffix = '') {
  const price = 19.5;
  log('creating one throwaway product to sell');
  const product = await fetchJson('/api/products', {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify({
      name: `CI iOS Milestone Item ${runId}${suffix}`, category: 'Test', price, cost: 0, stock: 999, sku: `CI-IOS-${runId}${suffix}`,
    }),
  });
  return product;
}

function mongoEval(script) {
  return execFileSync('mongosh', ['--quiet', `${MONGO_URL.replace('/?', `/${DB_NAME}?`)}`, '--eval', script], { encoding: 'utf8' });
}

// See this file's own header comment: the public API has no self-service
// way to create a second, independently-owned business once an owner
// exists anywhere. Enroll through the real API first (owner A enrolling a
// "cashier" produces a genuine, backend-hashed password), then promote only
// that one user to owner-of-a-fresh-business directly in Mongo -- the same
// shortcut docs/COLLABORATION_HANDOFF.md documents the existing tenant-
// isolation test suites already taking.
async function createIndependentSecondBusiness(ownerAToken, runId) {
  const email = `ci-ios-milestone-${runId}-bizb@example.com`;
  const password = 'Ci-Milestone-Password-1!';
  const name = `CI iOS Milestone ${runId} Biz B Owner`;
  log(`enrolling throwaway second owner ${email} (via owner A, then promoting to an independent business in Mongo)`);
  const enrolled = await fetchJson('/api/auth/register', {
    method: 'POST',
    headers: { Authorization: `Bearer ${ownerAToken}` },
    body: JSON.stringify({ name, email, password, role: 'cashier' }),
  });
  const freshBusinessId = `ci-biz-b-${runId}`;
  mongoEval(`db.auth_users.updateOne({email: ${JSON.stringify(email)}}, {$set: {role: "owner", businessId: ${JSON.stringify(freshBusinessId)}}})`);
  // The enrollment token above carries owner A's businessId -- re-login to
  // get a fresh token reflecting the promoted, independent business.
  const relogged = await fetchJson('/api/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  });
  return { email, password, name, token: relogged.token, user: relogged.user, businessId: freshBusinessId };
}

async function fetchDevices(token) {
  return fetchJson('/api/devices', { headers: { Authorization: `Bearer ${token}` } });
}

async function revokeDevice(token, deviceId) {
  return fetchJson(`/api/devices/${deviceId}/revoke`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
  });
}

async function setOwnPin(token, staffId, pin) {
  return fetchJson(`/api/auth/staff/${staffId}/set-pin`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify({ pin }),
  });
}

// This script owns the throwaway backend's actual process lifecycle (not
// just a tunnel to it, unlike Android's adb-reverse approach) so it can
// kill it outright to simulate a real dropped connection, and respawn it
// to simulate reconnection.
let backendProc = null;

function spawnBackend() {
  const proc = spawn('uvicorn', ['server:app', '--host', '0.0.0.0', '--port', '8001'], {
    cwd: BACKEND_DIR,
    env: {
      ...process.env,
      MONGO_URL: `${MONGO_URL}`,
      DB_NAME,
      JWT_SECRET: TEST_JWT_SECRET,
      // capacitor.config.json's iosScheme is "capacitor" on this branch
      // (fixed from the earlier unsupported "https" -- see
      // MOBILE_HARDENING_REVIEW_2026-10-14.md), so the WKWebView's real
      // origin is "capacitor://localhost", confirmed directly via
      // window.location.origin below.
      FRONTEND_URL: 'capacitor://localhost',
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
  await wait(2000); // propagation isn't instant
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
  async function clickButtonWithText(text, timeoutMs = 15000) {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      const clicked = await evalPage(`(function(){
        const btn = [...document.querySelectorAll('button')].find(b => b.textContent.trim() === ${JSON.stringify(text)});
        if (!btn) return false;
        btn.click();
        return true;
      })()`);
      if (clicked) return true;
      await wait(500);
    }
    return false;
  }
  return { evalPage, waitForSelector, setValue, click, clickButtonWithText };
}

// DB_VERSION/naming per lib/offlineQueue.js's dbNameFor() on this branch:
// "nua-offline-v2-biz-<businessId>" -- changed from the pre-hardening
// "nua-offline-biz-<businessId>" naming (old/first-login-migrated
// databases are deliberately preserved untouched, never auto-replayed).
function dbNameFor(businessId) {
  return `nua-offline-v2-biz-${encodeURIComponent(businessId)}`;
}

// Same lookup as countPendingInDb, but returns the queued record's own
// `payload` (the exact body offlineQueue.js's own replay would resend --
// see enqueueTransaction()) instead of just a count, so the real
// clientOpId it carries can be captured and matched later, and so this
// exact payload can be replayed to prove duplicate submission is safe.
async function getPendingPayloadInDb(evalPage, dbName) {
  return evalPage(`(async function(){
    const names = (await indexedDB.databases()).map(d => d.name);
    if (!names.includes(${JSON.stringify(dbName)})) return null;
    const db = await new Promise((resolve, reject) => {
      const req = indexedDB.open(${JSON.stringify(dbName)});
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
    let rows = [];
    if (db.objectStoreNames.contains('pending_transactions')) {
      rows = await new Promise((resolve, reject) => {
        const tx = db.transaction('pending_transactions', 'readonly');
        const getReq = tx.objectStore('pending_transactions').getAll();
        getReq.onsuccess = () => resolve(getReq.result);
        getReq.onerror = () => reject(getReq.error);
      });
    }
    db.close();
    return rows[0] ? rows[0].payload : null;
  })()`);
}

async function countPendingInDb(evalPage, dbName) {
  return evalPage(`(async function(){
    const names = (await indexedDB.databases()).map(d => d.name);
    if (!names.includes(${JSON.stringify(dbName)})) return 0;
    const db = await new Promise((resolve, reject) => {
      const req = indexedDB.open(${JSON.stringify(dbName)});
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
    let count = 0;
    if (db.objectStoreNames.contains('pending_transactions')) {
      count = await new Promise((resolve, reject) => {
        const tx = db.transaction('pending_transactions', 'readonly');
        const countReq = tx.objectStore('pending_transactions').count();
        countReq.onsuccess = () => resolve(countReq.result);
        countReq.onerror = () => reject(countReq.error);
      });
    }
    db.close();
    return count;
  })()`);
}

// Identical logic to android-critical-milestone.cjs's own — scans every
// per-business queue database that currently exists, independent of
// whatever the UI happens to be showing. Used where the active business
// isn't the point (e.g. confirming the queue drained to zero for whoever
// is currently signed in); the isolation check below instead names the
// exact database so it can assert on business A's row while B is active.
async function countPendingTransactions(evalPage) {
  return evalPage(`(async function(){
    const names = (await indexedDB.databases()).map(d => d.name).filter(n => n.startsWith('nua-offline-v2-biz-'));
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

// Decodes (never verifies -- no secret available here, and none needed:
// this only reads claims to assert on, the backend itself still enforces
// everything) a JWT's payload so the real bound token's own claims can be
// checked directly. A row existing in /api/devices proves a device was
// registered -- it does NOT by itself prove the CURRENT session actually
// carries that binding (per real review feedback on an earlier draft).
function decodeJwt(token) {
  const payload = token.split('.')[1];
  return JSON.parse(Buffer.from(payload.replace(/-/g, '+').replace(/_/g, '/'), 'base64').toString('utf8'));
}

// SecureStorageService.setToken() (frontend/src/platform/capacitor/
// SecureStorageService.js) actively purges the plaintext localStorage
// mirror on every call -- the real token only ever lives in the iOS
// Keychain via capacitor-secure-storage-plugin. Reading localStorage here
// always finds nothing, regardless of whether login actually bound a
// session. Read the same plugin the app itself reads from (getToken()'s
// own keys()-then-get() shape) so this captures what the app is really
// using, not a stale assumption about where it's stored.
async function captureBoundToken(page) {
  const token = await page.evalPage(`
    (async function() {
      const plugins = window.Capacitor && window.Capacitor.Plugins;
      if (!plugins || !plugins.SecureStoragePlugin) return null;
      const { value: keys } = await plugins.SecureStoragePlugin.keys();
      if (!keys.includes('nua_token')) return null;
      const { value } = await plugins.SecureStoragePlugin.get({ key: 'nua_token' });
      return value || null;
    })()
  `);
  if (!token) throw new Error('No token found in the real Keychain-backed SecureStoragePlugin after login');
  return { token, claims: decodeJwt(token) };
}

async function assertWebviewRefresh(page, expected, label) {
  const result = await page.evalPage(`(async () => {
    const response = await window.Capacitor.nativePromise('NuaRefreshSession', 'refresh', { url: ${JSON.stringify(BACKEND)} });
    if (response.status !== 200) return { status: response.status };
    const body = response.data;
    if (!body.token) return { status: 200, missingToken: true };
    const claims = JSON.parse(atob(body.token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')));
    const me = await fetch(${JSON.stringify(BACKEND)} + '/api/auth/me', {
      headers: { Authorization: 'Bearer ' + body.token }
    });
    const cookies = await window.Capacitor.nativePromise('CapacitorCookies', 'getCookies', {
      url: ${JSON.stringify(BACKEND)}
    });
    return { status: response.status, meStatus: me.status, claims,
      exposedRefreshCookie: Object.prototype.hasOwnProperty.call(cookies, 'refresh_token') ||
        document.cookie.includes('refresh_token=') };
  })()`);
  if (result.status !== 200 || result.meStatus !== 200 || result.missingToken || result.exposedRefreshCookie) {
    throw new Error(`${label}: usable HttpOnly-cookie refresh required, got ${JSON.stringify(result)}`);
  }
  for (const key of ['sub', 'businessId', 'deviceId', 'sessionId']) {
    if (!expected[key] || result.claims[key] !== expected[key]) {
      throw new Error(`${label}: refreshed ${key} changed`);
    }
  }
  log(`${label}: refresh 200, bearer /me 200, same account/business/device/session, HttpOnly cookie hidden`);
}

async function loginWithPassword(page, email, password) {
  // Login.jsx defaults `mode` from localStorage's 'nua_login_mode' -- a
  // device-level preference that survives logout (it's not account state).
  // Once any earlier login on this device used PIN, the page comes back up
  // in PIN mode and never renders login-email at all. A real CI run hung
  // the full 60s waitForSelector timeout on exactly this after the script's
  // own earlier PIN-login phase. Explicitly switch back to email mode first,
  // mirroring loginWithPin()'s own switch into PIN mode below.
  await page.waitForSelector('[data-testid="mode-email"]');
  await page.click('[data-testid="mode-email"]');
  await page.waitForSelector('[data-testid="login-email"]');
  await page.setValue('[data-testid="login-email"]', email);
  await page.setValue('[data-testid="login-password"]', password);
  await page.click('[data-testid="login-submit"]');
}

async function loginWithPin(page, pin) {
  await page.waitForSelector('[data-testid="mode-pin"]');
  await page.click('[data-testid="mode-pin"]');
  await page.waitForSelector('[data-testid="login-pin"]');
  await page.setValue('[data-testid="login-pin"]', pin);
  await page.click('[data-testid="pin-submit"]');
  // handlePinLogin (Login.jsx) does `await staffMgmtAPI.pinLogin(pin)` then
  // `await SecureStorageService.setToken(...)` then a full
  // `window.location.assign('/clock-in')` reload -- all AFTER this click
  // already returned (the click itself is just the tap; none of that is
  // awaited by it). A real CI run reconnected the WEBVIEW context and hit
  // it with executeAsync before the reload had actually started, getting a
  // context mid-teardown and an opaque WebDriverError back. Give the whole
  // chain time to actually finish navigating before anything touches the
  // page again.
  await wait(3000);
}

async function logoutViaUI(page) {
  // BottomDock.jsx's own "Sign Out" control is `hidden md:flex` -- desktop
  // only. The Simulator's viewport is phone-width, so the real control a
  // mobile user taps is inside the "More" sheet's mobile-only plain-text
  // "Sign out" button (also `md:hidden`, no data-testid) -- confirmed by
  // reading BottomDock.jsx directly, not assumed from the desktop button.
  await page.waitForSelector('[data-testid="dock-more"]');
  await page.click('[data-testid="dock-more"]');
  await page.waitForSelector('[data-testid="more-splash"]');
  const clicked = await page.clickButtonWithText('Sign out');
  if (!clicked) throw new Error('Could not find the mobile "Sign out" button inside the More sheet');
}

async function waitForOutcomeAfterSubmit(page, { timeoutMs = 15000, navSelector = '[data-testid="dock-pos"]' } = {}) {
  const deadline = Date.now() + timeoutMs;
  let outcome = 'timed-out-waiting';
  while (Date.now() < deadline) {
    const hasError = await page.evalPage(`!!document.querySelector('[data-testid="login-error"]')`);
    if (hasError) { outcome = 'login-error'; break; }
    const hasNav = await page.evalPage(`!!document.querySelector(${JSON.stringify(navSelector)})`);
    if (hasNav) { outcome = 'nav-visible'; break; }
    const stillOnLogin = await page.evalPage(`!!document.querySelector('[data-testid="login-page"]')`);
    if (!stillOnLogin) { outcome = 'left-login-page-no-nav-yet'; break; }
    await wait(500);
  }
  const pathname = await page.evalPage('window.location.pathname');
  const errorText = await page.evalPage(`(document.querySelector('[data-testid="login-error"]') || {}).innerText || null`);
  log(`post-submit diagnosis: outcome=${outcome} pathname=${pathname} loginErrorText=${JSON.stringify(errorText)}`);
  if (outcome === 'login-error') throw new Error(`Login failed: ${errorText}`);
  return outcome;
}

async function navigateToPos(page) {
  try {
    await page.waitForSelector('[data-testid="dock-pos"]', 45000);
  } catch (error) {
    const dump = await page.evalPage(`({
      pathname: window.location.pathname,
      readyState: document.readyState,
      bodyTextHead: document.body.innerText.slice(0, 300),
      testids: [...document.querySelectorAll('[data-testid]')].map(e => e.getAttribute('data-testid')).slice(0, 80),
      lastRefreshDiagnostic: window.__lastRefreshDiagnostic || null,
    })`).catch((e) => ({ evalPageFailed: e.message }));
    log(`page dump when dock-pos never appeared: ${JSON.stringify(dump)}`);
    throw error;
  }
  await page.click('[data-testid="dock-pos"]');
  await page.waitForSelector('[data-testid="pos-terminal"]', 20000);
}

async function main() {
  log('starting the throwaway backend process for the first time (mongod is already up — see ios.yml)');
  backendProc = spawnBackend();
  if (!(await waitForBackendReady())) throw new Error('Throwaway backend never became ready');

  const runId = Date.now().toString(36);
  const ownerA = await registerOwner(runId, '-a');
  const productA = await seedProduct(ownerA.token, runId, '-a');
  log(`seeded owner A ${ownerA.email}, product ${productA.id} at $${productA.price}`);

  log(`launching the real built app (${APP_PATH}) on simulator ${UDID} via Appium/WebDriverAgent`);
  const driver = await remote({
    hostname: 'localhost',
    port: APPIUM_PORT,
    path: '/',
    logLevel: 'warn',
    // One patient attempt beats webdriverio's own default of three
    // colliding ones -- see ios.yml's own history on this.
    connectionRetryCount: 0,
    connectionRetryTimeout: 600000,
    capabilities: {
      platformName: 'iOS',
      'appium:automationName': 'XCUITest',
      'appium:udid': UDID,
      'appium:app': APP_PATH,
      'appium:autoAcceptAlerts': true,
      'appium:newCommandTimeout': 180,
      'appium:webviewConnectTimeout': 30000,
      'appium:wdaLaunchTimeout': 300000,
      'appium:isHeadless': true,
      // This CODE_SIGN_IDENTITY=- debug build reports itself to the remote
      // debugger as "process-App" (its Xcode product/scheme name), not
      // "com.nua.pos" -- Appium's WebKit remote debugger only matches a
      // fixed bundle-id list otherwise.
      'appium:additionalWebviewBundleIds': ['process-App'],
    },
  });

  try {
    // W3C WebDriver sessions default their "script" timeout to near zero
    // unless explicitly set -- every evalPage() call below goes through
    // executeAsync.
    await driver.setTimeout({ script: 60000 });
    await connectWebviewContext(driver);
    let page = makePageDriver(driver);

    log('waiting for the login screen');
    await page.waitForSelector('[data-testid="login-email"]');

    const origin = await page.evalPage('window.location.origin');
    log(`WebView's real origin (decides which FRONTEND_URL entry CORS must match): ${origin}`);

    // ── Phase 1: password login + first-session device binding ──────────
    log('logging in as owner A with a password');
    await loginWithPassword(page, ownerA.email, ownerA.password);
    await waitForOutcomeAfterSubmit(page);
    await navigateToPos(page);
    await page.waitForSelector(`[data-testid="product-${productA.id}"]`, 20000);
    log('owner A reached the POS terminal — password login succeeded');

    let devicesA = await fetchDevices(ownerA.token);
    if (devicesA.length !== 1) {
      throw new Error(`Expected exactly 1 device registered for business A after first login, found ${devicesA.length}: ${JSON.stringify(devicesA)}`);
    }
    const deviceA = devicesA[0];
    if (deviceA.platform !== 'ios') throw new Error(`Expected the registered device's platform to be "ios", got "${deviceA.platform}"`);
    if (deviceA.status !== 'active') throw new Error(`Expected the registered device to be active, got status "${deviceA.status}"`);
    log(`a device was registered: deviceId=${deviceA.id} platform=${deviceA.platform} status=${deviceA.status} (registry row alone, not yet proof the live session is bound)`);

    // The registry row above only proves A device exists -- it says nothing
    // about whether THIS session's own token carries that binding. Decode
    // the real, currently-stored token the UI is actually using and check
    // its own claims directly.
    const boundA1 = await captureBoundToken(page);
    if (boundA1.claims.sub !== ownerA.user.id) throw new Error(`Bound token's subject ${boundA1.claims.sub} doesn't match owner A ${ownerA.user.id}`);
    if (boundA1.claims.businessId !== ownerA.user.businessId) throw new Error(`Bound token's businessId ${boundA1.claims.businessId} doesn't match business A ${ownerA.user.businessId}`);
    if (boundA1.claims.deviceId !== deviceA.id) throw new Error(`Bound token's own deviceId claim is ${boundA1.claims.deviceId}, expected the registered device ${deviceA.id}`);
    if (!boundA1.claims.sessionId) throw new Error('Bound token is missing a sessionId claim');
    log(`first-session device binding confirmed on the real, currently-stored token itself: sessionId=${boundA1.claims.sessionId} deviceId=${boundA1.claims.deviceId} businessId=${boundA1.claims.businessId}`);

    await assertWebviewRefresh(page, boundA1.claims, 'password login');

    // ── Phase 2: PIN login reuses the SAME bound device ──────────────────
    log('setting owner A\'s PIN for the PIN-login proof');
    await setOwnPin(ownerA.token, ownerA.user.id, '1234');
    log('stopping the backend before native logout to prove local cookie cleanup');
    await setNetwork(false);
    await logoutViaUI(page);
    await page.waitForSelector('[data-testid="login-page"]', 15000);
    await setNetwork(true);
    const afterLogout = await page.evalPage(`window.Capacitor.nativePromise('NuaRefreshSession', 'refresh', { url: ${JSON.stringify(BACKEND)} }).then(r => r.status)`);
    if (afterLogout !== 401) throw new Error(`Logout must remove the refresh cookie, got ${afterLogout}`);
    log('offline logout removed refresh capability from the real native cookie jar');

    log('logging back in as owner A via PIN');
    await loginWithPin(page, '1234');
    // handlePinLogin does a full `window.location.assign` reload (see
    // Login.jsx) -- rather than inline bindTerminalSession like the
    // password path -- so the webview context needs reconnecting, same as
    // after a real app restart.
    await connectWebviewContext(driver);
    page = makePageDriver(driver);
    await waitForOutcomeAfterSubmit(page);
    await navigateToPos(page);
    log('owner A reached the POS terminal again — PIN login succeeded');

    const devicesAfterPin = await fetchDevices(ownerA.token);
    if (devicesAfterPin.length !== 1 || devicesAfterPin[0].id !== deviceA.id) {
      throw new Error(`Expected PIN login to reuse the same bound device (${deviceA.id}), found: ${JSON.stringify(devicesAfterPin)}`);
    }
    log('PIN login reused the existing device binding — no duplicate registration');

    const boundA2 = await captureBoundToken(page);
    if (boundA2.claims.deviceId !== deviceA.id) throw new Error(`PIN login's own bound token carries deviceId ${boundA2.claims.deviceId}, expected ${deviceA.id}`);
    if (!boundA2.claims.sessionId) throw new Error('PIN login\'s bound token is missing a sessionId claim');
    log(`PIN login's real bound token also carries the same device binding: sessionId=${boundA2.claims.sessionId} deviceId=${boundA2.claims.deviceId}`);
    await assertWebviewRefresh(page, boundA2.claims, 'PIN login');

    // Fault injection only: expire this throwaway backend's already-issued
    // access token while preserving its genuine HttpOnly refresh cookie.
    // A real process restart must use the app's shared 401 handler, not an
    // injected success or an unverified local profile, to recover access.
    const expiredAccess = execFileSync('python', ['-c',
      "import sys,json,time,jwt; d=json.load(sys.stdin); p=d['claims']; p['exp']=time.time()-60; print(jwt.encode(p,d['secret'],algorithm='HS256'))"
    ], { input: JSON.stringify({ claims: boundA2.claims, secret: TEST_JWT_SECRET }), encoding: 'utf8' }).trim();
    await page.evalPage(`window.Capacitor.nativePromise('SecureStoragePlugin', 'set', {
      key: 'nua_token', value: ${JSON.stringify(expiredAccess)}
    })`);
    log('restarting with an expired access token and the real existing refresh cookie');
    await driver.execute('mobile: terminateApp', { bundleId: BUNDLE_ID });
    await wait(2000);
    await driver.execute('mobile: launchApp', { bundleId: BUNDLE_ID });
    await connectWebviewContext(driver);
    page = makePageDriver(driver);
    await waitForOutcomeAfterSubmit(page);
    await navigateToPos(page);
    const recoveredPin = await captureBoundToken(page);
    if (recoveredPin.token === expiredAccess || recoveredPin.claims.exp <= Date.now() / 1000) {
      throw new Error('Cold restart did not replace the expired access token');
    }
    for (const key of ['sub', 'businessId', 'deviceId', 'sessionId']) {
      if (recoveredPin.claims[key] !== boundA2.claims[key]) throw new Error(`Cold refresh changed ${key}`);
    }
    await assertWebviewRefresh(page, recoveredPin.claims, 'expired-access cold restart');
    log('expired access recovered through the real app after process restart; native refresh cookie survived');

    // ── Phase 3: offline cash sale, real outage, restart, reconnect, sync ─
    await setNetwork(false);

    log('ringing up one cash sale while offline');
    await page.click(`[data-testid="product-${productA.id}"]`);
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
        pendingBeforeRestart = await countPendingInDb(page.evalPage, dbNameFor(ownerA.user.businessId));
        if (pendingBeforeRestart > 0) break;
        await wait(500);
      }
    }
    if (pendingBeforeRestart !== 1) {
      throw new Error(`Expected exactly 1 queued offline transaction before restart, found ${pendingBeforeRestart}`);
    }
    log('exactly 1 transaction is queued offline, as expected');

    // Captured now, not inferred later from whatever the server happens to
    // report after sync -- this is the exact idempotency key (and full
    // payload) offlineQueue.js's own replay would resend, used below to
    // require an exact match and to prove a duplicate submission is safe.
    const queuedPayload = await getPendingPayloadInDb(page.evalPage, dbNameFor(ownerA.user.businessId));
    if (!queuedPayload || !queuedPayload.clientOpId) {
      throw new Error(`Expected the queued record's payload to carry a nonempty clientOpId, got: ${JSON.stringify(queuedPayload)}`);
    }
    log(`captured the queued sale's real idempotency key before restart: clientOpId=${queuedPayload.clientOpId}`);

    log('restarting the app process — a real terminate+relaunch, not a reload');
    await driver.execute('mobile: terminateApp', { bundleId: BUNDLE_ID });
    await wait(2000);
    await driver.execute('mobile: launchApp', { bundleId: BUNDLE_ID });
    await connectWebviewContext(driver);
    page = makePageDriver(driver);

    log('confirming the queued sale survived the restart while still offline');
    let pendingAfterRestart = 0;
    {
      const deadline = Date.now() + 20000;
      while (Date.now() < deadline) {
        try {
          pendingAfterRestart = await countPendingInDb(page.evalPage, dbNameFor(ownerA.user.businessId));
        } catch (error) {
          log(`countPendingInDb failed right after restart (${error.message}) — retrying`);
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

    log('confirming protected screens stay blocked until the server re-verifies this session');
    const authErrorShown = await page.evalPage(`!!document.querySelector('[role="alert"]') && document.body.innerText.includes('Unable to check your session')`);
    if (!authErrorShown) {
      const dump = await page.evalPage(`document.body.innerText.slice(0, 300)`).catch(() => '(unavailable)');
      throw new Error(`Expected the "Unable to check your session" gate after a cold restart while offline. Page text: ${dump}`);
    }
    log('confirmed: the app parked on the auth-error gate rather than authorising offline access after a cold restart');

    await setNetwork(true);

    const triedAgain = await page.clickButtonWithText('Try again');
    if (!triedAgain) throw new Error('Expected a "Try again" button on the auth-error gate');
    log('tapped "Try again" now that the backend is reachable again');
    await wait(2000);

    // ── Phase 4: business A's pending record is inaccessible from B ──────
    // Snapshot and log out BEFORE navigating back to the POS terminal --
    // useOfflineQueue only auto-flushes while mounted inside POSTerminal.jsx
    // (confirmed by reading hooks/useOfflineQueue.js's own mount scope), so
    // this window is safe: A's sale is still durably queued and untouched.
    const pendingStillQueued = await countPendingInDb(page.evalPage, dbNameFor(ownerA.user.businessId));
    if (pendingStillQueued !== 1) {
      throw new Error(`Expected A's sale to still be queued (1) before switching businesses, found ${pendingStillQueued}`);
    }
    log('logging out of owner A to switch to an independent second business');
    await logoutViaUI(page);
    await page.waitForSelector('[data-testid="login-page"]', 15000);

    const ownerB = await createIndependentSecondBusiness(ownerA.token, runId);
    if (ownerB.businessId === ownerA.user.businessId) throw new Error('Business B unexpectedly shares business A\'s id');
    log(`logging in as the independent second-business owner ${ownerB.email}`);
    await loginWithPassword(page, ownerB.email, ownerB.password);
    await waitForOutcomeAfterSubmit(page);
    await navigateToPos(page);
    log('owner B reached the POS terminal on the same physical device/app install');

    const devicesB = await fetchDevices(ownerB.token);
    if (devicesB.length !== 1) {
      throw new Error(`Expected exactly 1 device registered for business B, found ${devicesB.length}: ${JSON.stringify(devicesB)}`);
    }
    if (devicesB[0].id === deviceA.id) {
      throw new Error('Business B was bound to business A\'s own device id — binding did not isolate per business');
    }
    log(`business B registered its own, separate device: deviceId=${devicesB[0].id} (business A's was ${deviceA.id})`);

    // Reading A's database directly from B's session only proves
    // preservation (the row wasn't deleted/migrated) -- it says nothing
    // about whether the real APPLICATION itself would ever expose or
    // replay it under B. The POS terminal's own offline-queue-banner
    // (POSTerminal.jsx) is driven by useOfflineQueue's real queuedCount for
    // whichever business is currently activated -- its absence here is the
    // app's own UI proving B's session shows no sign of A's record, not an
    // inference from the storage layer alone.
    const bannerVisibleUnderB = await page.evalPage(`!!document.querySelector('[data-testid="offline-queue-banner"]')`);
    if (bannerVisibleUnderB) {
      throw new Error('The real app\'s own offline-queue-banner is visible under business B -- it should show no sign of business A\'s queued sale');
    }
    log('confirmed via the real app\'s own UI: no offline-queue-banner is shown under business B\'s session');

    const pendingForBWhileActive = await countPendingInDb(page.evalPage, dbNameFor(ownerB.businessId));
    if (pendingForBWhileActive !== 0) {
      throw new Error(`Expected business B's own queue to be empty, found ${pendingForBWhileActive}`);
    }
    const pendingForAWhileBActive = await countPendingInDb(page.evalPage, dbNameFor(ownerA.user.businessId));
    if (pendingForAWhileBActive !== 1) {
      throw new Error(`Expected business A's queued sale to still exist untouched while B is active, found ${pendingForAWhileBActive}`);
    }
    log('confirmed: business A\'s pending offline record still exists untouched (preservation, not a claim of encrypted/unreadable storage), and business B\'s own queue is empty, while B is the active session');

    const devicesVisibleToB = await fetchDevices(ownerB.token);
    if (devicesVisibleToB.some((d) => d.id === deviceA.id)) {
      throw new Error('Business A\'s device row leaked into business B\'s device list');
    }
    log('confirmed: business A\'s device row is not visible to business B\'s own device list either');

    // ── Back to A: reconnect, sync, verify exactly one transaction ───────
    // Password re-entry exercises the other login path after the real PIN
    // refresh and cold-start recovery already proved above.
    log('logging out of owner B and back into owner A via password to resume the offline sale');
    await logoutViaUI(page);
    await page.waitForSelector('[data-testid="login-page"]', 15000);
    await loginWithPassword(page, ownerA.email, ownerA.password);
    await connectWebviewContext(driver);
    page = makePageDriver(driver);
    await waitForOutcomeAfterSubmit(page);
    await navigateToPos(page);

    // This is the live, currently-active bound session -- the one Phase 5
    // below must prove revocation actually rejects, not the separate
    // registration-time token (see that phase's own comment).
    const boundA3 = await captureBoundToken(page);
    if (boundA3.claims.deviceId !== deviceA.id) throw new Error(`Final bound token carries deviceId ${boundA3.claims.deviceId}, expected ${deviceA.id}`);

    log('waiting for the queue to auto-flush now that the backend is back online');
    let synced = false;
    {
      const deadline = Date.now() + 90000; // useOfflineQueue's own 30s safety-net poll, with margin
      while (Date.now() < deadline) {
        let pendingNow;
        try {
          pendingNow = await countPendingInDb(page.evalPage, dbNameFor(ownerA.user.businessId));
        } catch (error) {
          log(`webview eval failed mid-poll (${error.message}) — reconnecting and retrying`);
          await connectWebviewContext(driver);
          page = makePageDriver(driver);
          continue;
        }
        if (pendingNow === 0) { synced = true; break; }
        await wait(3000);
      }
    }
    if (!synced) throw new Error('Offline queue never drained after reconnecting within the timeout');
    log('offline queue drained — verifying against the backend itself, not just the client');

    const transactions = await fetchJson('/api/transactions?payment_method=Cash', {
      headers: { Authorization: `Bearer ${ownerA.token}` },
    });
    if (transactions.length !== 1) {
      throw new Error(`Expected exactly 1 server-side transaction after sync, found ${transactions.length}: ${JSON.stringify(transactions)}`);
    }
    const [txn] = transactions;
    if (Math.abs(txn.total - productA.price) > 0.01) {
      throw new Error(`Synced transaction total $${txn.total} doesn't match the expected $${productA.price}`);
    }
    if (!txn.clientOpId) throw new Error('Synced transaction is missing its durable idempotency key');
    if (txn.clientOpId !== queuedPayload.clientOpId) {
      throw new Error(`Synced transaction's clientOpId ${txn.clientOpId} doesn't match the one captured from the queued record before restart (${queuedPayload.clientOpId})`);
    }
    if (txn.businessId !== ownerA.user.businessId) throw new Error('Synced transaction belongs to another business');
    log(`exactly one server-side transaction exists: id=${txn.id} total=$${txn.total} clientOpId=${txn.clientOpId} businessId=${txn.businessId} (matches the pre-restart queued record exactly)`);

    log('proving a duplicate submission of the exact same queued payload is safe (no second transaction)');
    const replayResult = await fetchJson('/api/transactions', {
      method: 'POST',
      headers: { Authorization: `Bearer ${ownerA.token}` },
      body: JSON.stringify(queuedPayload),
    });
    if (replayResult.id !== txn.id) {
      throw new Error(`Replaying the queued payload returned a different transaction (${replayResult.id}) instead of the existing one (${txn.id})`);
    }
    const transactionsAfterReplay = await fetchJson('/api/transactions?payment_method=Cash', {
      headers: { Authorization: `Bearer ${ownerA.token}` },
    });
    if (transactionsAfterReplay.length !== 1) {
      throw new Error(`Expected still exactly 1 transaction after replaying the same clientOpId, found ${transactionsAfterReplay.length}`);
    }
    log('confirmed: replaying the exact same queued payload returned the existing transaction, created no duplicate');

    // ── Phase 5: owner revocation rejects the bound session AND refresh ──
    // ownerA.token is the SEPARATE session /api/auth/register minted --
    // never bound to this device, since bind-device was only ever called
    // for the real UI's own login sessions. Revoking the device with it is
    // fine (owner role is enough to revoke), but testing *against* it would
    // prove nothing about this device's binding -- that unbound session
    // has no device claim to revoke in the first place, so it's expected
    // (and correct) to keep working after this device is revoked. The
    // actual proof has to use boundA3, the real session the UI itself is
    // using right now.
    log('proving refresh succeeds for the real bound session BEFORE revocation (establishing a real baseline)');
    const refreshBeforeRevoke = await page.evalPage(`
      window.Capacitor.nativePromise('NuaRefreshSession', 'refresh', { url: ${JSON.stringify(BACKEND)} })
        .then(r => ({ status: r.status }))
        .catch(e => ({ error: e.message }))
    `);
    log(`refresh attempt before revocation: ${JSON.stringify(refreshBeforeRevoke)}`);
    if (refreshBeforeRevoke.status !== 200) {
      throw new Error(`Expected pre-revocation refresh 200, got ${JSON.stringify(refreshBeforeRevoke)}`);
    }

    log('revoking owner A\'s own bound device (using the separate registration session, which owner role alone makes valid for this)');
    await revokeDevice(ownerA.token, deviceA.id);

    const registrationSessionStillValid = await fetchJson('/api/auth/me', { headers: { Authorization: `Bearer ${ownerA.token}` } });
    if (registrationSessionStillValid.id !== ownerA.user.id) throw new Error('The independent, never-bound registration session unexpectedly broke after revocation');
    log('confirmed: the independent, never-bound registration session remains valid after revocation (revocation is scoped to the device, not the whole account)');

    let rejectedAfterRevoke = false;
    try {
      await fetchJson('/api/auth/me', { headers: { Authorization: `Bearer ${boundA3.token}` } });
    } catch (error) {
      rejectedAfterRevoke = /HTTP 401|HTTP 403/.test(error.message);
      if (!rejectedAfterRevoke) throw error;
    }
    if (!rejectedAfterRevoke) throw new Error('Expected the real bound session\'s access token to be rejected on its next request after revocation');
    log('confirmed: the real bound session\'s access token is rejected on its very next request after revocation');

    const refreshAfterRevoke = await page.evalPage(`
      window.Capacitor.nativePromise('NuaRefreshSession', 'refresh', { url: ${JSON.stringify(BACKEND)} })
        .then(r => ({ status: r.status }))
        .catch(e => ({ error: e.message }))
    `);
    log(`refresh attempt after revocation: ${JSON.stringify(refreshAfterRevoke)}`);
    if (refreshAfterRevoke.status !== 401 && refreshAfterRevoke.status !== 403) {
      throw new Error(`Expected refresh rejection 401/403 after revocation, got ${JSON.stringify(refreshAfterRevoke)}`);
    }
    log('confirmed: refresh is specifically rejected after device revocation');
    log('PASS: password/PIN refresh, expired-access cold restart, offline sale recovery, tenant isolation, exact replay and bearer/refresh revocation all verified on the real iOS Simulator.');
  } finally {
    try { await driver.deleteSession(); } catch { /* best-effort cleanup */ }
    if (backendProc) { try { backendProc.kill('SIGTERM'); } catch { /* already gone */ } }
  }
}

// A real CI run's own log capture lost every one of this script's console.log
// lines outright despite the run demonstrably getting deep into the flow --
// macOS Node's stdout to a piped, non-TTY destination can be non-blocking,
// so a same-tick process.exit() truncates whatever's still queued.
// fs.writeSync bypasses that queue entirely, and the setTimeout before exit
// gives any already-queued async writes a turn to flush first.
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
