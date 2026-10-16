const mockPlatform = jest.fn(), mockCommit = jest.fn(), mockRefresh = jest.fn(), mockClear = jest.fn();
jest.mock('@capacitor/core', () => ({
  Capacitor: { getPlatform: () => mockPlatform() },
  registerPlugin: () => ({ commit: (...args) => mockCommit(...args),
    refresh: (...args) => mockRefresh(...args), clear: (...args) => mockClear(...args) }),
}));
const { commitNativeRefresh, refreshNativeSession, clearDurableNativeRefresh } = require('../nativeRefreshSession');
const token = `header.${btoa(JSON.stringify({ sessionId: 'verified-session' }))}.signature`;
beforeEach(() => { jest.clearAllMocks(); mockPlatform.mockReturnValue('ios'); });
it('commits the verified session reference without passing a refresh secret through JS', async () => {
  mockCommit.mockResolvedValue({ committed: true });
  await commitNativeRefresh('https://api.example.com', token);
  expect(mockCommit).toHaveBeenCalledWith({ url: 'https://api.example.com', sessionId: 'verified-session' });
});
it('does not commit a token without a terminal session', async () => {
  const legacy = `header.${btoa('{}')}.signature`;
  await expect(commitNativeRefresh('https://api.example.com', legacy)).rejects.toThrow('Verified terminal session');
  expect(mockCommit).not.toHaveBeenCalled();
});
it('fails sign-in when durable commitment fails', async () => {
  mockCommit.mockRejectedValue(new Error('Keychain locked'));
  await expect(commitNativeRefresh('https://api.example.com', token)).rejects.toThrow('Keychain locked');
});
it.each(['android', 'web'])('does not change %s cookie persistence', async platform => {
  mockPlatform.mockReturnValue(platform);
  await commitNativeRefresh('https://api.example.com', token);
  expect(mockCommit).not.toHaveBeenCalled();
});
it.each([401, 403])('preserves server rejection %s for the shared auth handler', async status => {
  mockRefresh.mockResolvedValue({ status, data: { detail: 'Rejected' } });
  await expect(refreshNativeSession('https://api.example.com')).rejects.toMatchObject({ response: { status } });
});
it('keeps a native storage error distinguishable from server rejection', async () => {
  mockRefresh.mockRejectedValue(new Error('Keychain unavailable'));
  await expect(refreshNativeSession('https://api.example.com')).rejects.toThrow('Keychain unavailable');
});
it('cannot report logout complete without durable native deletion', async () => {
  mockClear.mockResolvedValue({ cleared: false });
  await expect(clearDurableNativeRefresh('https://api.example.com')).rejects.toThrow('not cleared');
});
