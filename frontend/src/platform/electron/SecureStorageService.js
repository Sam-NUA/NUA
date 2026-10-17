/** Electron implementation — routes through `nua:token-*`, backed by
 * `EncryptedStore` + `windowsCrypto` (real Windows DPAPI via
 * `safeStorage`, verified in apps/windows/test/store.test.cjs and
 * smoke.cjs) rather than the host's own Chromium session, which is
 * deliberately in-memory (`session.fromPartition('nua-windows-
 * foundation')`, no `persist:` prefix) so nothing Chromium manages on
 * its own survives a restart. Unlike the Capacitor adapter's
 * `@capacitor/preferences` (verified elsewhere to be plain
 * SharedPreferences/UserDefaults, not actually encrypted — see
 * docs/platform/SECURITY_MODEL.md), this one really is OS-encrypted at
 * rest: `safeStorage.isEncryptionAvailable()` is required and checked on
 * every call, with no plaintext fallback. */
export async function getToken() {
  return window.nuaDesktop.getToken();
}

export async function setToken(token) {
  await window.nuaDesktop.setToken(token);
}

export async function clearToken() {
  await window.nuaDesktop.clearToken();
}
