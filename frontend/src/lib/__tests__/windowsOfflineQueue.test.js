const mockCreate = jest.fn();
let mockToken = 'token-A';
jest.mock('../../services/api', () => ({ transactionsAPI: { create: (...a) => mockCreate(...a) } }));
jest.mock('../../platform/sessionToken', () => ({ getSessionToken: () => mockToken }));
jest.mock('../telemetry', () => ({ trackEvent: jest.fn() }));
let queue, records, active;
beforeEach(() => {
  jest.resetModules(); jest.clearAllMocks(); mockToken = 'token-A'; records = new Map(); active = null;
  window.nuaDesktop = {
    activateOffline: jest.fn(async business => { active = business; }),
    lockOffline: jest.fn(async () => { active = null; }),
    readOffline: jest.fn(async (kind, business) => {
      if (active !== business) throw new Error('locked');
      return JSON.parse(JSON.stringify(records.get(business + kind) || []));
    }),
    mutateOffline: jest.fn(async (kind, business, commands) => {
      if (active !== business) throw new Error('locked');
      let rows = records.get(business + kind) || [];
      for (const { op, value } of commands) {
        if (op === 'delete') rows = rows.filter(row => row.id !== value);
        else { rows = rows.filter(row => row.id !== value.id); rows.push(JSON.parse(JSON.stringify(value))); }
      }
      records.set(business + kind, rows);
    }),
  };
  queue = require('../offlineQueue');
});
afterEach(() => { queue.lock(); delete window.nuaDesktop; });
it('persists the real checkout payload before HTTP and replays its operation after restart', async () => {
  await queue.activate('A');
  const payload = { paymentMethod: 'Cash', customerId: null, items: [{ productId: 'p', quantity: 1, modifiers: [{ name: 'milk' }] }],
    appliedDiscounts: [], pointsRedeemed: 0, walkInName: 'Walk in' };
  mockCreate.mockImplementationOnce(async body => {
    expect((await queue.getQueued())[0].payload).toEqual(body);
    throw Object.assign(new Error('lost response'), { request: {} });
  });
  expect((await queue.createTransactionResilient(payload)).data.queuedOffline).toBe(true);
  const operation = (await queue.getQueued())[0].payload.clientOpId;
  queue.lock(); jest.resetModules(); queue = require('../offlineQueue');
  await queue.activate('A');
  mockCreate.mockResolvedValueOnce({ data: { id: 'server-sale' } });
  await queue.flushQueue();
  expect(mockCreate.mock.calls[1][0]).toMatchObject({ ...payload, clientOpId: operation });
  expect(await queue.getQueued()).toEqual([]);
});
it('keeps A records inaccessible during B login and recovers them on return', async () => {
  await queue.activate('A'); await queue.enqueueTransaction({ paymentMethod: 'Cash', clientOpId: 'same-operation' });
  queue.lock(); mockToken = 'token-B'; await queue.activate('B');
  expect(await queue.getQueued()).toEqual([]);
  queue.lock(); mockToken = 'token-A'; await queue.activate('A');
  expect((await queue.getQueued())[0].payload.clientOpId).toBe('same-operation');
});
it('fails closed when encrypted host persistence fails', async () => {
  await queue.activate('A'); window.nuaDesktop.mutateOffline.mockRejectedValueOnce(new Error('OS encryption unavailable'));
  await expect(queue.createTransactionResilient({ paymentMethod: 'cash', items: [] })).rejects.toThrow('OS encryption');
  expect(mockCreate).not.toHaveBeenCalled();
});
