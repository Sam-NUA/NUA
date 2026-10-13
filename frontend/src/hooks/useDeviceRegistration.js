import { useEffect } from 'react';
import { isNative, DeviceIdentityService } from '../platform';
import { trackEvent } from '../lib/telemetry';

const HEARTBEAT_INTERVAL_MS = 5 * 60 * 1000;

/** Registers this physical device once a session exists, on native
 * platforms only — Android, iOS, or the Windows desktop shell (see
 * docs/platform/DEVICE_IDENTITY_MODEL.md) — a web tab is never
 * auto-registered (AuthContext's getStoredDeviceId() is then always
 * null, matching pre-device-identity behavior exactly). Sends a cheap
 * heartbeat on mount and periodically after that so an owner's device
 * list reflects real usage, not just the moment of registration. */
export default function useDeviceRegistration(user) {
  useEffect(() => {
    if (!user || !isNative()) return;
    let cancelled = false;

    (async () => {
      const existing = await DeviceIdentityService.getStoredDeviceId();
      if (!existing) {
        try { await DeviceIdentityService.register(); trackEvent('device_registered'); }
        catch { /* best-effort — a cashier mid-shift must never be blocked by this */ }
      }
      if (!cancelled) await DeviceIdentityService.heartbeat();
    })();

    const id = setInterval(() => { DeviceIdentityService.heartbeat(); }, HEARTBEAT_INTERVAL_MS);
    return () => { cancelled = true; clearInterval(id); };
  }, [user]);
}
