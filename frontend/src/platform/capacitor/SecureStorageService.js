import { Preferences } from '@capacitor/preferences';

/** @capacitor/preferences, backed by EncryptedSharedPreferences on Android
 * — meaningfully better than plain localStorage for the one real theft
 * target in this app's client-side storage (the access token; see
 * docs/platform/SECURITY_MODEL.md). Not Keystore-hardware-backed — that
 * would need a dedicated secure-storage plugin and is tracked in
 * MOBILE_DESKTOP_BACKLOG.md as a v2 hardening step, not done here.
 *
 * ALSO mirrors into plain localStorage under the same key: ~20 existing
 * pages (NotificationBell, AshChat, StaffRoster, etc. — see
 * MOBILE_DESKTOP_BACKLOG.md) read `localStorage.getItem('nua_token')`
 * directly for their own axios calls rather than going through
 * services/api.js's interceptor. Without this mirror those pages would
 * silently get no token at all on Android the moment the primary path
 * moved to Preferences-only storage — a real functional break, not a
 * theoretical one. This mirror is the pragmatic fix until those call
 * sites are migrated to this service directly; it means the token isn't
 * exclusively Keystore-backed as long as they exist. */
const TOKEN_KEY = 'nua_token';

export async function getToken() {
  const { value } = await Preferences.get({ key: TOKEN_KEY });
  return value;
}

export async function setToken(token) {
  await Preferences.set({ key: TOKEN_KEY, value: token });
  try { localStorage.setItem(TOKEN_KEY, token); } catch { /* storage unavailable — Preferences is still set */ }
}

export async function clearToken() {
  await Preferences.remove({ key: TOKEN_KEY });
  try { localStorage.removeItem(TOKEN_KEY); } catch { /* ignore */ }
}
