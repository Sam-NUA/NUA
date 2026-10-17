// Local routing hints only. The server verifies every selected device's tenant.
export function parseDeviceMap(value) {
  if (!value) return Object.create(null);
  const map = JSON.parse(value);
  if (!map || Array.isArray(map) || typeof map !== 'object' || Object.keys(map).length > 30
      || Object.entries(map).some(([business, id]) => !business || typeof id !== 'string' || !id || id.length > 200)) {
    throw new Error('Terminal identities require recovery');
  }
  return Object.assign(Object.create(null), map);
}
export function loginDeviceHeaders(map, legacy) {
  return Object.keys(map).length ? { 'X-Device-Map': JSON.stringify(map) }
    : legacy ? { 'X-Device-Id': legacy } : {};
}
