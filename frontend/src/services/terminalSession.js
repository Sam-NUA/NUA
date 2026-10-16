import axios from 'axios';
import { DeviceIdentityService, SecureStorageService, isNative } from '../platform';
import { getSessionToken } from '../platform/sessionToken';

// Protected routes and queue activation wait for this to succeed. No offline
// cold-start authorisation, and no best-effort unbound native session.
export async function bindTerminalSession(user, token) {
  if (!isNative()) return token;
  const current = () => {
    if (getSessionToken() !== token) throw new Error('Sign-in session changed');
  };
  current();
  let deviceId = await DeviceIdentityService.getStoredDeviceId(user.businessId);
  current();
  if (!deviceId) {
    const device = await DeviceIdentityService.register();
    current();
    if (device.businessId !== user.businessId) throw new Error('Terminal business changed');
    deviceId = device.id;
  }
  const result = await axios.post(`${process.env.REACT_APP_BACKEND_URL}/api/auth/bind-device`, { deviceId }, {
    adapter: 'fetch', withCredentials: true, headers: { Authorization: `Bearer ${token}` },
  });
  current();
  if (!result.data.token || result.data.businessId !== user.businessId || result.data.deviceId !== deviceId) {
    throw new Error('Terminal session could not be verified');
  }
  await DeviceIdentityService.rememberDevice(user.businessId, deviceId);
  current();
  await SecureStorageService.setToken(result.data.token);
  return result.data.token;
}
