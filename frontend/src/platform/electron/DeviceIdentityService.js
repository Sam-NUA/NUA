/** Electron implementation — the device id is persisted the same way the
 * auth token is (`nua:device-id-*`, OS-encrypted via `EncryptedStore` +
 * `windowsCrypto`), not in the host's in-memory Chromium session. Unlike
 * the Capacitor adapter, there's no OS-reported device-info API to call
 * here (Electron has no `@capacitor/device` equivalent exposed by this
 * host); the backend assigns the identity on `register()` the same way
 * it does for every platform, this just remembers the id it returned. */
export async function getStoredDeviceId() {
  return window.nuaDesktop.getDeviceId();
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
  await window.nuaDesktop.setDeviceId(res.data.id);
  return res.data;
}

export async function heartbeat() {
  const deviceId = await getStoredDeviceId();
  if (!deviceId) return;
  const { devicesAPI } = await import('../../services/api');
  try { await devicesAPI.heartbeat(deviceId); } catch { /* best-effort */ }
}
