'use strict';
const { app, BrowserWindow, Menu, protocol, ipcMain, session, dialog } = require('electron');
const fs = require('node:fs/promises');
const path = require('node:path');
const { APP_ORIGIN, isAppUrl, apiOrigin, assetPath, assertSender, contentSecurityPolicy } = require('./policy.cjs');
const { renderReceipt } = require('./receipt.cjs');
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
async function printReceipt(receipt) {
  const html = renderReceipt(receipt); // validation before opening any OS dialog
  if (printing) throw new Error('A print job is already awaiting an outcome');
  printing = true;
  const win = new BrowserWindow({ show: false, parent: mainWindow, webPreferences: { nodeIntegration: false, contextIsolation: true, sandbox: true, javascript: false } });
  restrict(win.webContents);
  try {
    await win.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent(html));
    // Never claim a physical print or retry after an unknown spool outcome.
    return await new Promise(resolve => win.webContents.print({ silent: false, printBackground: false }, success => resolve({ status: success ? 'submitted' : 'cancelled-or-failed' })));
  } finally { win.destroy(); printing = false; }
}
async function start() {
  if (process.platform !== 'win32') throw new Error('This host is supported on Windows only');
  const config = JSON.parse(await fs.readFile(path.join(renderer, 'host-config.json'), 'utf8'));
  const origin = apiOrigin(config.apiOrigin);
  // In-memory web session prevents credentials being persisted by Chromium.
  // Native secure-store integration is a separate shared-auth release gate.
  const hostSession = session.fromPartition('nua-windows-foundation');
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
  mainWindow = new BrowserWindow({ width: 1400, height: 950, minWidth: 1024, minHeight: 768, title: 'NUA POS Foundation', autoHideMenuBar: true, webPreferences: { preload: path.join(__dirname, 'preload.cjs'), session: hostSession, sandbox: true, contextIsolation: true, nodeIntegration: false, webSecurity: true, devTools: !app.isPackaged } });
  restrict(mainWindow.webContents);
  Menu.setApplicationMenu(null);
  guarded('nua:info', () => ({ version: app.getVersion(), bridgeVersion: 1, platform: 'windows', inputMode, releaseChannel: 'foundation', updates: 'manual-review-only', secureAuthIntegrated: false, offlineSyncIntegrated: false }));
  guarded('nua:fullscreen', value => {
    if (typeof value !== 'boolean') throw new Error('Invalid fullscreen value');
    mainWindow.setFullScreen(value);
    return mainWindow.isFullScreen();
  });
  guarded('nua:printers', async () => (await mainWindow.webContents.getPrintersAsync()).map(p => ({ name: p.name, displayName: p.displayName, isDefault: p.isDefault })));
  guarded('nua:print-receipt', printReceipt);
  mainWindow.on('closed', () => { mainWindow = null; });
  await mainWindow.loadURL(APP_ORIGIN + '/');
}
if (!app.requestSingleInstanceLock()) app.quit();
else {
  app.on('second-instance', () => { if (mainWindow) { if (mainWindow.isMinimized()) mainWindow.restore(); mainWindow.focus(); } });
  app.whenReady().then(start).catch(() => { dialog.showErrorBox('NUA Windows could not start', 'Use a verified Windows foundation build with an explicitly configured HTTPS API origin.'); app.quit(); });
  app.on('window-all-closed', () => app.quit());
}
