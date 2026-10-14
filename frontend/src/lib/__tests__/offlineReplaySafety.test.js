import 'fake-indexeddb/auto';
import { activate, lock, enqueueTransaction, getQueued, flushQueue, createTransactionResilient, cacheCatalogue, getCachedCatalogue, captureScope, courseActionResilient, getQueuedCourseActions } from '../offlineQueue';
import { transactionsAPI } from '../../services/api';
jest.mock('../../services/api', () => ({ transactionsAPI: { create: jest.fn() } }));
jest.mock('../telemetry', () => ({ trackEvent: jest.fn() }));
if (!global.structuredClone) global.structuredClone = value => JSON.parse(JSON.stringify(value));
const networkError = () => Object.assign(new Error('offline'), { request: {} });
const sale = () => ({ items: [{ price: 5, quantity: 1 }], paymentMethod: 'Cash', clientOpId: `op-${Math.random()}` });
let business;
beforeEach(async () => {
  jest.resetAllMocks(); localStorage.setItem('nua_token', 'A-token');
  business = `A-${Math.random()}`; await activate(business);
});
afterEach(() => { lock(); localStorage.clear(); });
it('persists cash before the first HTTP attempt and removes only on success', async () => {
  transactionsAPI.create.mockImplementation(async body => {
    const rows = await getQueued(); expect(rows).toHaveLength(1);
    expect(rows[0].payload.clientOpId).toBe(body.clientOpId);
    return { data: { id: 'server-id' } };
  });
  await createTransactionResilient(sale()); expect(await getQueued()).toHaveLength(0);
});
it('keeps the same idempotency key across a lost response and replay', async () => {
  const payload = sale(); transactionsAPI.create.mockRejectedValueOnce(networkError());
  expect((await createTransactionResilient(payload)).data.queuedOffline).toBe(true);
  transactionsAPI.create.mockResolvedValueOnce({ data: { id: 'same-sale' } });
  await flushQueue();
  expect(transactionsAPI.create.mock.calls.map(call => call[0].clientOpId)).toEqual([payload.clientOpId, payload.clientOpId]);
  expect(await getQueued()).toHaveLength(0);
});
it('retains rejected sales for review without resubmitting them', async () => {
  await enqueueTransaction(sale());
  transactionsAPI.create.mockRejectedValue(Object.assign(new Error('rejected'), { response: { status: 422 } }));
  await flushQueue(); expect((await getQueued())[0].state).toBe('review');
  await flushQueue(); expect(transactionsAPI.create).toHaveBeenCalledTimes(1);
});
it('does not replay remaining A sales under B or delete A rows after switching', async () => {
  await enqueueTransaction(sale()); await enqueueTransaction(sale());
  let resolve;
  transactionsAPI.create.mockImplementation(() => new Promise(r => { resolve = r; }));
  const flush = flushQueue();
  while (!resolve) await new Promise(r => setTimeout(r, 0));
  lock(); localStorage.setItem('nua_token', 'B-token'); await activate(`B-${Math.random()}`);
  resolve({ data: { id: 'A-server-sale' } });
  await expect(flush).rejects.toThrow('session changed');
  expect(transactionsAPI.create).toHaveBeenCalledTimes(1); expect(await getQueued()).toHaveLength(0);
  localStorage.setItem('nua_token', 'A-token'); await activate(business);
  expect(await getQueued()).toHaveLength(2);
});
it('pins the replay credential and opts out of cookie-based refresh', async () => {
  await enqueueTransaction(sale()); transactionsAPI.create.mockResolvedValue({ data: { id: 'ok' } });
  await flushQueue(); const config = transactionsAPI.create.mock.calls[0][1];
  expect(config.headers.Authorization).toBe('Bearer A-token'); expect(config._skipAuthRefresh).toBe(true);
});
it.each([{ paymentMethod: 'Card' }, { paymentMethod: 'Cash', pointsRedeemed: 10 },
  { paymentMethod: 'Cash', paymentSplits: [{ method: 'card', amount: 5 }] }])('does not acknowledge uncertain non-cash payment offline: %p', async fields => {
  transactionsAPI.create.mockRejectedValue(networkError());
  await expect(createTransactionResilient({ ...sale(), ...fields })).rejects.toThrow('offline');
  expect(await getQueued()).toHaveLength(0);
});
it('does not save a delayed A menu into B cache', async () => {
  const scope = captureScope(); await activate(`B-${Math.random()}`);
  await cacheCatalogue([{ id: 'A-product' }], [], scope);
  expect((await getCachedCatalogue()).products).toEqual([]);
});

it('holds uncertain kitchen actions for review rather than repeating side effects', async () => {
  const run = jest.fn().mockRejectedValue(networkError());
  const result = await courseActionResilient('fire', { orderId: 'kitchen-ticket', course: 1 }, run);
  expect(result.requiresReview).toBe(true);
  expect((await getQueuedCourseActions())[0].state).toBe('review');
  await flushQueue();
  expect(run).toHaveBeenCalledTimes(1);
  expect(await getQueuedCourseActions()).toHaveLength(1);
});
