import { parseDeviceMap, loginDeviceHeaders } from '../deviceMap';
/** Electron implementation — the device id is persisted the same way the
 * auth token is (`nua:device-id-*`, OS-encrypted via `EncryptedStore` +
 * `windowsCrypto`), not in the host's in-memory Chromium session. Unlike
 * the Capacitor adapter, there's no OS-reported device-info API to call
 * here (Electron has no `@capacitor/device` equivalent exposed by this
 * host); the backend assigns the identity on `register()` the same way
 * it does for every platform, this just remembers the id it returned. */
async function identities() {
  return parseDeviceMap(await window.nuaDesktop.getDeviceMap());
}
export async function getStoredDeviceId(businessId) {
  const map = await identities();
  if (businessId && Object.keys(map).length) return map[businessId] || null;
  return window.nuaDesktop.getDeviceId();
}
export async function getLoginHeaders() {
  return loginDeviceHeaders(await identities(), await window.nuaDesktop.getDeviceId());
}

export async function rememberDevice(businessId, deviceId) {
  const map = await identities(); map[businessId] = deviceId;
  await window.nuaDesktop.setDeviceMap(JSON.stringify(map));
  await window.nuaDesktop.setDeviceId(deviceId);
}

export async function register(extra = {}) {
  const { devicesAPI } = await import('../../services/api');
  const desktopInfo = await window.nuaDesktop.getInfo();
  const res = await devicesAPI.register({
    platform: 'windows',
    deviceName: desktopInfo.hostname || 'Unnamed Windows PC',
    deviceModel: 'Windows PC',
    appVersion: desktopInfo.version,
    ...extra,
  });
  await rememberDevice(res.data.businessId, res.data.id);
  return res.data;
}

export async function heartbeat(businessId) {
  const deviceId = await getStoredDeviceId(businessId);
  if (!deviceId) return;
  const { devicesAPI } = await import('../../services/api');
  try { await devicesAPI.heartbeat(deviceId); } catch { /* best-effort */ }
}
