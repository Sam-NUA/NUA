'use strict';
const { app, BrowserWindow, Menu, protocol, ipcMain, session, dialog, safeStorage } = require('electron');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { APP_ORIGIN, isAppUrl, apiOrigin, assetPath, safeFilename, safeHtmlDocument, assertSender, contentSecurityPolicy } = require('./policy.cjs');
const { renderReceipt } = require('./receipt.cjs');
const { EncryptedStore } = require('./encrypted-store.cjs');
const { OfflineStore } = require('./offline-store.cjs');
const { windowsCrypto } = require('./windows-crypto.cjs');
const { waitForWindowsKey } = require('./crypto-readiness.cjs');
protocol.registerSchemesAsPrivileged([{ scheme: 'nua', privileges: { standard: true, secure: true, supportFetchAPI: true, corsEnabled: true } }]);
let mainWindow;
let printing = false;
const renderer = path.resolve(__dirname, '../renderer');
const inputMode = process.argv.includes('--touch') ? 'touch' : 'desktop';
const mime = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json', '.png': 'image/png', '.svg': 'image/svg+xml', '.ico': 'image/x-icon', '.woff2': 'font/woff2' };
function guarded(channel, handler) {
  ipcMain.handle(channel, (event, ...args) => { assertSender(event, mainWindow); return handler(...args); });
}
function restrict(contents) {
  contents.setWindowOpenHandler(() => ({ action: 'deny' }));
  contents.on('will-navigate', (event, target) => { if (!isAppUrl(target)) event.preventDefault(); });
  contents.on('will-redirect', (event, target) => { if (!isAppUrl(target)) event.preventDefault(); });
  contents.on('will-attach-webview', event => event.preventDefault());
}
async function printDocument(html, printerName = '') {
  // A renderer-selected printer must be one of the OS spooler devices.
  // This remains a user-reviewed print dialog, not unattended silent printing.
  if (typeof printerName !== 'string' || printerName.length > 255) throw new Error('Invalid printer name');
  if (printerName && !(await mainWindow.webContents.getPrintersAsync()).some(p => p.name === printerName)) {
    throw new Error('Selected printer is not installed on this Windows device');
  }
  if (printing) throw new Error('A print job is already awaiting an outcome');
  printing = true;
  // javascript: false means a malformed or hostile document can distort the
  // print preview, never execute — this is the control that makes printHtml
  // safe for callers (e.g. the kitchen docket) whose HTML isn't run through
  // receipt.cjs's own field-level escaping.
  const win = new BrowserWindow({ show: false, parent: mainWindow, webPreferences: { nodeIntegration: false, contextIsolation: true, sandbox: true, javascript: false } });
  restrict(win.webContents);
  try {
    await win.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent(html));
    // Never claim a physical print or retry after an unknown spool outcome.
    return await new Promise(resolve => win.webContents.print({ silent: false, printBackground: false, ...(printerName ? { deviceName: printerName } : {}) }, success => resolve({ status: success ? 'submitted' : 'cancelled-or-failed' })));
  } finally { win.destroy(); printing = false; }
}
async function printReceipt(receipt, printerName) {
  return printDocument(renderReceipt(receipt), printerName); // validation before opening any OS dialog
}
async function printHtml(html, printerName) {
  return printDocument(safeHtmlDocument(html), printerName);
}
async function saveFile(filename, data) {
  safeFilename(filename);
  if (!(data instanceof Uint8Array)) throw new Error('Invalid file data');
  if (data.byteLength > 50 * 1024 * 1024) throw new Error('File too large');
  const result = await dialog.showSaveDialog(mainWindow, { defaultPath: filename });
  if (result.canceled || !result.filePath) return { status: 'cancelled' };
  await fs.writeFile(result.filePath, Buffer.from(data));
  return { status: 'saved' };
}
async function start() {
  if (process.platform !== 'win32') throw new Error('This host is supported on Windows only');
  const config = JSON.parse(await fs.readFile(path.join(renderer, 'host-config.json'), 'utf8'));
  const origin = apiOrigin(config.apiOrigin);
  await waitForWindowsKey({ safeStorage, sessionDataPath: app.getPath('sessionData') });
  // The Chromium session itself stays in-memory (below) so nothing Chromium
  // manages on its own survives a restart; the auth token and device id are
  // instead persisted explicitly here, through the same OS-encrypted,
  // atomic store already built and tested for the cash queue, so they
  // *do* survive a restart without ever touching plain disk.
  const secureStore = new EncryptedStore(path.join(app.getPath('userData'), 'secure'), windowsCrypto(safeStorage));
  // In-memory web session prevents credentials being persisted by Chromium.
  const hostSession = session.fromPartition('nua-windows-foundation');
  const offlineStore = new OfflineStore({ store: secureStore,
    readToken: () => secureStore.read('auth-token'),
    verifyToken: async token => {
      const result = await fetch(origin + '/api/auth/me', { headers: { Authorization: `Bearer ${token}` },
        credentials: 'omit', redirect: 'error', signal: AbortSignal.timeout(15000) });
      if (!result.ok) throw new Error('Terminal session could not be verified');
      return result.json();
    },
  });
  hostSession.setPermissionRequestHandler((_wc, _permission, callback) => callback(false));
  hostSession.setPermissionCheckHandler(() => false);
  hostSession.on('will-download', event => event.preventDefault());
  hostSession.protocol.handle('nua', async request => {
    try {
      if (request.method !== 'GET') return new Response(null, { status: 405 });
      let file = assetPath(request.url, renderer);
      let data;
      try { data = await fs.readFile(file); }
      catch (e) {
        if (!['ENOENT', 'EISDIR'].includes(e.code) || path.extname(file)) return new Response(null, { status: 404 });
        file = path.join(renderer, 'index.html');
        data = await fs.readFile(file);
      }
      return new Response(data, { headers: { 'Content-Type': mime[path.extname(file)] || 'application/octet-stream', 'Content-Security-Policy': contentSecurityPolicy(origin), 'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'no-store' } });
    } catch { return new Response(null, { status: 403 }); }
  });
  // Requests are limited to bundled resources and the explicitly configured API.
  hostSession.webRequest.onBeforeRequest((details, callback) => {
    let allowed = isAppUrl(details.url);
    try { allowed ||= [origin, origin.replace('https:', 'wss:')].includes(new URL(details.url).origin); } catch {}
    callback({ cancel: !allowed });
  });
  mainWindow = new BrowserWindow({ width: 1400, height: 950, minWidth: 1024, minHeight: 768, title: 'NUA POS', icon: path.join(__dirname, '../build/icon.ico'), autoHideMenuBar: true, webPreferences: { preload: path.join(__dirname, 'preload.cjs'), session: hostSession, sandbox: true, contextIsolation: true, nodeIntegration: false, webSecurity: true, devTools: !app.isPackaged } });
  restrict(mainWindow.webContents);
  Menu.setApplicationMenu(null);
  guarded('nua:info', () => ({ version: app.getVersion(), bridgeVersion: 1, platform: 'windows', inputMode, releaseChannel: 'foundation', updates: 'manual-review-only', secureAuthIntegrated: true, offlineSyncIntegrated: true, hostname: os.hostname() }));
  const windowState = () => ({ fullscreen: mainWindow.isFullScreen(), maximized: mainWindow.isMaximized(), minimized: mainWindow.isMinimized() });
  const notifyWindowState = () => {
    if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send('nua:window-state-changed', windowState());
  };
  for (const change of ['enter-full-screen', 'leave-full-screen', 'maximize', 'unmaximize', 'restore', 'minimize']) {
    mainWindow.on(change, notifyWindowState);
  }
  guarded('nua:window-state', windowState);
  guarded('nua:fullscreen', value => {
    if (typeof value !== 'boolean') throw new Error('Invalid fullscreen value');
    if (!value && mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.setFullScreen(value);
    if (!value && mainWindow.isMaximized()) mainWindow.unmaximize();
    notifyWindowState();
    return windowState();
  });
  // A visible and keyboard-accessible escape route even if React fails to mount.
  mainWindow.webContents.on('before-input-event', (event, input) => {
    if (input.type !== 'keyDown' || input.isAutoRepeat) return;
    if (input.key === 'F11') {
      event.preventDefault();
      mainWindow.setFullScreen(!mainWindow.isFullScreen());
    } else if (input.key === 'Escape' && mainWindow.isFullScreen()) {
      event.preventDefault();
      mainWindow.setFullScreen(false);
    }
  });
  guarded('nua:printers', async () => (await mainWindow.webContents.getPrintersAsync()).map(p => ({ name: p.name, displayName: p.displayName, isDefault: p.isDefault })));
  guarded('nua:print-receipt', printReceipt);
  guarded('nua:print-html', printHtml);
  guarded('nua:save-file', saveFile);
  // Scope keys are fixed, app-level values, not business/account-scoped —
  // the same shape SecureStorageService already uses on Android/iOS
  // (a single 'nua_token' key); per-tenant scoping happens at the backend
  // JWT level, not in client storage. See CashOrderQueue in
  // packages/platform-core for the one store that IS identity-scoped.
  guarded('nua:token-get', () => secureStore.read('auth-token'));
  guarded('nua:token-set', value => {
    if (typeof value !== 'string' || !value || value.length > 8192) throw new Error('Invalid token value');
    offlineStore.lock();
    return secureStore.write('auth-token', value);
  });
  guarded('nua:token-clear', () => { offlineStore.lock(); return secureStore.write('auth-token', null); });
  guarded('nua:offline-activate', business => offlineStore.activate(business));
  guarded('nua:offline-lock', () => offlineStore.lock());
  guarded('nua:offline-read', (kind, business) => offlineStore.read(kind, business));
  guarded('nua:offline-mutate', (kind, business, commands) => offlineStore.mutate(kind, business, commands));
  guarded('nua:device-map-get', () => secureStore.read('device-map'));
  guarded('nua:device-map-set', value => {
    if (typeof value !== 'string' || value.length > 16000) throw new Error('Invalid terminal identities');
    const map = JSON.parse(value);
    if (!map || Array.isArray(map) || typeof map !== 'object' || Object.keys(map).length > 30
        || Object.entries(map).some(([business, id]) => !business || typeof id !== 'string' || !id || id.length > 200)) throw new Error('Invalid terminal identities');
    return secureStore.write('device-map', value);
  });
  guarded('nua:device-id-get', () => secureStore.read('device-id'));
  guarded('nua:device-id-set', value => {
    if (typeof value !== 'string' || !value || value.length > 200) throw new Error('Invalid device id');
    return secureStore.write('device-id', value);
  });
  mainWindow.on('closed', () => { mainWindow = null; });
  await mainWindow.loadURL(APP_ORIGIN + '/');
}
if (!app.requestSingleInstanceLock()) app.quit();
else {
  app.on('second-instance', () => { if (mainWindow) { if (mainWindow.isMinimized()) mainWindow.restore(); mainWindow.focus(); } });
  app.whenReady().then(start).catch(() => { dialog.showErrorBox('NUA Windows could not start', 'Use a verified Windows foundation build with an explicitly configured HTTPS API origin.'); app.quit(); });
  app.on('window-all-closed', () => app.quit());
}
