// Directive Phase 11 — tiny external store (no Context needed: this never
// needs to re-validate or poll, only to go from "fine" to "tripped" once,
// the moment VersionGateMiddleware's 426 is ever seen) so api.js's response
// interceptor can report a 426 without importing React, and any component
// can subscribe to it with useSyncExternalStore.
let state = null; // null = fine; otherwise the 426 response body, e.g. {detail, minSupportedVersion}
const listeners = new Set();

export function tripVersionGate(detail) {
  state = detail || { detail: 'This app version is no longer supported. Please update.' };
  listeners.forEach((l) => l());
}

export function subscribeVersionGate(callback) {
  listeners.add(callback);
  return () => listeners.delete(callback);
}

export function getVersionGateSnapshot() {
  return state;
}
