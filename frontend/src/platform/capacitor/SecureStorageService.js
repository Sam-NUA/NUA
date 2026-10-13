import { Preferences } from '@capacitor/preferences';

/** CORRECTED (verified against the installed plugin's own native source,
 * not assumed from its name): @capacitor/preferences is plain
 * `context.getSharedPreferences(group, MODE_PRIVATE)` on Android
 * (node_modules/@capacitor/preferences/android/.../Preferences.java) and
 * plain `UserDefaults.standard` on iOS
 * (node_modules/@capacitor/preferences/ios/.../Preferences.swift) —
 * NEITHER is encrypted at rest, and iOS's path doesn't touch Keychain at
 * all. An earlier pass of this codebase's own docs incorrectly stated
 * this was "EncryptedSharedPreferences-backed on Android" — that was
 * never true; see docs/platform/SECURITY_MODEL.md's corrected version.
 *
 * What this buys over plain localStorage, honestly: on Android, a
 * MODE_PRIVATE SharedPreferences file is sandboxed to this app's UID the
 * same way localStorage already is inside the WebView — no meaningfully
 * different theft-resistance. On iOS, UserDefaults is likewise
 * app-sandboxed, not hardware-backed. Real Keystore/Keychain-backed
 * storage needs a dedicated secure-storage plugin, not this one — tracked
 * in MOBILE_DESKTOP_BACKLOG.md as genuinely not done, not merely "v2
 * hardening" of something already secure.
 *
 * Used anyway (rather than reverted to plain localStorage) because it's
 * still the correct platform-abstraction shape to swap a real
 * secure-storage plugin into later without touching every call site
 * again — see platform/index.js.
 *
 * ALSO mirrors into plain localStorage under the same key: ~20 existing
 * pages (NotificationBell, AshChat, StaffRoster, etc. — see
 * MOBILE_DESKTOP_BACKLOG.md) read `localStorage.getItem('nua_token')`
 * directly for their own axios calls rather than going through
 * services/api.js's interceptor. Without this mirror those pages would
 * silently get no token at all on Android/iOS the moment the primary
 * path moved to Preferences-only storage — a real functional break, not
 * a theoretical one. */
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
