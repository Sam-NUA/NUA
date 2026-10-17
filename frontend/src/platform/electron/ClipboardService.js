/** Electron implementation — reuses the web Clipboard API. Note: the
 * Windows host's session denies every permission check/request
 * (`setPermissionCheckHandler(() => false)` in main.cjs) — if a future
 * Chromium version starts gating user-gesture clipboard writes behind an
 * explicit permission query, this would need a native nuaDesktop IPC
 * instead. Not observed as a problem as of Electron 44; documented here
 * so a silent regression has a place to be looked up. */
export * from '../web/ClipboardService';
