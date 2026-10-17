import { parseDeviceMap, loginDeviceHeaders } from '../deviceMap';
it('routes by business without discarding a revoked business identity', () => {
  const map = parseDeviceMap('{"A":"DEV-A","B":"DEV-B"}');
  expect(JSON.parse(loginDeviceHeaders(map, 'old')['X-Device-Map'])).toEqual({ A: 'DEV-A', B: 'DEV-B' });
  expect(loginDeviceHeaders(parseDeviceMap(null), 'old')).toEqual({ 'X-Device-Id': 'old' });
});
it('rejects corrupt hints rather than silently starting an unregistered terminal', () => {
  for (const value of ['[]', 'null', '{"A":null}', 'broken']) expect(() => parseDeviceMap(value)).toThrow();
});
it('supports unusual tenant identifiers without prototype inheritance', () => {
  const map = parseDeviceMap(null); map.__proto__ = 'DEV-PROTO';
  expect(parseDeviceMap(JSON.stringify(map)).__proto__).toBe('DEV-PROTO');
  expect(map.constructor).toBeUndefined();
});
