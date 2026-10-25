import React, { useEffect, useState } from 'react';
import { Printer, RefreshCw, Save, TestTube2 } from 'lucide-react';
import { Button } from '../ui/button';
import { Input } from '../ui/input';
import { Card, CardContent, CardHeader, CardTitle } from '../ui/card';
import { coursingAPI } from '../../services/api';
import { toast } from 'sonner';

// These are backend ESC/POS station targets, not the legacy hardware inventory.
// A hosted backend cannot discover printers on a merchant's private LAN.
const STATIONS = ['Kitchen Printer', 'Bar Printer', 'Pizza Printer', 'Receipt Printer'];
const EMPTY = { printer: STATIONS[0], host: '', port: '9100', enabled: true,
  width: '48', codepage: 'cp437', cut: 'partial', footerInPerson: true,
  footerOnline: true, paddingLines: '3' };
const numericPort = value => {
  const number = Number(value);
  return Number.isInteger(number) && number >= 1 && number <= 65535;
};
const nonUrlHost = value => /^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,252}$/.test(value) &&
  !/^[a-z]+:\/\//i.test(value) && !/[\/\\@?#]/.test(value);

export default function StationPrinterConnections() {
  const [targets, setTargets] = useState([]);
  const [profiles, setProfiles] = useState([]);
  const [windowsPrinters, setWindowsPrinters] = useState(null);
  const [selectedWindowsPrinter, setSelectedWindowsPrinter] = useState('');
  const [draft, setDraft] = useState(EMPTY);
  const [busy, setBusy] = useState('');
  const [health, setHealth] = useState(null);
  const [error, setError] = useState('');

  const refresh = async () => {
    setBusy('refresh');
    try {
      const [targetsResult, profilesResult] = await Promise.all([
        coursingAPI.getPrintTargets(), coursingAPI.printProfiles(),
      ]);
      setTargets(Array.isArray(targetsResult.data) ? targetsResult.data : []);
      setProfiles(profilesResult.data?.profiles || []);
      setError('');
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not load station printer configuration');
    } finally { setBusy(''); }
  };

  useEffect(() => {
    refresh();
    if (typeof window.nuaDesktop?.listPrinters === 'function') {
      window.nuaDesktop.listPrinters()
        .then(result => setWindowsPrinters(Array.isArray(result) ? result : []))
        .catch(() => setWindowsPrinters([]));
    }
  }, []);

  const edit = (name) => {
    const saved = targets.find(p => p.printer === name);
    setDraft(saved ? { ...EMPTY, ...saved, port: String(saved.port ?? 9100),
      width: String(saved.width ?? 48), paddingLines: String(saved.paddingLines ?? 3) }
      : { ...EMPTY, printer: name });
  };

  const save = async () => {
    if (!draft.printer.trim() || draft.printer.length > 100) {
      toast.error('Enter a station printer name (maximum 100 characters)'); return;
    }
    if (draft.host.trim() && !nonUrlHost(draft.host.trim())) {
      toast.error('Enter only an IP address or hostname, not a URL'); return;
    }
    if (!numericPort(draft.port)) { toast.error('TCP port must be between 1 and 65535'); return; }
    if (!Number.isInteger(Number(draft.width)) || Number(draft.width) < 24 || Number(draft.width) > 96) {
      toast.error('Ticket width must be 24–96 characters'); return;
    }
    setBusy('save');
    try {
      await coursingAPI.setPrintTarget(draft.printer.trim(), {
        host: draft.host.trim(), port: Number(draft.port), enabled: draft.enabled,
        width: Number(draft.width), codepage: draft.codepage, cut: draft.cut,
        footerInPerson: draft.footerInPerson, footerOnline: draft.footerOnline,
        paddingLines: Math.max(0, Math.min(9, Number(draft.paddingLines) || 0)),
      });
      toast.success('Station connection saved. Printing is not verified until a test succeeds.');
      await refresh();
    } catch (err) { toast.error(err.response?.data?.detail || 'Could not save printer connection'); }
    finally { setBusy(''); }
  };

  const check = async () => {
    setBusy('check');
    try {
      const response = await coursingAPI.printHealth();
      setHealth(response.data);
      toast('Reachability is measured from the NUA backend, not this tablet or Windows PC.');
    } catch (err) { toast.error(err.response?.data?.detail || 'Printer check failed'); }
    finally { setBusy(''); }
  };

  const test = async () => {
    if (!draft.host.trim() || !targets.some(p => p.printer === draft.printer && p.host === draft.host.trim())) {
      toast.error('Save a printer with a network address before sending a test page'); return;
    }
    setBusy('test');
    try {
      const result = (await coursingAPI.printSelfTest(draft.printer)).data;
      if (result?.sent) toast.success('Backend submitted a test page. Verify the printer physically printed it.');
      else toast.error(result?.error || 'Printer test failed');
    } catch (err) { toast.error(err.response?.data?.detail || 'Printer test failed'); }
    finally { setBusy(''); }
  };

  const windowsTest = async () => {
    if (!selectedWindowsPrinter) { toast.error('Select an installed Windows printer'); return; }
    setBusy('windows-test');
    try {
      const result = await window.nuaDesktop.printReceipt({
        businessName: 'NUA POS — printer test', receiptId: 'TEST — NOT A SALE',
        items: [{ name: 'Windows spooler verification', quantity: 1, totalCents: 0 }],
        totalCents: 0, footer: 'Check paper width and physical output.',
      }, selectedWindowsPrinter);
      if (result?.status === 'submitted') toast('Submitted to the Windows spooler. Confirm output on paper.');
      else toast.error('Windows print dialog cancelled or could not submit.');
    } catch (e) { toast.error(e.message || 'Windows printer unavailable'); }
    finally { setBusy(''); }
  };

  const field = (name, label, placeholder = '', type = 'text') => (
    <label className="block text-xs font-medium space-y-1">
      <span>{label}</span>
      <Input type={type} min={type === 'number' ? 0 : undefined} value={draft[name] ?? ''}
        placeholder={placeholder} onChange={e => setDraft(d => ({ ...d, [name]: e.target.value }))}
        data-testid={`station-${name}`} />
    </label>
  );

  return (
    <Card data-testid="station-printer-connections">
      <CardHeader><CardTitle className="text-base flex items-center gap-2"><Printer size={18} /> Station printer connections</CardTitle></CardHeader>
      <CardContent className="space-y-4">
        <p className="text-xs text-gray-600">
          Set real ESC/POS network destinations for kitchen, bar and receipt stations. The TCP connection
          is made by the backend (usually port 9100), not from this device. Printers on a private venue
          Wi-Fi/LAN may require an authenticated local print bridge; entering a local IP alone does not create connectivity.
        </p>
        {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <label className="block text-xs font-medium space-y-1">
            <span>Station / routing name</span>
            <Input list="nua-printer-stations" value={draft.printer} maxLength={100}
              onChange={e => edit(e.target.value)} data-testid="station-printer-name" />
            <datalist id="nua-printer-stations">{[...new Set([...STATIONS, ...targets.map(p => p.printer)])].map(s => <option key={s} value={s} />)}</datalist>
          </label>
          <label className="block text-xs font-medium space-y-1">
            <span>Printer profile</span>
            <select className="w-full border rounded-md p-2" defaultValue="" onChange={e => {
              const p = profiles.find(item => item.id === e.target.value);
              if (p) setDraft(d => ({ ...d, width: String(p.width), codepage: p.codepage, cut: p.cut }));
            }} data-testid="station-printer-profile">
              <option value="">Custom settings</option>
              {profiles.map(p => <option key={p.id} value={p.id}>{p.label}</option>)}
            </select>
          </label>
          {field('host', 'Host / IP address', '192.168.1.50')}
          {field('port', 'TCP port', '9100', 'number')}
          {field('width', 'Ticket width (characters)', '48', 'number')}
          <label className="block text-xs font-medium space-y-1">
            <span>Character encoding</span>
            <select value={draft.codepage} className="w-full border rounded-md p-2"
              onChange={e => setDraft(d => ({ ...d, codepage: e.target.value }))}>
              <option value="cp437">CP437 (US)</option>
              <option value="cp850">CP850 (Western European)</option>
            </select>
          </label>
          <label className="block text-xs font-medium space-y-1">
            <span>Paper cutter</span>
            <select value={draft.cut} className="w-full border rounded-md p-2"
              onChange={e => setDraft(d => ({ ...d, cut: e.target.value }))}>
              <option value="partial">Partial cut</option><option value="full">Full cut</option>
              <option value="legacy">Legacy ESC i</option><option value="none">No cut</option>
            </select>
          </label>
          {field('paddingLines', 'Blank lines before cut', '3', 'number')}
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={draft.enabled} onChange={e => setDraft(d => ({ ...d, enabled: e.target.checked }))} />
          Enable this network print target
        </label>
        <div className="flex flex-wrap gap-2">
          <Button onClick={save} disabled={!!busy} data-testid="save-station-printer"><Save size={15} className="mr-1" /> Save connection</Button>
          <Button variant="outline" onClick={check} disabled={!!busy}><RefreshCw size={15} className="mr-1" /> Check ports</Button>
          <Button variant="outline" onClick={test} disabled={!!busy}><TestTube2 size={15} className="mr-1" /> Print network test</Button>
        </div>
        {health?.printers?.length > 0 && (
          <div className="text-xs space-y-1" aria-live="polite">
            {health.printers.map(p => <p key={p.printer}>{p.printer}: {p.host ? `${p.host}:${p.port}` : 'not configured'}
              {' — '}{p.reachable === true ? 'TCP reachable from backend (paper not verified)' :
                p.reachable === false ? 'unreachable from backend' : 'not tested / disabled'}</p>)}
          </div>
        )}
        {windowsPrinters !== null && (
          <div className="border-t pt-3 space-y-2" data-testid="windows-spooler-printers">
            <p className="text-sm font-semibold">Windows locally installed printers</p>
            <p className="text-xs text-gray-600">These come from the Windows spooler, not the backend TCP port.
              The print test opens an OS dialog; it does not prove a receipt reached paper.</p>
            <div className="flex flex-wrap gap-2">
              <select aria-label="Windows printer" className="border rounded-md p-2 text-sm"
                value={selectedWindowsPrinter} onChange={e => setSelectedWindowsPrinter(e.target.value)}>
                <option value="">Choose an installed printer</option>
                {windowsPrinters.map(p => <option key={p.name} value={p.name}>{p.displayName || p.name}{p.isDefault ? ' (default)' : ''}</option>)}
              </select>
              <Button variant="outline" onClick={windowsTest} disabled={!selectedWindowsPrinter || !!busy}>Windows print test</Button>
            </div>
            {!windowsPrinters.length && <p className="text-xs text-amber-700">No printer detected by Windows. Install its Windows driver first.</p>}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
