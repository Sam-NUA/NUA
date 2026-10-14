import { SecureStoragePlugin } from 'capacitor-secure-storage-plugin';
import { Preferences } from '@capacitor/preferences';

const TOKEN_KEY = 'nua_token';
const SIGNED_OUT_KEY = 'nua_native_signed_out';
async function purgePlaintext() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem('nua_device_token');
  await Preferences.remove({ key: TOKEN_KEY });
}

// A keys lookup distinguishes an absent key from a locked/broken OS store.
// Legacy plaintext credentials are deliberately not trusted on upgrade:
// one fresh login is safer than a best-effort, fail-open migration.
export async function getToken() {
  await purgePlaintext();
  const { value: signedOut } = await Preferences.get({ key: SIGNED_OUT_KEY });
  if (signedOut === 'true') return null;
  const { value: keys } = await SecureStoragePlugin.keys();
  if (!keys.includes(TOKEN_KEY)) return null;
  const { value } = await SecureStoragePlugin.get({ key: TOKEN_KEY });
  return value || null;
}

export async function setToken(token) {
  await purgePlaintext();
  await Preferences.set({ key: SIGNED_OUT_KEY, value: 'true' });
  await SecureStoragePlugin.set({ key: TOKEN_KEY, value: token });
  await Preferences.remove({ key: SIGNED_OUT_KEY });
}

export async function clearToken() {
  // This non-secret tombstone survives even if OS deletion fails.
  await Preferences.set({ key: SIGNED_OUT_KEY, value: 'true' });
  await purgePlaintext();
  // Overwrite first: even a subsequent remove failure cannot revive a token.
  await SecureStoragePlugin.set({ key: TOKEN_KEY, value: '' });
  await SecureStoragePlugin.remove({ key: TOKEN_KEY });
}
