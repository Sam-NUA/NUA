import { Device } from '@capacitor/device';
import { App } from '@capacitor/app';
import { Preferences } from '@capacitor/preferences';

/** Registers this physical device with the business on first launch
 * (App.js calls this once an owner/staff session exists — see
 * docs/platform/DEVICE_IDENTITY_MODEL.md), using real OS-reported device
 * info rather than anything the caller has to supply by hand. */
const DEVICE_ID_KEY = 'nua_device_id';

export async function getStoredDeviceId() {
  const { value } = await Preferences.get({ key: DEVICE_ID_KEY });
  return value;
}

export async function register(extra = {}) {
  const info = await Device.getInfo();
  let appVersion;
  try { ({ version: appVersion } = await App.getInfo()); } catch { appVersion = undefined; }
  const { devicesAPI } = await import('../../services/api');
  const res = await devicesAPI.register({
    platform: info.platform, // 'android' | 'ios'
    deviceName: info.name || `${info.manufacturer || ''} ${info.model || ''}`.trim() || 'Unnamed device',
    deviceModel: info.model,
    osVersion: info.osVersion,
    appVersion,
    ...extra,
  });
  await Preferences.set({ key: DEVICE_ID_KEY, value: res.data.id });
  return res.data;
}

export async function heartbeat() {
  const deviceId = await getStoredDeviceId();
  if (!deviceId) return;
  const { devicesAPI } = await import('../../services/api');
  try { await devicesAPI.heartbeat(deviceId); } catch { /* best-effort */ }
}
