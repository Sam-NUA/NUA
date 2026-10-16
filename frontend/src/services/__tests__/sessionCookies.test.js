const mockNative = jest.fn(), mockClear = jest.fn();
jest.mock('@capacitor/core', () => ({
  Capacitor: { isNativePlatform: () => mockNative() },
  CapacitorCookies: { clearCookies: (...args) => mockClear(...args) },
}));
const { clearNativeSessionCookies } = require('../sessionCookies');
beforeEach(() => { jest.clearAllMocks(); });
it('clears only the native API cookie jar without a network request or reading secrets', async () => {
  mockNative.mockReturnValue(true); mockClear.mockResolvedValue(undefined);
  expect(await clearNativeSessionCookies('https://api.example.com')).toBe(true);
  expect(mockClear).toHaveBeenCalledWith({ url: 'https://api.example.com' });
});
it('leaves browser and Windows HttpOnly deletion to the server', async () => {
  mockNative.mockReturnValue(false);
  expect(await clearNativeSessionCookies('https://api.example.com')).toBe(false);
  expect(mockClear).not.toHaveBeenCalled();
});
it('propagates a failed native purge instead of reporting sign-out cleanup complete', async () => {
  mockNative.mockReturnValue(true); mockClear.mockRejectedValue(new Error('cookie store unavailable'));
  await expect(clearNativeSessionCookies('https://api.example.com')).rejects.toThrow('cookie store unavailable');
});
