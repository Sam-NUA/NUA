const mockPost = jest.fn(), mockRegister = jest.fn(), mockGetId = jest.fn(), mockSetToken = jest.fn(), mockRemember = jest.fn();
let mockToken;
jest.mock('axios', () => ({ __esModule: true, default: { post: (...a) => mockPost(...a) } }));
jest.mock('../../platform', () => ({ isNative: () => true,
  DeviceIdentityService: { getStoredDeviceId: (...a) => mockGetId(...a), register: () => mockRegister(), rememberDevice: (...a) => mockRemember(...a) },
  SecureStorageService: { setToken: (...a) => mockSetToken(...a) },
}));
jest.mock('../../platform/sessionToken', () => ({ getSessionToken: () => mockToken }));
const { bindTerminalSession } = require('../terminalSession');
beforeEach(() => { jest.clearAllMocks(); mockToken = 'initial'; });
it('registers then binds before returning a usable native token', async () => {
  mockGetId.mockResolvedValueOnce(null); mockRegister.mockResolvedValueOnce({ id: 'DEV-A', businessId: 'A' });
  mockPost.mockResolvedValueOnce({ data: { token: 'bound', deviceId: 'DEV-A', businessId: 'A' } });
  expect(await bindTerminalSession({ businessId: 'A' }, 'initial')).toBe('bound');
  expect(mockGetId).toHaveBeenCalledWith('A'); expect(mockRemember).toHaveBeenCalledWith('A', 'DEV-A'); expect(mockSetToken).toHaveBeenCalledWith('bound');
  expect(mockPost.mock.calls[0][2]).toMatchObject({ adapter: 'fetch', withCredentials: true });
});
it('does not replace a known revoked terminal when binding fails', async () => {
  mockGetId.mockResolvedValueOnce('DEV-A'); mockPost.mockRejectedValueOnce({ response: { status: 403 } });
  await expect(bindTerminalSession({ businessId: 'A' }, 'initial')).rejects.toMatchObject({ response: { status: 403 } });
  expect(mockRegister).not.toHaveBeenCalled(); expect(mockSetToken).not.toHaveBeenCalled();
});
it('a late registration response cannot bind after logout', async () => {
  mockGetId.mockResolvedValueOnce(null);
  mockRegister.mockImplementationOnce(async () => { mockToken = null; return { id: 'DEV-A', businessId: 'A' }; });
  await expect(bindTerminalSession({ businessId: 'A' }, 'initial')).rejects.toThrow('session changed');
  expect(mockPost).not.toHaveBeenCalled(); expect(mockSetToken).not.toHaveBeenCalled();
});
it('does not store a response for another business', async () => {
  mockGetId.mockResolvedValueOnce('DEV-A');
  mockPost.mockResolvedValueOnce({ data: { token: 'bad', deviceId: 'DEV-A', businessId: 'B' } });
  await expect(bindTerminalSession({ businessId: 'A' }, 'initial')).rejects.toThrow('could not be verified');
  expect(mockSetToken).not.toHaveBeenCalled();
});
