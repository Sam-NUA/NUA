const mockRefresh = jest.fn();
const mockRetry = jest.fn();
let mockResponseFailure;
mockRetry.interceptors = {
  request: { use: jest.fn() },
  response: { use: jest.fn((_success, fail) => { mockResponseFailure = fail; }) },
};
const mockSetToken = jest.fn(async token => { localStorage.setItem('nua_token', token); });
const mockClearToken = jest.fn(async () => { localStorage.removeItem('nua_token'); });
jest.mock('axios', () => ({ __esModule: true, default: {
  create: () => mockRetry, post: (...args) => mockRefresh(...args),
} }));
jest.mock('../../platform', () => ({ isNative: () => false, SecureStorageService: {
  getToken: async () => global.localStorage.getItem('nua_token'),
  setToken: (...args) => mockSetToken(...args), clearToken: () => mockClearToken(),
} }));
require('../api');
const token = (sub, businessId) => `header.${btoa(JSON.stringify({ sub, businessId }))}.signature`;
const errorFor = value => ({ response: { status: 401 }, config: {
  url: '/products', headers: {}, _usesStaffSession: true, _sessionToken: value,
} });
beforeEach(() => {
  jest.clearAllMocks(); localStorage.clear();
  // CRA resets mock implementations before each test.
  mockSetToken.mockImplementation(async value => { localStorage.setItem('nua_token', value); });
  mockClearToken.mockImplementation(async () => { localStorage.removeItem('nua_token'); });
});
it('does not revive a signed-out session through an old refresh cookie', async () => {
  const error = errorFor(null);
  await expect(mockResponseFailure(error)).rejects.toBe(error);
  expect(mockRefresh).not.toHaveBeenCalled(); expect(mockSetToken).not.toHaveBeenCalled();
});
it.each([['staff-B', 'business-A'], ['staff-A', 'business-B'], ['staff-B', 'business-B']])('rejects refresh identity %s / %s', async (sub, business) => {
  const previous = token('staff-A', 'business-A'); localStorage.setItem('nua_token', previous);
  mockRefresh.mockResolvedValueOnce({ data: { token: token(sub, business) } });
  const error = errorFor(previous);
  await expect(mockResponseFailure(error)).rejects.toBe(error);
  expect(mockSetToken).not.toHaveBeenCalled(); expect(mockRetry).not.toHaveBeenCalled();
  expect(localStorage.getItem('nua_token')).toBeNull();
});
it('refreshes and retries the same verified actor', async () => {
  const previous = token('staff-A', 'business-A'); const next = `${previous}new`;
  localStorage.setItem('nua_token', previous);
  mockRefresh.mockResolvedValueOnce({ data: { token: next } }); mockRetry.mockResolvedValueOnce({ data: 'ok' });
  expect(await mockResponseFailure(errorFor(previous))).toEqual({ data: 'ok' });
  expect(mockSetToken).toHaveBeenCalledWith(next); expect(localStorage.getItem('nua_token')).toBe(next);
});
