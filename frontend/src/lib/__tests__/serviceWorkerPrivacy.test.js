/** @jest-environment node */
const fs = require('node:fs');
const vm = require('node:vm');

test.each(['/api/auth/me', '/bookings-api/reservations'])('private API %s never falls back to a previous actor cache', async path => {
  const listeners = {};
  const cache = { open: jest.fn(), match: jest.fn() };
  const fetch = jest.fn(async () => { throw new Error('offline'); });
  const context = { URL, Response, fetch, caches: cache, self: {
    addEventListener: (type, callback) => { listeners[type] = callback; },
  } };
  vm.runInNewContext(fs.readFileSync('public/service-worker.js', 'utf8'), context);
  let response;
  listeners.fetch({ request: { method: 'GET', mode: 'cors', url: `https://app.example${path}` },
    respondWith: value => { response = value; } });
  const result = await response;
  expect(result.status).toBe(503);
  expect(await result.json()).toEqual({ offline: true });
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(cache.open).not.toHaveBeenCalled();
  expect(cache.match).not.toHaveBeenCalled();
});


test('activation removes old caches that may contain private booking responses', async () => {
  const listeners = {};
  const cache = { keys: async () => ['nua-shell-v3', 'nua-shell-v4'], delete: jest.fn(async () => true) };
  const claim = jest.fn(async () => {});
  vm.runInNewContext(fs.readFileSync('public/service-worker.js', 'utf8'), {
    URL, Response, caches: cache, self: { clients: { claim },
      addEventListener: (type, callback) => { listeners[type] = callback; } },
  });
  let pending;
  listeners.activate({ waitUntil: promise => { pending = promise; } });
  await pending;
  expect(cache.delete).toHaveBeenCalledWith('nua-shell-v3');
  expect(cache.delete).not.toHaveBeenCalledWith('nua-shell-v4');
  expect(claim).toHaveBeenCalledTimes(1);
});
