import React, { useState, useEffect, useCallback } from 'react';
import { eftposAPI } from '../services/api';
import { toast } from 'sonner';
import { Card, CardContent } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Badge } from '../components/ui/badge';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '../components/ui/dialog';
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from '../components/ui/select';
import { CreditCard, PlusCircle, Pencil, Trash2, Wifi, History } from 'lucide-react';
import SensitiveActionReauthDialog from '../components/security/SensitiveActionReauthDialog';

const PROVIDERS = ['tyro', 'linkly', 'smartpay', 'windcave', 'westpac', 'anz', 'nab', 'cba', 'square'];
const CONNECTION_TYPES = ['tcp', 'serial', 'cloud', 'usb'];
const STATUS_BADGE = { active: 'default', inactive: 'outline', error: 'destructive' };

const EMPTY_FORM = {
  provider: 'tyro', terminalId: '', merchantId: '', name: '', location: 'Main',
  connectionType: 'tcp', ipAddress: '', port: 0, serialPort: '', apiKey: '',
  apiSecret: '', cloudEndpoint: '', timeout: 60, autoSettlement: true,
};

export default function EFTPOSTerminals() {
  const [terminals, setTerminals] = useState([]);
  const [show, setShow] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [testing, setTesting] = useState(null);
  const [historyFor, setHistoryFor] = useState(null);
  const [history, setHistory] = useState(null);
  const [testHistory, setTestHistory] = useState(null);
  const [loadingHistory, setLoadingHistory] = useState(false);
  // Directive Phase 5 — removing a live payment terminal's configuration
  // is a sensitive, irreversible settings change.
  const [pendingRemove, setPendingRemove] = useState(null); // terminal | null

  const load = useCallback(async () => {
    try { setTerminals((await eftposAPI.listTerminals()).data); }
    catch { toast.error('Could not load EFTPOS terminals'); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const closeDialog = () => { setShow(false); setEditingId(null); setForm(EMPTY_FORM); };

  const openEdit = (t) => {
    setEditingId(t.id);
    setForm({ ...EMPTY_FORM, ...t, ipAddress: t.ipAddress || '', serialPort: t.serialPort || '',
      apiKey: t.apiKey || '', apiSecret: t.apiSecret || '', cloudEndpoint: t.cloudEndpoint || '' });
    setShow(true);
  };

  const save = async () => {
    if (!form.name || !form.terminalId || !form.merchantId) {
      return toast.error('Name, terminal ID and merchant ID are required');
    }
    const payload = { ...form, port: parseInt(form.port, 10) || 0, timeout: parseInt(form.timeout, 10) || 60 };
    try {
      if (editingId) await eftposAPI.updateTerminal(editingId, payload);
      else await eftposAPI.createTerminal(payload);
      toast.success(editingId ? 'Terminal updated' : 'Terminal added');
      closeDialog();
      load();
    } catch (e) { toast.error(e.response?.data?.detail || 'Failed to save terminal'); }
  };

  const remove = (t) => {
    if (!window.confirm(`Remove terminal "${t.name}"? This cannot be undone.`)) return;
    setPendingRemove(t);
  };

  const doRemove = async () => {
    const t = pendingRemove;
    setPendingRemove(null);
    if (!t) return;
    try { await eftposAPI.deleteTerminal(t.id); toast.success('Terminal removed'); load(); }
    catch (e) { toast.error(e.response?.data?.detail || 'Failed to remove terminal'); }
  };

  const viewHistory = async (t) => {
    setHistoryFor(t);
    setHistory(null);
    setTestHistory(null);
    setLoadingHistory(true);
    try {
      const [txns, tests] = await Promise.all([
        eftposAPI.listTransactions(t.id),
        eftposAPI.testHistory(t.id),
      ]);
      setHistory(txns.data);
      setTestHistory(tests.data);
    } catch { toast.error('Could not load transaction history'); }
    finally { setLoadingHistory(false); }
  };

  const testConnection = async (t) => {
    setTesting(t.id);
    try {
      const r = await eftposAPI.testTerminal(t.id);
      if (r.data.success) toast.success(r.data.message || 'Connection successful');
      else toast.error(r.data.message || 'Connection failed');
      load();
    } catch (e) { toast.error(e.response?.data?.detail || 'Test failed'); }
    finally { setTesting(null); }
  };

  return (
    <div className="space-y-4" data-testid="eftpos-terminals-page">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2"><CreditCard size={22} /> EFTPOS Terminals</h1>
          <p className="text-sm text-slate-500">Card terminal configs — provider, connection details and credentials for taking card payments.</p>
        </div>
        <Button size="sm" onClick={() => { setForm(EMPTY_FORM); setShow(true); }} data-testid="terminal-new-btn">
          <PlusCircle size={14} className="mr-1" /> Add Terminal
        </Button>
      </div>

      <Card><CardContent className="p-0">
        <table className="w-full text-sm">
          <thead className="bg-slate-50"><tr>
            <th className="p-2 pl-4 text-left text-xs text-slate-500">Name</th>
            <th className="p-2 text-left text-xs text-slate-500">Provider</th>
            <th className="p-2 text-left text-xs text-slate-500">Location</th>
            <th className="p-2 text-left text-xs text-slate-500">Connection</th>
            <th className="p-2 text-center text-xs text-slate-500">Status</th>
            <th className="p-2 pr-4"></th>
          </tr></thead>
          <tbody>
            {terminals.map(t => (
              <tr key={t.id} className="border-t hover:bg-slate-50" data-testid={`terminal-row-${t.id.slice(0, 6)}`}>
                <td className="p-2 pl-4 font-medium">{t.name}</td>
                <td className="p-2 capitalize">{t.provider}</td>
                <td className="p-2">{t.location}</td>
                <td className="p-2 text-xs font-mono uppercase">{t.connectionType}{t.ipAddress ? ` · ${t.ipAddress}:${t.port}` : ''}</td>
                <td className="p-2 text-center"><Badge variant={STATUS_BADGE[t.status] || 'outline'} className="capitalize">{t.status}</Badge></td>
                <td className="p-2 pr-4 text-right space-x-1">
                  <Button size="sm" variant="outline" disabled={testing === t.id} onClick={() => testConnection(t)}
                    data-testid={`terminal-test-${t.id.slice(0, 6)}`}>
                    <Wifi size={12} className="mr-1" /> {testing === t.id ? 'Testing...' : 'Test'}
                  </Button>
                  <Button size="icon" variant="ghost" onClick={() => viewHistory(t)} data-testid={`terminal-history-${t.id.slice(0, 6)}`} title="Recent transactions">
                    <History size={14} />
                  </Button>
                  <Button size="icon" variant="ghost" onClick={() => openEdit(t)} data-testid={`terminal-edit-${t.id.slice(0, 6)}`}>
                    <Pencil size={14} />
                  </Button>
                  <Button size="icon" variant="ghost" onClick={() => remove(t)} data-testid={`terminal-delete-${t.id.slice(0, 6)}`}>
                    <Trash2 size={14} className="text-rose-600" />
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {terminals.length === 0 && <p className="text-center text-slate-400 py-8">No EFTPOS terminals configured yet.</p>}
      </CardContent></Card>

      <Dialog open={show} onOpenChange={o => { if (!o) closeDialog(); else setShow(true); }}>
        <DialogContent className="max-w-lg" data-testid="terminal-dialog">
          <DialogHeader><DialogTitle>{editingId ? 'Edit Terminal' : 'Add EFTPOS Terminal'}</DialogTitle></DialogHeader>
          <div className="space-y-3 max-h-[70vh] overflow-y-auto pr-1">
            <Input placeholder="Display name (e.g. Front Counter)" value={form.name}
              onChange={e => setForm({ ...form, name: e.target.value })} data-testid="terminal-name" />
            <div className="grid grid-cols-2 gap-3">
              <Select value={form.provider} onValueChange={v => setForm({ ...form, provider: v })}>
                <SelectTrigger data-testid="terminal-provider"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {PROVIDERS.map(p => <SelectItem key={p} value={p} className="capitalize">{p}</SelectItem>)}
                </SelectContent>
              </Select>
              <Input placeholder="Location" value={form.location} onChange={e => setForm({ ...form, location: e.target.value })} />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <Input placeholder="Terminal ID" value={form.terminalId} onChange={e => setForm({ ...form, terminalId: e.target.value })} data-testid="terminal-terminal-id" />
              <Input placeholder="Merchant ID" value={form.merchantId} onChange={e => setForm({ ...form, merchantId: e.target.value })} data-testid="terminal-merchant-id" />
            </div>
            <Select value={form.connectionType} onValueChange={v => setForm({ ...form, connectionType: v })}>
              <SelectTrigger data-testid="terminal-connection-type"><SelectValue /></SelectTrigger>
              <SelectContent>
                {CONNECTION_TYPES.map(c => <SelectItem key={c} value={c} className="uppercase">{c}</SelectItem>)}
              </SelectContent>
            </Select>
            {form.connectionType === 'tcp' && (
              <div className="grid grid-cols-2 gap-3">
                <Input placeholder="IP address" value={form.ipAddress} onChange={e => setForm({ ...form, ipAddress: e.target.value })} />
                <Input type="number" placeholder="Port" value={form.port} onChange={e => setForm({ ...form, port: e.target.value })} />
              </div>
            )}
            {form.connectionType === 'serial' && (
              <Input placeholder="Serial port (e.g. /dev/ttyUSB0)" value={form.serialPort} onChange={e => setForm({ ...form, serialPort: e.target.value })} />
            )}
            {form.connectionType === 'cloud' && (
              <Input placeholder="Cloud endpoint URL" value={form.cloudEndpoint} onChange={e => setForm({ ...form, cloudEndpoint: e.target.value })} />
            )}
            <div className="grid grid-cols-2 gap-3">
              <Input type="password" placeholder="API key (optional)" value={form.apiKey} onChange={e => setForm({ ...form, apiKey: e.target.value })} />
              <Input type="password" placeholder="API secret (optional)" value={form.apiSecret} onChange={e => setForm({ ...form, apiSecret: e.target.value })} />
            </div>
            <Input type="number" placeholder="Timeout (seconds)" value={form.timeout} onChange={e => setForm({ ...form, timeout: e.target.value })} />
            <label className="flex items-center gap-2 text-sm text-slate-600 cursor-pointer">
              <input type="checkbox" checked={form.autoSettlement} onChange={e => setForm({ ...form, autoSettlement: e.target.checked })} />
              Auto-settlement at end of day
            </label>
            <Button className="w-full" onClick={save} data-testid="terminal-save-btn">
              {editingId ? 'Save Changes' : 'Add Terminal'}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={!!historyFor} onOpenChange={o => { if (!o) { setHistoryFor(null); setHistory(null); } }}>
        <DialogContent className="max-w-lg max-h-[80vh] overflow-y-auto" data-testid="terminal-history-dialog">
          <DialogHeader><DialogTitle>{historyFor?.name} — recent transactions</DialogTitle></DialogHeader>
          <div className="space-y-1">
            {loadingHistory && <p className="text-sm text-slate-400 text-center py-6">Loading…</p>}
            {history?.length === 0 && <p className="text-sm text-slate-400 text-center py-6">No transactions on this terminal yet.</p>}
            {history?.map(tx => (
              <div key={tx.id} className="flex justify-between items-center text-sm py-1.5 border-b last:border-0" data-testid={`terminal-history-row-${tx.id.slice(0, 6)}`}>
                <div>
                  <p className="font-medium capitalize">{tx.transactionType} {tx.cardType ? `· ${tx.cardType}` : ''} {tx.maskedPan ? `•••• ${tx.maskedPan}` : ''}</p>
                  <p className="text-xs text-slate-500">{new Date(tx.timestamp).toLocaleString()}</p>
                </div>
                <div className="text-right">
                  <p className="font-medium">${tx.amount.toFixed(2)}</p>
                  <Badge variant={tx.approved ? 'default' : 'destructive'} className="text-[10px]">
                    {tx.approved ? 'Approved' : 'Declined'}
                  </Badge>
                </div>
              </div>
            ))}
          </div>

          {testHistory?.length > 0 && (
            <div className="pt-3 mt-3 border-t">
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1.5">Connection test history</p>
              <div className="space-y-1">
                {testHistory.map(t => (
                  <div key={t.id} className="flex justify-between items-center text-xs py-1" data-testid={`terminal-test-history-row-${t.id.slice(0, 6)}`}>
                    <span className="text-slate-500">{new Date(t.testedAt).toLocaleString()}</span>
                    <Badge variant={t.success ? 'default' : 'destructive'} className="text-[10px]">{t.message}</Badge>
                  </div>
                ))}
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
      <SensitiveActionReauthDialog
        open={!!pendingRemove}
        label={`remove terminal "${pendingRemove?.name || ''}"`}
        onVerified={doRemove}
        onCancel={() => setPendingRemove(null)}
      />
    </div>
  );
}
