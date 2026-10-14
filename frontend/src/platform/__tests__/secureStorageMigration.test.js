const mockSecureGet = jest.fn();
const mockSecureKeys = jest.fn();
const mockSecureSet = jest.fn();
const mockSecureRemove = jest.fn();
const mockPrefRemove = jest.fn();
const mockPrefGet = jest.fn();
const mockPrefSet = jest.fn();
jest.mock('capacitor-secure-storage-plugin', () => ({ SecureStoragePlugin: {
  get: (...a) => mockSecureGet(...a), keys: (...a) => mockSecureKeys(...a),
  set: (...a) => mockSecureSet(...a), remove: (...a) => mockSecureRemove(...a),
} }));
jest.mock('@capacitor/preferences', () => ({ Preferences: { remove: (...a) => mockPrefRemove(...a), get: (...a) => mockPrefGet(...a), set: (...a) => mockPrefSet(...a) } }));
const { getToken, setToken, clearToken } = require('../capacitor/SecureStorageService');

describe('native credentials fail closed', () => {
  beforeEach(() => {
    jest.resetAllMocks(); localStorage.clear();
    mockPrefGet.mockResolvedValue({ value: null });
    mockSecureKeys.mockResolvedValue({ value: ['nua_token'] });
    mockSecureGet.mockResolvedValue({ value: 'secure-token' });
  });
  it('reads OS storage and purges both plaintext credentials', async () => {
    localStorage.setItem('nua_token', 'plaintext'); localStorage.setItem('nua_device_token', 'trusted');
    expect(await getToken()).toBe('secure-token');
    expect(localStorage.length).toBe(0);
    expect(mockPrefRemove).toHaveBeenCalledWith({ key: 'nua_token' });
  });
  it('requires a fresh login when only legacy plaintext remains', async () => {
    localStorage.setItem('nua_token', 'legacy'); mockSecureKeys.mockResolvedValue({ value: [] });
    expect(await getToken()).toBeNull();
    expect(mockSecureGet).not.toHaveBeenCalled(); expect(mockSecureSet).not.toHaveBeenCalled();
  });
  it('propagates a locked OS store instead of using plaintext', async () => {
    localStorage.setItem('nua_token', 'legacy'); mockSecureKeys.mockRejectedValue(new Error('locked'));
    await expect(getToken()).rejects.toThrow('locked');
    expect(mockSecureGet).not.toHaveBeenCalled(); expect(localStorage.getItem('nua_token')).toBeNull();
  });
  it('propagates decryption failures for an existing key', async () => {
    mockSecureGet.mockRejectedValue(new Error('decrypt failed'));
    await expect(getToken()).rejects.toThrow('decrypt failed');
  });
  it('does not revive an OS token after a failed logout deletion', async () => {
    mockPrefGet.mockResolvedValue({ value: 'true' });
    expect(await getToken()).toBeNull();
    expect(mockSecureGet).not.toHaveBeenCalled();
  });
  it('never mirrors a new token into localStorage', async () => {
    await setToken('fresh'); expect(mockSecureSet).toHaveBeenCalledWith({ key: 'nua_token', value: 'fresh' });
    expect(localStorage.getItem('nua_token')).toBeNull();
  });
  it('overwrites the credential before removal and reports removal failure', async () => {
    mockSecureRemove.mockRejectedValue(new Error('remove failed'));
    await expect(clearToken()).rejects.toThrow('remove failed');
    expect(mockSecureSet).toHaveBeenCalledWith({ key: 'nua_token', value: '' });
    expect(mockSecureSet.mock.invocationCallOrder[0]).toBeLessThan(mockSecureRemove.mock.invocationCallOrder[0]);
  });
});
