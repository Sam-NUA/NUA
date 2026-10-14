import { useEffect } from 'react';
import { isNative, DeviceIdentityService } from '../platform';
const HEARTBEAT_INTERVAL_MS = 5 * 60 * 1000;

// AuthContext registers and binds before mounting protected routes. This hook
// only reports activity; registration failure can never yield an unbound till.
export default function useDeviceRegistration(user) {
  useEffect(() => {
    if (!user || !isNative()) return;
    const beat = () => DeviceIdentityService.heartbeat(user.businessId).catch(() => {});
    beat();
    const timer = setInterval(beat, HEARTBEAT_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [user]);
}
