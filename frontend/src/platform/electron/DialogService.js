/** Electron implementation — the Windows host's BrowserWindow is a real
 * Chromium renderer (sandboxed, but window.confirm/prompt/alert are
 * standard DOM APIs, not gated by the host's IPC bridge or permission
 * handler), so the web implementation already behaves correctly here
 * without any native dialog IPC. See apps/windows/src/main.cjs. */
export * from '../web/DialogService';
