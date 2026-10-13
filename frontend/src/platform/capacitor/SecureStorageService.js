import { Preferences } from '@capacitor/preferences';
import { SecureStoragePlugin } from 'capacitor-secure-storage-plugin';

/** Directive Phase 5/MOBILE_DESKTOP_BACKLOG.md item 2 — real hardening,
 * not the plain `@capacitor/preferences` this adapter used before (see
 * git history / SECURITY_MODEL.md for why that was never actually
 * encrypted: plain `SharedPreferences`/`UserDefaults`, same
 * theft-resistance as `localStorage`). `capacitor-secure-storage-plugin`
 * (verified against its own README, not assumed from its name) uses
 * Android Keystore + SharedPreferences on Android and Keychain (via
 * SwiftKeychainWrapper) on iOS — genuinely hardware/OS-backed, matching
 * what Windows's `safeStorage`/DPAPI path already does.
 *
 * Migration: an install updated from before this change may already
 * have a token sitting in the old `Preferences` store. `getToken()`
 * checks the new secure store first, and falls back to migrating that
 * old value in rather than silently signing the user out on upgrade.
 * New writes only ever go to the new store.
 *
 * ALSO still mirrors into plain `localStorage` under the same key — see
 * the original comment this replaces for why (~20 pages read
 * `localStorage.getItem('nua_token')` directly). That mirror's own
 * security property is unchanged by this swap: those call sites were
 * never going through Preferences either, and migrating them is tracked
 * separately (MOBILE_DESKTOP_BACKLOG.md item 2), not silently fixed by
 * this file alone. */
const TOKEN_KEY = 'nua_token';

export async function getToken() {
  try {
    const { value } = await SecureStoragePlugin.get({ key: TOKEN_KEY });
    if (value) return value;
  } catch { /* not found in the new store yet — fall through to migrate */ }
  const { value: legacy } = await Preferences.get({ key: TOKEN_KEY });
  if (legacy) {
    try { await SecureStoragePlugin.set({ key: TOKEN_KEY, value: legacy }); } catch { /* best-effort migration */ }
  }
  return legacy;
}

export async function setToken(token) {
  await SecureStoragePlugin.set({ key: TOKEN_KEY, value: token });
  try { await Preferences.remove({ key: TOKEN_KEY }); } catch { /* best-effort cleanup of the old store */ }
  try { localStorage.setItem(TOKEN_KEY, token); } catch { /* storage unavailable — secure store is still set */ }
}

export async function clearToken() {
  try { await SecureStoragePlugin.remove({ key: TOKEN_KEY }); } catch { /* already absent */ }
  try { await Preferences.remove({ key: TOKEN_KEY }); } catch { /* ignore */ }
  try { localStorage.removeItem(TOKEN_KEY); } catch { /* ignore */ }
}
