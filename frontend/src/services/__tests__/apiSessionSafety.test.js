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
  expect(mockRetry).toHaveBeenCalledWith(expect.objectContaining({ _sessionToken: next,
    headers: { Authorization: `Bearer ${next}` } }));
});

it('shares refresh and storage persistence across simultaneous expired requests', async () => {
  const previous = token('A', 'venue'); const next = `${previous}new`;
  localStorage.setItem('nua_token', previous);
  let finish;
  mockRefresh.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  mockRetry.mockResolvedValue({ data: 'ok' });
  const requests = [mockResponseFailure(errorFor(previous)), mockResponseFailure(errorFor(previous))];
  finish({ data: { token: next } });
  expect(await Promise.all(requests)).toEqual([{ data: 'ok' }, { data: 'ok' }]);
  expect(mockRefresh).toHaveBeenCalledTimes(1);
  expect(mockSetToken).toHaveBeenCalledTimes(1);
  expect(mockRetry).toHaveBeenCalledTimes(2);
});

it.each([undefined, 503])('keeps a credential retryable when refresh fails with status %s', async status => {
  const previous = token('A', 'venue'); localStorage.setItem('nua_token', previous);
  const unavailable = status ? { response: { status } } : new Error('offline');
  mockRefresh.mockRejectedValueOnce(unavailable);
  await expect(mockResponseFailure(errorFor(previous))).rejects.toBe(unavailable);
  expect(mockClearToken).not.toHaveBeenCalled(); expect(mockRetry).not.toHaveBeenCalled();
  expect(localStorage.getItem('nua_token')).toBe(previous);
});

it('clears the rejected session when refresh returns 403 (no cold-start retry)', async () => {
  const previous = token('A', 'venue'); localStorage.setItem('nua_token', previous);
  const rejected = { response: { status: 403 } }; mockRefresh.mockRejectedValueOnce(rejected);
  await expect(mockResponseFailure(errorFor(previous))).rejects.toBe(rejected);
  expect(mockRefresh).toHaveBeenCalledTimes(1);
  expect(mockClearToken).toHaveBeenCalledTimes(1); expect(mockRetry).not.toHaveBeenCalled();
});

it('retries once, then clears the session when refresh still returns 401', async () => {
  // A real CI run caught this: right after a native cold restart,
  // CapacitorHttp's native cookie jar hadn't synced the still-valid
  // refresh_token cookie back in yet, so the very first /auth/refresh came
  // back 401 "No refresh token" -- a transient race, not a real rejection.
  // One bounded retry recovers it; if the second attempt also 401s, the
  // session is genuinely gone and clears exactly as before.
  const previous = token('A', 'venue'); localStorage.setItem('nua_token', previous);
  const rejected = { response: { status: 401 } };
  mockRefresh.mockRejectedValueOnce(rejected).mockRejectedValueOnce(rejected);
  await expect(mockResponseFailure(errorFor(previous))).rejects.toBe(rejected);
  expect(mockRefresh).toHaveBeenCalledTimes(2);
  expect(mockClearToken).toHaveBeenCalledTimes(1); expect(mockRetry).not.toHaveBeenCalled();
});

it('recovers when a cold-start 401 is immediately followed by a working refresh', async () => {
  const previous = token('A', 'venue'); const next = `${previous}new`;
  localStorage.setItem('nua_token', previous);
  mockRefresh.mockRejectedValueOnce({ response: { status: 401 } })
    .mockResolvedValueOnce({ data: { token: next } });
  mockRetry.mockResolvedValueOnce({ data: 'ok' });
  expect(await mockResponseFailure(errorFor(previous))).toEqual({ data: 'ok' });
  expect(mockRefresh).toHaveBeenCalledTimes(2);
  expect(mockSetToken).toHaveBeenCalledWith(next); expect(localStorage.getItem('nua_token')).toBe(next);
});

it('cannot revive credentials when logout finishes during refresh', async () => {
  const previous = token('A', 'venue'); localStorage.setItem('nua_token', previous);
  let finish;
  mockRefresh.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  const request = mockResponseFailure(errorFor(previous));
  localStorage.removeItem('nua_token'); finish({ data: { token: `${previous}new` } });
  await expect(request).rejects.toThrow('Session changed');
  expect(mockSetToken).not.toHaveBeenCalled(); expect(mockRetry).not.toHaveBeenCalled();
});

it('does not overwrite a new account after an old refresh response arrives', async () => {
  const previous = token('A', 'venue'); const other = token('B', 'other');
  localStorage.setItem('nua_token', previous);
  let finish;
  mockRefresh.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  const request = mockResponseFailure(errorFor(previous));
  localStorage.setItem('nua_token', other); finish({ data: { token: `${previous}new` } });
  await expect(request).rejects.toThrow('Session changed');
  expect(mockSetToken).not.toHaveBeenCalled(); expect(mockClearToken).not.toHaveBeenCalled();
  expect(localStorage.getItem('nua_token')).toBe(other);
});
