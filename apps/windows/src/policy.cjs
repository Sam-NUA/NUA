'use strict';
const path = require('node:path');
const APP_ORIGIN = 'nua://app';
function isAppUrl(value) {
  try {
    const u = new URL(value);
    return u.protocol === 'nua:' && u.hostname === 'app' && !u.port && !u.username && !u.password;
  } catch { return false; }
}
function apiOrigin(value) {
  const u = new URL(value);
  if (u.protocol !== 'https:' || u.username || u.password || u.pathname !== '/' || u.search || u.hash) {
    throw new Error('API must be an explicit HTTPS origin');
  }
  return u.origin;
}
function assetPath(url, root) {
  if (!isAppUrl(url)) throw new Error('Foreign origin');
  const name = decodeURIComponent(new URL(url).pathname);
  if (name.includes('\0') || name.includes('\\') || name.split('/').some(p => p === '..' || p === '.')) {
    throw new Error('Invalid asset path');
  }
  const target = path.resolve(root, '.' + name);
  if (target !== root && !target.startsWith(root + path.sep)) throw new Error('Invalid asset path');
  return target;
}
function assertSender(event, window) {
  if (!window || window.isDestroyed() || event.sender !== window.webContents ||
      event.senderFrame !== window.webContents.mainFrame || !isAppUrl(event.senderFrame.url)) {
    throw new Error('Untrusted native command sender');
  }
}
function contentSecurityPolicy(api) {
  const origin = apiOrigin(api);
  return `default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https:; font-src 'self' data:; connect-src 'self' ${origin} ${origin.replace('https:', 'wss:')}; media-src 'self' blob:; object-src 'none'; base-uri 'none'; frame-src 'none'; frame-ancestors 'none'; form-action 'none'`;
}
module.exports = { APP_ORIGIN, isAppUrl, apiOrigin, assetPath, assertSender, contentSecurityPolicy };
