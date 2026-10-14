import React, { useCallback, useEffect, useState } from 'react';
import { devicesAPI } from '../../services/api';
import { detectPlatform, DeviceIdentityService, FileService } from '../../platform';
import { APP_VERSION } from '../../version';
import { captureScope, assertScope, getQueued, getQueuedCourseActions } from '../../lib/offlineQueue';
import { Button } from '../ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '../ui/card';
import SensitiveActionReauthDialog from '../security/SensitiveActionReauthDialog';

export default function DeviceManagementPanel() {
  const [devices, setDevices] = useState([]);
  const [currentId, setCurrentId] = useState(null);
  const [pending, setPending] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    setError(''); setBusy(true);
    try {
      const scope = captureScope();
      const [response, deviceId] = await Promise.all([devicesAPI.list(), DeviceIdentityService.getStoredDeviceId()]);
      assertScope(scope); setDevices(response.data || []); setCurrentId(deviceId);
    } catch { setError('Could not load terminals. Check your connection and try again.'); }
    finally { setBusy(false); }
  }, []);
  useEffect(() => { load(); }, [load]);
  const revoke = async () => {
    if (!pending) return;
    const device = pending; setPending(null); setBusy(true); setError('');
    try { await devicesAPI.revoke(device.id); await load(); }
    catch { setError('Could not revoke the terminal. Refresh its status before trying again.'); }
    finally { setBusy(false); }
  };
  const exportQueue = async () => {
    setError('');
    try {
      const scope = captureScope();
      const sales = await getQueued(scope); const kitchenActions = await getQueuedCourseActions(scope);
      assertScope(scope);
      await FileService.downloadFile(new Blob([JSON.stringify({ businessId: scope.businessId, exportedAt: new Date().toISOString(), sales, kitchenActions }, null, 2)], { type: 'application/json' }), 'nua-offline-review.json');
    } catch { setError('Could not export this business’s offline records. Sign in again and retry.'); }
  };
  return <Card data-testid="device-management-panel">
    <CardHeader><CardTitle>Registered terminals & offline review</CardTitle></CardHeader>
    <CardContent className="space-y-4">
      <p className="text-sm text-gray-600">NUA POS {APP_VERSION} · {detectPlatform()}{currentId ? ` · This terminal: ${currentId}` : ''}</p>
      <p className="text-sm">Revoke a lost or retired terminal to block its registered sessions.</p>
      {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" className="min-h-11" disabled={busy} onClick={load}>Refresh terminals</Button>
        <Button variant="outline" className="min-h-11" onClick={exportQueue} data-testid="export-offline-review">Export offline records</Button>
      </div>
      <div className="space-y-2">
        {devices.map(device => <div key={device.id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border p-3">
          <div><p className="font-medium">{device.deviceName}{device.id === currentId ? ' (this terminal)' : ''}</p>
            <p className="text-xs text-gray-600">{device.platform} · {device.appVersion || 'Version unknown'} · {device.status}</p>
            <p className="text-xs text-gray-600">Last seen: {device.lastSeenAt ? new Date(device.lastSeenAt).toLocaleString() : 'Not reported'}</p></div>
          <Button variant="outline" className="min-h-11" disabled={busy || device.status !== 'active'} onClick={() => setPending(device)} data-testid={`revoke-device-${device.id}`}>Revoke access</Button>
        </div>)}
        {!devices.length && !busy && <p className="text-sm text-gray-600">No registered terminals found.</p>}
      </div>
      <div className="border-t pt-4 space-y-2">
        <p className="text-sm">Rejected sales and uncertain kitchen actions stay saved for review. Export this business’s records and compare them with server transactions and kitchen tickets before repeating an action.</p>
        <p className="text-xs text-gray-600">Older unscoped queue databases are preserved separately. Support must verify ownership before recovering them.</p>
        </div>
      <SensitiveActionReauthDialog open={!!pending} label={`revoke access for ${pending?.deviceName || 'this terminal'}`} onVerified={revoke} onCancel={() => setPending(null)} />
    </CardContent>
  </Card>;
}
