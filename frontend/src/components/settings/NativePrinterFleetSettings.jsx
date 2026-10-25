import React, { useCallback, useEffect, useState } from 'react';
import { Plus, Printer, RefreshCw, TestTube, Trash2 } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '../ui/card';
import { Button } from '../ui/button';
import { Input } from '../ui/input';
import { toast } from 'sonner';
import { useAuth } from '../../contexts/AuthContext';
import { printerFleetAPI } from '../../services/api';
import {
  supported, getFleetConfig, saveFleetConfig, discover, requestUsb,
  requestBluetooth, scanBle, registerFleetDevice, syncFleet, fanOut, testPayload,
} from '../../services/printerFleetClient';
import { detectPlatform } from '../../platform';

const baseDevice = () => ({
  name: '', station: 'Kitchen Printer', transport: 'wifi',
  host: '', port: '9100', address: '',
  serviceUUID: '', characteristicUUID: '',
  enabled: true, width: 48, codepage: 'cp437', cut: 'partial',
});
const uniqueId = () => 'dev_' + (window.crypto?.randomUUID?.() || Math.random().toString(36).slice(2)).replace(/-/g, '');
const STATIONS = ['Kitchen Printer', 'Bar Printer', 'Pizza Station', 'Receipt Printer'];
const MESSAGE = 'Submission means bytes accepted by the driver/interface, not that paper was physically printed.';

export default function NativePrinterFleetSettings() {
  const { user } = useAuth();
  const business = user?.businessId;
  const platform = detectPlatform();
  const [config, setConfig] = useState(null);
  const [form, setForm] = useState(baseDevice());
  const [discovered, setDiscovered] = useState([]);
  const [results, setResults] = useState([]);
  const [deliveryStatus, setDeliveryStatus] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const refresh = useCallback(async () => {
    if (!business || !supported()) return;
    try {
      const cfg = await getFleetConfig(business);
      setConfig(cfg);
      const devices = await discover();
      setDiscovered(devices);
      const status = await printerFleetAPI.status();
      setDeliveryStatus(status.data || []);
      setError('');
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Cannot load native printer settings');
    }
  }, [business]);

  useEffect(() => { refresh(); }, [refresh]);

  const update = (name, value) => setForm(f => ({ ...f, [name]: value }));
  const persist = async next => {
    await syncFleet(next);
    await saveFleetConfig(business, next);
    setConfig(next);
  };

  const add = async () => {
    if (!config) return;
    const name = form.name.trim();
    if (!name || !form.station.trim()) { toast.error('Printer name and station required'); return; }
    if (form.transport === 'wifi' && (!/^(?:\d{1,3}\.){3}\d{1,3}$/.test(form.host) ||
        !(Number(form.port) >= 1 && Number(form.port) <= 65535))) {
      toast.error('Provide a private-network IPv4 address and TCP port'); return;
    }
    if (['bluetooth','usb','ble','windows-spooler'].includes(form.transport) && !form.address) {
      toast.error('Select a discovered device'); return;
    }
    if (form.transport === 'ble' && (!form.serviceUUID || !form.characteristicUUID)) {
      toast.error('BLE printer service and writable characteristic UUID are required'); return;
    }
    setBusy(true);
    try {
      const device = { ...form, id: uniqueId(), name, station: form.station.trim(),
        port: Number(form.port), width: Number(form.width) };
      const next = { ...config, devices: [...config.devices, device] };
      if (next.devices.length > 32) throw new Error('Maximum 32 printers per gateway');
      await registerFleetDevice(next, { ...device, enabled: next.enabled && device.enabled });
      await saveFleetConfig(business, next);
      setConfig(next);
      setForm(baseDevice());
      toast.success('Printer added; configure and verify a physical test before service');
    } catch (err) { toast.error(err.response?.data?.detail || err.message); }
    finally { setBusy(false); }
  };

  const remove = async device => {
    if (!config) return;
    setBusy(true);
    try {
      await printerFleetAPI.disableDevice(device.id);
      const next = { ...config, devices: config.devices.filter(d => d.id !== device.id) };
      await saveFleetConfig(business, next);
      setConfig(next);
      toast.success('Printer disconnected from this NUA gateway');
    } catch (err) { toast.error(err.response?.data?.detail || err.message); }
    finally { setBusy(false); }
  };

  const toggle = async checked => {
    if (!config) return;
    setBusy(true);
    try {
      const next = { ...config, enabled: checked };
      await persist(next);
      toast(checked ? 'Gateway active. Keep NUA open and signed in to deliver dockets.' :
        'Automatic printing disabled for this gateway');
    } catch (err) { toast.error(err.response?.data?.detail || err.message); }
    finally { setBusy(false); }
  };

  const testAll = async () => {
    if (!config?.devices?.length) return;
    setBusy(true); setResults([]);
    try {
      const devices = config.devices.filter(d => d.enabled);
      const tested = await fanOut(devices, testPayload);
      const report = tested.map((r, i) => ({
        id: devices[i].id, name: devices[i].name,
        status: r.status === 'fulfilled' && r.value?.status === 'submitted' ? 'submitted' : 'uncertain',
        error: r.status === 'rejected' ? String(r.reason?.message || r.reason)
          : r.value?.status !== 'submitted' ? r.value?.reason || 'Not submitted' : '',
      }));
      setResults(report);
      if (report.some(x => x.status !== 'submitted')) toast.error('Some printers failed; review each result');
      else toast.success('Sent tests concurrently to all enabled printers. Check every paper ticket.');
    } finally { setBusy(false); }
  };

  const scan = async () => {
    setBusy(true);
    try {
      if (platform === 'android') await requestBluetooth();
      const devices = platform === 'ios' && form.transport === 'ble'
        ? await scanBle(form.serviceUUID) : await discover();
      setDiscovered(devices);
      toast('Device discovery complete');
    } catch (err) { toast.error(err.message); }
    finally { setBusy(false); }
  };

  if (!supported()) return (
    <Card><CardContent className="p-4 text-sm text-gray-600">
      Direct USB, Bluetooth and raw Wi-Fi printing requires the native NUA Android, iPad or Windows app.
      This browser can still use server printer routing and browser print previews.
    </CardContent></Card>
  );

  return <Card data-testid="native-printer-fleet">
    <CardHeader><CardTitle className="flex gap-2 items-center text-base"><Printer size={18} /> Native printer fleet</CardTitle></CardHeader>
    <CardContent className="space-y-4">
      <p className="text-sm text-gray-600">
        Add multiple kitchen, bar and receipt printers over Wi-Fi, USB or Bluetooth.
        Active printers receive their own copies concurrently, with one print job per physical target.
        Bluetooth Classic SPP and USB bulk are available on Android; Windows uses installed
        USB/Bluetooth printer drivers; iPad supports Wi-Fi and compatible vendor BLE GATT printers.
      </p>
      {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
      {config && <label className="flex items-center gap-3 font-medium text-sm">
        <input type="checkbox" checked={config.enabled} disabled={busy || !config.devices.length}
          onChange={e => toggle(e.target.checked)} data-testid="fleet-enable" />
        Enable automatic station printing on this terminal
      </label>}
      <p className="text-xs text-amber-700">
        One terminal acts as the designated print gateway. Keep it signed in and connected.
        Other NUA terminals can still take orders without duplicating its dockets.
        A printer with no live gateway cannot print. Failed/unknown print submissions require manual review.
      </p>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {config?.devices.map(d => <div key={d.id} className="border rounded-lg p-3 space-y-1" data-testid="fleet-device">
          <div className="flex justify-between gap-2">
            <strong className="text-sm">{d.name}</strong>
            <Button size="sm" variant="ghost" disabled={busy} onClick={() => remove(d)}
              aria-label={`Remove ${d.name}`}><Trash2 size={14}/></Button>
          </div>
          <p className="text-xs text-gray-600">{d.station} · {d.transport}</p>
          <p className="text-xs text-gray-500">{d.transport === 'wifi' ? `${d.host}:${d.port}` : d.address}</p>
        </div>)}
      </div>
      <div className="border rounded-lg p-3 space-y-3">
        <strong className="text-sm">Add another physical printer</strong>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          <label className="text-xs">Display name
            <Input data-testid="fleet-new-name" value={form.name} onChange={e => update('name', e.target.value)}
              placeholder="Kitchen receipt printer #2" />
          </label>
          <label className="text-xs">Station / docket route
            <Input list="fleet-stations" value={form.station}
              onChange={e => update('station', e.target.value)} />
            <datalist id="fleet-stations">{STATIONS.map(s => <option key={s} value={s}/>)}</datalist>
          </label>
          <label className="text-xs">Connection type
            <select aria-label="Connection type" className="w-full border rounded p-2" value={form.transport}
              onChange={e => setForm(f => ({ ...f, transport: e.target.value, address: '' }))}>
              <option value="wifi">Wi-Fi / Ethernet (TCP ESC/POS)</option>
              {platform === 'android' && <><option value="usb">Direct USB bulk</option><option value="bluetooth">Paired Bluetooth Classic SPP</option></>}
              {platform === 'electron' && <option value="windows-spooler">Installed Windows printer (USB / Bluetooth)</option>}
              {platform === 'ios' && <option value="ble">Bluetooth Low Energy / vendor GATT</option>}
            </select>
          </label>
          {form.transport === 'wifi' ? <>
            <label className="text-xs">LAN IPv4 address
              <Input placeholder="192.168.1.50" value={form.host} onChange={e => update('host', e.target.value)} />
            </label>
            <label className="text-xs">TCP port
              <Input type="number" min="1" max="65535" value={form.port}
                onChange={e => update('port', e.target.value)} />
            </label>
          </> : <>
            <label className="text-xs">Discovered device
              <select className="w-full border rounded p-2" aria-label="Discovered printer"
                value={form.address} onChange={e => update('address', e.target.value)}>
                <option value="">Choose device</option>
                {discovered.filter(d => d.transport === form.transport).map(d =>
                  <option key={d.address} value={d.address}>{d.name} · {d.address}</option>)}
              </select>
            </label>
            {form.transport === 'ble' && <>
              <label className="text-xs">BLE GATT service UUID
                <Input value={form.serviceUUID} onChange={e => update('serviceUUID', e.target.value)}/>
              </label>
              <label className="text-xs">BLE writable characteristic UUID
                <Input value={form.characteristicUUID} onChange={e => update('characteristicUUID', e.target.value)}/>
              </label>
            </>}
            <div className="flex flex-wrap items-end gap-2">
              <Button variant="outline" disabled={busy} onClick={scan}><RefreshCw size={14} className="mr-1" /> Scan</Button>
              {platform === 'android' && form.transport === 'usb' && form.address &&
                <Button variant="outline" disabled={busy} onClick={() => requestUsb(form.address)
                  .then(() => toast.success('USB permission granted'))
                  .catch(err => toast.error(err.message))}>Approve USB access</Button>}
            </div>
          </>}
          <label className="text-xs">Paper width
            <select className="w-full border rounded p-2" value={form.width}
              onChange={e => update('width', Number(e.target.value))}>
              <option value={48}>80mm (48 columns)</option><option value={32}>58mm (32 columns)</option>
            </select>
          </label>
          <label className="text-xs">Cutter
            <select className="w-full border rounded p-2" value={form.cut}
              onChange={e => update('cut', e.target.value)}>
              <option value="partial">Partial</option><option value="full">Full</option>
              <option value="legacy">Legacy</option><option value="none">None</option>
            </select>
          </label>
        </div>
        <Button disabled={busy || !config} onClick={add}><Plus size={16} className="mr-1" /> Add printer</Button>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button disabled={busy || !config?.devices?.some(d => d.enabled)} variant="outline"
          onClick={testAll} data-testid="fleet-test-all"><TestTube size={15} className="mr-1" />
          Test all connected printers simultaneously</Button>
        <Button disabled={busy} variant="outline" onClick={refresh}><RefreshCw size={15} className="mr-1"/> Refresh</Button>
      </div>
      <p className="text-xs text-gray-600">{MESSAGE}</p>
      {results.map(r => <p className="text-xs" key={r.id}>{r.name}: {r.status}{r.error ? ` — ${r.error}` : ''}</p>)}
      {deliveryStatus.filter(d => d.status === 'uncertain').slice(0,10).map(d => <div key={d.id} className="border border-amber-300 rounded p-2 text-xs flex items-center gap-2">
        <span className="flex-1">{d.station}: delivery uncertain — check paper before retrying</span>
        <Button size="sm" variant="outline" onClick={async () => {
          if (!window.confirm('Confirm that you checked the printer and want to send this ticket again. A duplicate ticket may result.')) return;
          try { await printerFleetAPI.retry(d.id); toast.success('Delivery requeued'); refresh(); }
          catch (err) { toast.error(err.response?.data?.detail || 'Could not requeue'); }
        }}>Review & retry</Button>
      </div>)}
    </CardContent>
  </Card>;
}
