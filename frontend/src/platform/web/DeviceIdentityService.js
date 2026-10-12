/** Web implementation — device identity is optional for a browser tab (it
 * isn't a dedicated terminal the way a tablet/kiosk is), so this never
 * auto-registers. If a caller explicitly registers anyway (e.g. an owner
 * wants to track a particular back-office browser), the id persists the
 * same way the Capacitor adapter's does. */
const DEVICE_ID_KEY = 'nua_device_id';

export async function getStoredDeviceId() {
  return localStorage.getItem(DEVICE_ID_KEY);
}

export async function register(info) {
  const { devicesAPI } = await import('../../services/api');
  const res = await devicesAPI.register({ platform: 'web', ...info });
  localStorage.setItem(DEVICE_ID_KEY, res.data.id);
  return res.data;
}

export async function heartbeat() {
  const deviceId = await getStoredDeviceId();
  if (!deviceId) return;
  const { devicesAPI } = await import('../../services/api');
  try { await devicesAPI.heartbeat(deviceId); } catch { /* best-effort */ }
}
