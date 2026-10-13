/** Electron implementation — navigator.onLine and the online/offline
 * events are standard Chromium renderer behavior, unaffected by the
 * Windows host's IPC bridge or CSP. */
export * from '../web/NetworkService';
