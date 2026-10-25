import { useEffect } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { supported, runFleetPoll } from '../services/printerFleetClient';

// Mounted once at the authenticated app root, not on the Hardware Settings
// page. Only managers/owners with an explicitly enabled gateway can claim.
export default function PrinterFleetDaemon() {
  const { user } = useAuth();
  const businessId = user && ['owner', 'manager'].includes(user.role) ? user.businessId : null;
  useEffect(() => {
    if (!businessId || !supported()) return undefined;
    let alive = true;
    const tick = () => { if (alive) runFleetPoll(businessId).catch(() => {}); };
    tick();
    const timer = window.setInterval(tick, 3500);
    return () => { alive = false; window.clearInterval(timer); };
  }, [businessId]);
  return null;
}
