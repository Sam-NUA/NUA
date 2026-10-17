import { parseDeviceMap, loginDeviceHeaders } from '../deviceMap';
/** Web implementation — device identity is optional for a browser tab (it
 * isn't a dedicated terminal the way a tablet/kiosk is), so this never
 * auto-registers. If a caller explicitly registers anyway (e.g. an owner
 * wants to track a particular back-office browser), the id persists the
 * same way the Capacitor adapter's does. */
const DEVICE_ID_KEY = 'nua_device_id';

const DEVICE_MAP_KEY = 'nua_device_map';
export async function getStoredDeviceId(businessId) {
  const map = parseDeviceMap(localStorage.getItem(DEVICE_MAP_KEY));
  if (businessId && Object.keys(map).length) return map[businessId] || null;
  return localStorage.getItem(DEVICE_ID_KEY);
}
export async function getLoginHeaders() {
  return loginDeviceHeaders(parseDeviceMap(localStorage.getItem(DEVICE_MAP_KEY)), localStorage.getItem(DEVICE_ID_KEY));
}

export async function rememberDevice(businessId, deviceId) {
  const map = parseDeviceMap(localStorage.getItem(DEVICE_MAP_KEY)); map[businessId] = deviceId;
  localStorage.setItem(DEVICE_MAP_KEY, JSON.stringify(map));
  localStorage.setItem(DEVICE_ID_KEY, deviceId);
}

export async function register(info) {
  const { devicesAPI } = await import('../../services/api');
  const res = await devicesAPI.register({ platform: 'web', ...info });
  await rememberDevice(res.data.businessId, res.data.id);
  return res.data;
}

export async function heartbeat(businessId) {
  const deviceId = await getStoredDeviceId(businessId);
  if (!deviceId) return;
  const { devicesAPI } = await import('../../services/api');
  try { await devicesAPI.heartbeat(deviceId); } catch { /* best-effort */ }
}
