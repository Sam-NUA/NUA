import React, { useEffect, useMemo, useState } from 'react';
import { Card, CardContent } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Badge } from '../components/ui/badge';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '../components/ui/dialog';
import { temperatureAPI } from '../services/api';
import { useTheme } from '../contexts/ThemeContext';
import { useToast } from '../hooks/use-toast';
import {
  Thermometer, Snowflake, Plus, RefreshCcw, Bell, Bluetooth, Wifi, Wrench, Trash2,
  AlertTriangle, CheckCircle2, Calendar, FileDown, Copy, Zap,
} from 'lucide-react';
import { DialogService, FileService } from '../platform';

/**
 * Temperature Monitoring — HACCP compliant, hardware-agnostic.
 * Owners register each fridge/freezer + its Bluetooth/WiFi sensor; readings
 * flow in via webhook OR manual entry. Twice-daily nudges catch outages.
 */
const CONN_ICON = { bluetooth: Bluetooth, wifi: Wifi, wifi_gateway: Wifi, cellular: Wifi, manual: Wrench };

export default function Temperature() {
  const { theme } = useTheme();
  const { toast } = useToast();

  const [brands, setBrands] = useState([]);
  const [devices, setDevices] = useState([]);
  const [readings, setReadings] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [busy, setBusy] = useState(false);

  const [addOpen, setAddOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(initialForm());

  const [logOpen, setLogOpen] = useState(false);
  const [logForm, setLogForm] = useState({ deviceId: '', temperatureC: '', humidity: '', note: '' });

  const [reportPeriod, setReportPeriod] = useState('weekly');
  const [customStart, setCustomStart] = useState('');
  const [customEnd, setCustomEnd] = useState('');
  const [reportData, setReportData] = useState(null);
  const [secretDialog, setSecretDialog] = useState(null); // {device, ingestSecret}

  const load = async () => {
    setBusy(true);
    try {
      const [b, d, r, a] = await Promise.all([
        temperatureAPI.brands(),
        temperatureAPI.listDevices(),
        temperatureAPI.listReadings({ limit: 200 }),
        temperatureAPI.listAlerts({ unacknowledgedOnly: false }),
      ]);
      setBrands(b.data.brands || []);
      setDevices(d.data || []);
      setReadings(r.data || []);
      setAlerts(a.data || []);
    } catch (e) {
      toast({ title: 'Load failed', description: e?.response?.data?.detail, variant: 'destructive' });
    } finally { setBusy(false); }
  };
  useEffect(() => { load(); }, []);

  const brandsByKey = useMemo(() => Object.fromEntries(brands.map(b => [b.key, b])), [brands]);

  // KPIs
  const kpis = useMemo(() => ({
    devices: devices.filter(d => d.active).length,
    fridges: devices.filter(d => d.unitType === 'fridge').length,
    freezers: devices.filter(d => d.unitType === 'freezer').length,
    unackAlerts: alerts.filter(a => !a.acknowledged).length,
  }), [devices, alerts]);

  const latestByDevice = useMemo(() => {
    const m = {};
    for (const r of readings) if (!m[r.deviceId]) m[r.deviceId] = r;
    return m;
  }, [readings]);

  const openAdd = () => { setEditing(null); setForm(initialForm()); setAddOpen(true); };
  const openEdit = (dev) => {
    setEditing(dev);
    setForm({ ...initialForm(), ...dev, minC: String(dev.minC), maxC: String(dev.maxC) });
    setAddOpen(true);
  };

  const saveDevice = async () => {
    if (!form.name.trim()) return toast({ title: 'Name is required', variant: 'destructive' });
    const payload = {
      name: form.name.trim(),
      unitType: form.unitType,
      brand: form.brand,
      model: form.model || undefined,
      connectivity: form.connectivity,
      deviceId: form.deviceId || undefined,
      location: form.location || undefined,
      minC: form.minC === '' ? null : parseFloat(form.minC),
      maxC: form.maxC === '' ? null : parseFloat(form.maxC),
      active: !!form.active,
    };
    setBusy(true);
    try {
      if (editing) {
        await temperatureAPI.updateDevice(editing.id, payload);
        toast({ title: 'Device updated' });
      } else {
        const r = await temperatureAPI.createDevice(payload);
        toast({ title: 'Device added' });
        // Show one-time ingest secret so owner can paste it into device / webhook
        if (r.data?.ingestSecret) setSecretDialog({ device: r.data, ingestSecret: r.data.ingestSecret });
      }
      setAddOpen(false);
      load();
    } catch (e) {
      toast({ title: 'Save failed', description: e?.response?.data?.detail, variant: 'destructive' });
    } finally { setBusy(false); }
  };

  const deleteDevice = async (dev) => {
    if (!await DialogService.confirm(`Remove ${dev.name}? Historical readings stay for audit.`)) return;
    setBusy(true);
    try {
      await temperatureAPI.deleteDevice(dev.id);
      toast({ title: 'Device removed' });
      load();
    } catch (e) {
      toast({ title: 'Failed', description: e?.response?.data?.detail, variant: 'destructive' });
    } finally { setBusy(false); }
  };

  const rotateSecret = async (dev) => {
    if (!await DialogService.confirm(`Rotate ingest secret for ${dev.name}? The old secret stops working immediately.`)) return;
    setBusy(true);
    try {
      const r = await temperatureAPI.rotateSecret(dev.id);
      setSecretDialog({ device: dev, ingestSecret: r.data.ingestSecret });
    } catch (e) {
      toast({ title: 'Failed', description: e?.response?.data?.detail, variant: 'destructive' });
    } finally { setBusy(false); }
  };

  const openLog = (dev = null) => {
    setLogForm({ deviceId: dev?.id || (devices[0]?.id ?? ''), temperatureC: '', humidity: '', note: '' });
    setLogOpen(true);
  };

  const submitLog = async () => {
    if (!logForm.deviceId) return toast({ title: 'Pick a device', variant: 'destructive' });
    const temp = parseFloat(logForm.temperatureC);
    if (Number.isNaN(temp)) return toast({ title: 'Enter a temperature', variant: 'destructive' });
    setBusy(true);
    try {
      const r = await temperatureAPI.logReading({
        deviceId: logForm.deviceId,
        temperatureC: temp,
        humidity: logForm.humidity ? parseFloat(logForm.humidity) : undefined,
        note: logForm.note || undefined,
        source: 'manual',
      });
      toast({
        title: r.data.status === 'normal' ? 'Reading logged ✓' : `⚠ ${r.data.status.replace('_', ' ')}`,
        variant: r.data.status === 'normal' ? 'default' : 'destructive',
      });
      setLogOpen(false);
      load();
    } catch (e) {
      toast({ title: 'Failed', description: e?.response?.data?.detail, variant: 'destructive' });
    } finally { setBusy(false); }
  };

  const ackAlert = async (a) => {
    setBusy(true);
    try {
      await temperatureAPI.ackAlert(a.id);
      load();
    } finally { setBusy(false); }
  };

  const runReport = async () => {
    setBusy(true);
    try {
      const params = reportPeriod === 'custom'
        ? { start: customStart, end: customEnd }
        : { period: reportPeriod };
      const r = await temperatureAPI.report(params);
      setReportData(r.data);
      toast({ title: `Report generated · ${r.data.totalReadings} readings` });
    } catch (e) {
      toast({ title: 'Report failed', description: e?.response?.data?.detail, variant: 'destructive' });
    } finally { setBusy(false); }
  };

  const exportCSV = async () => {
    if (!reportData) return;
    const rows = [
      ['Device', 'Type', 'Temperature (°C)', 'Humidity (%)', 'Status', 'Recorded at', 'Source', 'Note'],
      ...reportData.readings.map(r => [
        r.deviceName, r.unitType, r.temperatureC, r.humidity ?? '',
        r.status, r.recordedAt, r.source, (r.note || '').replace(/,/g, ';'),
      ]),
    ];
    const csv = rows.map(r => r.map(v => `"${String(v ?? '').replace(/"/g, '""')}"`).join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    await FileService.downloadFile(blob, `temperature-report-${reportData.range.start}_to_${reportData.range.end}.csv`);
  };

  const runScan = async () => {
    setBusy(true);
    try {
      const r = await temperatureAPI.scanMissing();
      toast({ title: `${r.data.remindersCreated} missing-reading reminders queued` });
      load();
    } finally { setBusy(false); }
  };

  return (
    <div className="space-y-6" data-testid="temperature-page">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-2" style={{ color: theme.text }}>
            <Thermometer className="text-blue-500" /> Temperature Monitoring
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            Register your fridges &amp; freezers, pair Bluetooth/WiFi sensors, and get alerted when temperatures drift.
          </p>
        </div>
        <div className="flex gap-2 flex-wrap">
          <Button variant="outline" size="sm" onClick={load} disabled={busy} data-testid="refresh-temperature">
            <RefreshCcw size={13} className={`mr-1 ${busy ? 'animate-spin' : ''}`} /> Refresh
          </Button>
          <Button variant="outline" size="sm" onClick={runScan} disabled={busy} data-testid="scan-missing">
            <Zap size={13} className="mr-1" /> Scan missing (12h)
          </Button>
          <Button variant="outline" size="sm" onClick={() => openLog()} data-testid="log-reading">
            <Thermometer size={13} className="mr-1" /> Log reading
          </Button>
          <Button onClick={openAdd} style={{ background: theme.primary }} className="text-white" data-testid="add-device">
            <Plus size={13} className="mr-1" /> Add device
          </Button>
        </div>
      </div>

      {/* KPI strip */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3" data-testid="temperature-kpis">
        <Kpi label="Active devices" value={kpis.devices} icon={Thermometer} tone="bg-blue-50 border-blue-200 text-blue-800" testid="kpi-devices" />
        <Kpi label="Fridges" value={kpis.fridges} icon={Thermometer} tone="bg-emerald-50 border-emerald-200 text-emerald-800" testid="kpi-fridges" />
        <Kpi label="Freezers" value={kpis.freezers} icon={Snowflake} tone="bg-cyan-50 border-cyan-200 text-cyan-800" testid="kpi-freezers" />
        <Kpi label="Unack alerts" value={kpis.unackAlerts} icon={Bell} tone="bg-rose-50 border-rose-200 text-rose-800" testid="kpi-alerts" />
      </div>

      {/* Devices grid */}
      <section data-testid="devices-section">
        <h2 className="text-sm font-semibold uppercase tracking-widest text-gray-500 mb-2">Devices</h2>
        {devices.length === 0 ? (
          <Card><CardContent className="py-8 text-center text-gray-400">
            No devices yet — click <strong>Add device</strong> to register your first fridge or freezer.
          </CardContent></Card>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {devices.map(d => {
              const latest = latestByDevice[d.id];
              const Icon = d.unitType === 'freezer' ? Snowflake : Thermometer;
              const status = latest?.status || 'no_data';
              const statusTone = status === 'normal' ? 'bg-emerald-100 text-emerald-700'
                : status === 'no_data' ? 'bg-gray-100 text-gray-500'
                : 'bg-rose-100 text-rose-700';
              const ConnIcon = CONN_ICON[d.connectivity] || Wifi;
              return (
                <Card key={d.id} data-testid={`device-${d.id}`}>
                  <CardContent className="p-4">
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <Icon size={22} className="text-blue-500" />
                        <div>
                          <div className="font-semibold">{d.name}</div>
                          <div className="text-[10px] text-gray-500 uppercase tracking-widest">{d.unitType.replace('_', ' ')} · {d.location || '—'}</div>
                        </div>
                      </div>
                      <div className="flex gap-1">
                        <button onClick={() => openLog(d)} className="p-1 rounded hover:bg-gray-100" title="Log manual reading" data-testid={`log-${d.id}`}>
                          <Thermometer size={13} />
                        </button>
                        <button onClick={() => openEdit(d)} className="p-1 rounded hover:bg-gray-100" title="Edit" data-testid={`edit-device-${d.id}`}>
                          <Wrench size={13} />
                        </button>
                        <button onClick={() => rotateSecret(d)} className="p-1 rounded hover:bg-gray-100" title="Rotate ingest secret">
                          <RefreshCcw size={13} />
                        </button>
                        <button onClick={() => deleteDevice(d)} className="p-1 rounded hover:bg-red-100 text-red-600" title="Remove device" data-testid={`delete-device-${d.id}`}>
                          <Trash2 size={13} />
                        </button>
                      </div>
                    </div>
                    <div className="mt-3 flex items-center gap-2 flex-wrap">
                      <Badge className={statusTone}>
                        {status === 'no_data' ? 'No reading yet' : (latest ? `${latest.temperatureC}°C` : status)}
                      </Badge>
                      <span className="text-[10px] text-gray-500 flex items-center gap-0.5"><ConnIcon size={10} /> {d.connectivity.replace('_', ' ')}</span>
                      <span className="text-[10px] text-gray-500">{(brandsByKey[d.brand]?.label) || d.brand}{d.model ? ` · ${d.model}` : ''}</span>
                      {!d.active && <Badge className="bg-gray-200 text-gray-600 text-[10px]">disabled</Badge>}
                    </div>
                    <div className="mt-2 text-[10px] text-gray-500">
                      Normal range: <strong>{d.minC}°C → {d.maxC}°C</strong>
                      {latest && <span className="ml-2">· last recorded {new Date(latest.recordedAt).toLocaleString()}</span>}
                    </div>
                  </CardContent>
                </Card>
              );
            })}
          </div>
        )}
      </section>

      {/* Alerts */}
      <section data-testid="alerts-section">
        <h2 className="text-sm font-semibold uppercase tracking-widest text-gray-500 mb-2">Alerts</h2>
        <Card>
          <CardContent className="p-0">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-xs uppercase text-gray-500">
                <tr>
                  <th className="text-left px-4 py-2">Device</th>
                  <th className="text-left px-4 py-2">Type</th>
                  <th className="text-right px-4 py-2">Reading</th>
                  <th className="text-center px-4 py-2">Status</th>
                  <th className="text-left px-4 py-2">Recorded at</th>
                  <th className="text-right px-4 py-2">Actions</th>
                </tr>
              </thead>
              <tbody>
                {alerts.length === 0 ? (
                  <tr><td colSpan={6} className="text-center py-6 text-gray-400" data-testid="no-alerts">
                    <CheckCircle2 size={24} className="mx-auto mb-1 opacity-30" /> No alerts. Everything&apos;s in range.
                  </td></tr>
                ) : alerts.map(a => (
                  <tr key={a.id} className={`border-t ${a.acknowledged ? 'opacity-60' : ''}`} data-testid={`alert-${a.id}`}>
                    <td className="px-4 py-2">{a.deviceName}</td>
                    <td className="px-4 py-2 text-xs capitalize">{(a.unitType || '').replace('_', ' ')}</td>
                    <td className="px-4 py-2 text-right font-mono">{a.temperatureC != null ? `${a.temperatureC}°C` : '—'}</td>
                    <td className="px-4 py-2 text-center">
                      <Badge className={
                        a.status === 'abnormal_high' ? 'bg-rose-100 text-rose-700' :
                        a.status === 'abnormal_low' ? 'bg-blue-100 text-blue-700' :
                        'bg-amber-100 text-amber-700'
                      }>
                        <AlertTriangle size={10} className="inline mr-0.5" /> {a.status.replace('_', ' ')}
                      </Badge>
                    </td>
                    <td className="px-4 py-2 text-xs text-gray-500">{a.recordedAt ? new Date(a.recordedAt).toLocaleString() : '—'}</td>
                    <td className="px-4 py-2 text-right">
                      {!a.acknowledged && (
                        <Button size="sm" variant="outline" onClick={() => ackAlert(a)} data-testid={`ack-alert-${a.id}`}>
                          <CheckCircle2 size={11} className="mr-1" /> Acknowledge
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
      </section>

      {/* Reports */}
      <section data-testid="reports-section">
        <h2 className="text-sm font-semibold uppercase tracking-widest text-gray-500 mb-2">Reports · Weekly / Monthly / Yearly / Custom</h2>
        <Card><CardContent className="p-4 space-y-3">
          <div className="flex items-center gap-2 flex-wrap">
            {['weekly', 'monthly', 'yearly', 'custom'].map(p => (
              <button key={p}
                onClick={() => setReportPeriod(p)}
                data-testid={`period-${p}`}
                className={`px-3 py-1 text-xs rounded-full font-medium ${reportPeriod === p ? 'text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'}`}
                style={reportPeriod === p ? { background: theme.primary } : {}}>
                {p.charAt(0).toUpperCase() + p.slice(1)}
              </button>
            ))}
            {reportPeriod === 'custom' && (
              <div className="flex items-center gap-2 ml-2" data-testid="custom-range-inputs">
                <Input type="date" value={customStart} onChange={e => setCustomStart(e.target.value)} className="w-40" data-testid="custom-start" />
                <span className="text-gray-400">→</span>
                <Input type="date" value={customEnd} onChange={e => setCustomEnd(e.target.value)} className="w-40" data-testid="custom-end" />
              </div>
            )}
            <div className="ml-auto flex gap-2">
              <Button size="sm" onClick={runReport} disabled={busy || (reportPeriod === 'custom' && (!customStart || !customEnd))} data-testid="run-report">
                <Calendar size={13} className="mr-1" /> Generate
              </Button>
              {reportData && (
                <Button size="sm" variant="outline" onClick={exportCSV} data-testid="export-csv">
                  <FileDown size={13} className="mr-1" /> Export CSV
                </Button>
              )}
            </div>
          </div>

          {reportData && (
            <div className="space-y-3" data-testid="report-summary">
              <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs">
                <SummaryTile label="Range" value={`${reportData.range.start} → ${reportData.range.end}`} />
                <SummaryTile label="Readings" value={reportData.totalReadings} />
                <SummaryTile label="Devices covered" value={reportData.devicesCovered} />
                <SummaryTile label="Abnormal" value={reportData.totalAbnormal} tone={reportData.totalAbnormal ? 'text-rose-600' : 'text-emerald-600'} />
              </div>
              <table className="w-full text-xs">
                <thead className="bg-gray-50 text-gray-500">
                  <tr>
                    <th className="text-left px-3 py-2">Device</th>
                    <th className="text-right px-3 py-2">Readings</th>
                    <th className="text-right px-3 py-2">Min °C</th>
                    <th className="text-right px-3 py-2">Max °C</th>
                    <th className="text-right px-3 py-2">Avg °C</th>
                    <th className="text-right px-3 py-2">Abnormal</th>
                  </tr>
                </thead>
                <tbody>
                  {reportData.devices.map(d => (
                    <tr key={d.deviceId} className="border-t">
                      <td className="px-3 py-1.5"><strong>{d.deviceName}</strong> <span className="text-gray-400">· {d.unitType}</span></td>
                      <td className="px-3 py-1.5 text-right">{d.readingsCount}</td>
                      <td className="px-3 py-1.5 text-right font-mono">{d.minObservedC ?? '—'}</td>
                      <td className="px-3 py-1.5 text-right font-mono">{d.maxObservedC ?? '—'}</td>
                      <td className="px-3 py-1.5 text-right font-mono">{d.avgObservedC ?? '—'}</td>
                      <td className={`px-3 py-1.5 text-right font-mono ${d.abnormalCount ? 'text-rose-600' : ''}`}>{d.abnormalCount}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent></Card>
      </section>

      {/* Add / edit device dialog */}
      <Dialog open={addOpen} onOpenChange={setAddOpen}>
        <DialogContent className="max-w-md max-h-[90vh] overflow-y-auto" data-testid="device-dialog">
          <DialogHeader>
            <DialogTitle>{editing ? 'Edit device' : 'Register a new fridge / freezer'}</DialogTitle>
            <DialogDescription className="text-xs text-gray-500">
              Pick your unit type, choose the sensor brand you&apos;re using, and set the safe temperature range.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3 py-2">
            <Field label="Name *"><Input value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} placeholder="e.g. Kitchen Fridge #1" data-testid="dev-name" /></Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Unit type">
                <select value={form.unitType} onChange={e => setForm({ ...form, unitType: e.target.value })} className="w-full p-2 border rounded text-sm" data-testid="dev-type">
                  <option value="fridge">Fridge</option>
                  <option value="freezer">Freezer</option>
                  <option value="cool_room">Cool room</option>
                  <option value="display">Display case</option>
                  <option value="warmer">Hot-hold / warmer</option>
                </select>
              </Field>
              <Field label="Sensor brand">
                <select value={form.brand} onChange={e => setForm({ ...form, brand: e.target.value })} className="w-full p-2 border rounded text-sm" data-testid="dev-brand">
                  {brands.map(b => <option key={b.key} value={b.key}>{b.label}</option>)}
                </select>
              </Field>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Model (optional)"><Input value={form.model} onChange={e => setForm({ ...form, model: e.target.value })} placeholder={brandsByKey[form.brand]?.productLine?.[0] || ''} data-testid="dev-model" /></Field>
              <Field label="Connectivity">
                <select value={form.connectivity} onChange={e => setForm({ ...form, connectivity: e.target.value })} className="w-full p-2 border rounded text-sm" data-testid="dev-connectivity">
                  {(brandsByKey[form.brand]?.connectivity || ['wifi', 'bluetooth', 'manual']).map(c => (
                    <option key={c} value={c}>{c.replace('_', ' ')}</option>
                  ))}
                  <option value="manual">manual (no sensor)</option>
                </select>
              </Field>
            </div>
            <Field label="Vendor device ID (optional)"><Input value={form.deviceId} onChange={e => setForm({ ...form, deviceId: e.target.value })} placeholder="MAC / serial from the sensor" data-testid="dev-vendor-id" /></Field>
            <Field label="Location"><Input value={form.location} onChange={e => setForm({ ...form, location: e.target.value })} placeholder="Prep kitchen, Bar…" data-testid="dev-location" /></Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Min °C"><Input type="number" step="0.1" value={form.minC} onChange={e => setForm({ ...form, minC: e.target.value })} data-testid="dev-min" /></Field>
              <Field label="Max °C"><Input type="number" step="0.1" value={form.maxC} onChange={e => setForm({ ...form, maxC: e.target.value })} data-testid="dev-max" /></Field>
            </div>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.active} onChange={e => setForm({ ...form, active: e.target.checked })} /> Active</label>
            {brandsByKey[form.brand]?.docsUrl && (
              <div className="text-[10px] text-gray-500">
                📘 <a href={brandsByKey[form.brand].docsUrl} target="_blank" rel="noreferrer" className="text-blue-600 underline">{brandsByKey[form.brand].label} API docs</a>
              </div>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setAddOpen(false)}>Cancel</Button>
            <Button onClick={saveDevice} disabled={busy} style={{ background: theme.primary }} className="text-white" data-testid="save-device">
              {busy ? 'Saving…' : (editing ? 'Save changes' : 'Register device')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Manual log dialog */}
      <Dialog open={logOpen} onOpenChange={setLogOpen}>
        <DialogContent className="max-w-sm" data-testid="log-dialog">
          <DialogHeader>
            <DialogTitle>Log a manual temperature reading</DialogTitle>
            <DialogDescription className="text-xs text-gray-500">Fallback for when a sensor&apos;s battery is dead or offline.</DialogDescription>
          </DialogHeader>
          <div className="space-y-3 py-2">
            <Field label="Device">
              <select value={logForm.deviceId} onChange={e => setLogForm({ ...logForm, deviceId: e.target.value })} className="w-full p-2 border rounded text-sm" data-testid="log-device">
                <option value="">— Pick a device —</option>
                {devices.filter(d => d.active).map(d => (
                  <option key={d.id} value={d.id}>{d.name} ({d.unitType})</option>
                ))}
              </select>
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Temperature (°C)"><Input type="number" step="0.1" value={logForm.temperatureC} onChange={e => setLogForm({ ...logForm, temperatureC: e.target.value })} data-testid="log-temp" /></Field>
              <Field label="Humidity (%)"><Input type="number" step="0.1" value={logForm.humidity} onChange={e => setLogForm({ ...logForm, humidity: e.target.value })} placeholder="optional" data-testid="log-humidity" /></Field>
            </div>
            <Field label="Note (optional)"><Input value={logForm.note} onChange={e => setLogForm({ ...logForm, note: e.target.value })} placeholder="e.g. Battery replaced today" data-testid="log-note" /></Field>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setLogOpen(false)}>Cancel</Button>
            <Button onClick={submitLog} disabled={busy} style={{ background: theme.primary }} className="text-white" data-testid="submit-log">
              Log reading
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* One-time ingest secret dialog */}
      <Dialog open={!!secretDialog} onOpenChange={(o) => { if (!o) setSecretDialog(null); }}>
        <DialogContent className="max-w-md" data-testid="secret-dialog">
          <DialogHeader>
            <DialogTitle>Ingest secret · {secretDialog?.device?.name}</DialogTitle>
            <DialogDescription className="text-xs text-gray-500">
              Copy this NOW. It&apos;s shown once — rotate it later if lost.
              Paste it into the device (or your webhook script) as the <code>ingestSecret</code> field.
            </DialogDescription>
          </DialogHeader>
          {secretDialog && (
            <div className="space-y-3 py-2">
              <div className="bg-gray-100 rounded p-3 font-mono text-xs break-all" data-testid="secret-value">{secretDialog.ingestSecret}</div>
              <div className="text-xs text-gray-600">
                <div className="font-semibold mb-1">Example webhook POST:</div>
                <pre className="bg-slate-900 text-slate-100 rounded p-2 overflow-x-auto text-[10px]">{`POST /api/temperature/ingest
{
  "deviceId": "${secretDialog.device.id}",
  "ingestSecret": "${secretDialog.ingestSecret}",
  "temperatureC": 3.2,
  "humidity": 45.0
}`}</pre>
              </div>
              <Button onClick={() => { navigator.clipboard.writeText(secretDialog.ingestSecret); toast({ title: 'Copied!' }); }} data-testid="copy-secret" className="w-full">
                <Copy size={13} className="mr-1" /> Copy secret
              </Button>
            </div>
          )}
          <DialogFooter>
            <Button onClick={() => setSecretDialog(null)}>Done</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function initialForm() {
  return { name: '', unitType: 'fridge', brand: 'manual', model: '', connectivity: 'manual', deviceId: '', location: '', minC: '', maxC: '', active: true };
}

const Kpi = ({ label, value, icon: Icon, tone, testid }) => (
  <div className={`rounded-xl border px-3 py-2 ${tone}`} data-testid={testid}>
    <div className="flex items-center justify-between">
      <span className="text-[10px] uppercase tracking-widest font-semibold opacity-80">{label}</span>
      {Icon && <Icon size={13} className="opacity-70" />}
    </div>
    <div className="text-xl font-bold mt-0.5">{value}</div>
  </div>
);

const Field = ({ label, children }) => (
  <div>
    <label className="text-[10px] uppercase tracking-widest text-gray-500 block mb-1 font-semibold">{label}</label>
    {children}
  </div>
);

const SummaryTile = ({ label, value, tone = '' }) => (
  <div className="rounded border bg-white px-2 py-1">
    <div className="text-[9px] uppercase tracking-widest text-gray-500">{label}</div>
    <div className={`text-sm font-semibold ${tone}`}>{value}</div>
  </div>
);
