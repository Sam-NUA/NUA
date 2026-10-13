/**
 * MOBILE_DESKTOP_BACKLOG.md item 2 — real Keystore/Keychain-backed token
 * storage (capacitor-secure-storage-plugin) replacing the previous,
 * never-actually-encrypted @capacitor/preferences path. The native
 * plugins themselves can't run outside a real device/emulator, so this
 * mocks both and tests the one piece of real new logic this file adds:
 * getToken() migrating an existing Preferences-stored token into the new
 * secure store rather than silently signing an upgraded install out.
 */
const mockSecureGet = jest.fn();
const mockSecureSet = jest.fn();
const mockSecureRemove = jest.fn();
const mockPrefGet = jest.fn();
const mockPrefSet = jest.fn();
const mockPrefRemove = jest.fn();

jest.mock('capacitor-secure-storage-plugin', () => ({
  SecureStoragePlugin: {
    get: (...args) => mockSecureGet(...args),
    set: (...args) => mockSecureSet(...args),
    remove: (...args) => mockSecureRemove(...args),
  },
}));
jest.mock('@capacitor/preferences', () => ({
  Preferences: {
    get: (...args) => mockPrefGet(...args),
    set: (...args) => mockPrefSet(...args),
    remove: (...args) => mockPrefRemove(...args),
  },
}));

const { getToken, setToken, clearToken } = require('../capacitor/SecureStorageService');

describe('capacitor SecureStorageService', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    try { localStorage.clear(); } catch { /* jsdom always has it */ }
  });

  it('returns the token straight from the secure store when already migrated', async () => {
    mockSecureGet.mockResolvedValue({ value: 'secure-token' });
    const token = await getToken();
    expect(token).toBe('secure-token');
    expect(mockPrefGet).not.toHaveBeenCalled();
  });

  it('migrates an existing Preferences-stored token into the secure store on first read', async () => {
    mockSecureGet.mockRejectedValue(new Error('not found')); // plugin throws per its own README when a key is missing
    mockPrefGet.mockResolvedValue({ value: 'legacy-token' });
    const token = await getToken();
    expect(token).toBe('legacy-token');
    expect(mockSecureSet).toHaveBeenCalledWith({ key: 'nua_token', value: 'legacy-token' });
  });

  it('returns null/undefined, not a crash, when neither store has a token (logged out)', async () => {
    mockSecureGet.mockRejectedValue(new Error('not found'));
    mockPrefGet.mockResolvedValue({ value: null });
    const token = await getToken();
    expect(token).toBeFalsy();
    expect(mockSecureSet).not.toHaveBeenCalled();
  });

  it('setToken writes only to the new secure store and cleans up the old one', async () => {
    await setToken('fresh-token');
    expect(mockSecureSet).toHaveBeenCalledWith({ key: 'nua_token', value: 'fresh-token' });
    expect(mockPrefRemove).toHaveBeenCalledWith({ key: 'nua_token' });
    expect(localStorage.getItem('nua_token')).toBe('fresh-token');
  });

  it('clearToken clears both stores and the localStorage mirror', async () => {
    localStorage.setItem('nua_token', 'x');
    await clearToken();
    expect(mockSecureRemove).toHaveBeenCalledWith({ key: 'nua_token' });
    expect(mockPrefRemove).toHaveBeenCalledWith({ key: 'nua_token' });
    expect(localStorage.getItem('nua_token')).toBeNull();
  });
});
