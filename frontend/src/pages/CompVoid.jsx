import React, { useState, useEffect } from 'react';
import { Plus, Ban, Gift, Search } from 'lucide-react';
import { Card, CardContent } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Badge } from '../components/ui/badge';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '../components/ui/dialog';
import { useTheme } from '../contexts/ThemeContext';
import { itemsSystemAPI } from '../services/api';
import { toast } from 'sonner';
import SensitiveActionReauthDialog from '../components/security/SensitiveActionReauthDialog';

// Used both as its own route (/comp-void — full page header) and embedded
// as the "Comp / Void History" tab inside Discounts.jsx, which used to
// reimplement a second, smaller copy of this same table (no search, no
// filter, no stats) plus its own record dialog. One implementation now;
// `embedded` just drops the page header, since the host page supplies one.
export default function CompVoid({ embedded = false }) {
  const { theme } = useTheme();
  const [records, setRecords] = useState([]);
  const [showDialog, setShowDialog] = useState(false);
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState('all');
  const [form, setForm] = useState({ type: 'comp', reason: '', amount: '', transactionId: '', printVoid: false });
  // Directive Phase 5 — a void (writing off a transaction) is a sensitive
  // action, same as a refund; a comp isn't named by the directive but
  // shares this form/handler, so it goes through the same gate rather
  // than forking the save path by type.
  const [showReauth, setShowReauth] = useState(false);

  useEffect(() => { fetchData(); }, []);
  const fetchData = async () => { try { const r = await itemsSystemAPI.getCompVoids(); setRecords(r.data); } catch {} };

  const handleSave = () => {
    if (!form.reason) { toast.error('Reason required'); return; }
    if (!form.amount || parseFloat(form.amount) <= 0) { toast.error('Amount must be greater than 0'); return; }
    setShowReauth(true);
  };

  const doSave = async () => {
    setShowReauth(false);
    try {
      await itemsSystemAPI.createCompVoid({ ...form, amount: parseFloat(form.amount) });
      toast.success(`${form.type === 'comp' ? 'Comp' : 'Void'} recorded`);
      setShowDialog(false);
      setForm({ type: 'comp', reason: '', amount: '', transactionId: '', printVoid: false });
      fetchData();
    } catch { toast.error('Failed'); }
  };

  const filtered = records.filter(r => {
    if (filter !== 'all' && r.type !== filter) return false;
    if (search && !(r.reason?.toLowerCase().includes(search.toLowerCase()) || r.transactionId?.toLowerCase().includes(search.toLowerCase()))) return false;
    return true;
  });

  const totalComp = records.filter(r => r.type === 'comp').reduce((s, r) => s + (r.amount || 0), 0);
  const totalVoid = records.filter(r => r.type === 'void').reduce((s, r) => s + (r.amount || 0), 0);

  return (
    <div className={embedded ? "space-y-4" : "space-y-6"} data-testid="comp-void-page">
      <div className="flex items-center justify-between">
        {embedded
          ? <div />
          : <div><h1 className="text-2xl font-bold" style={{ color: theme.text }}>Comp / Void</h1><p className="text-sm text-gray-500">Track complimentary items and voided transactions with reasons</p></div>}
        <Button style={{ backgroundColor: theme.primary }} onClick={() => setShowDialog(true)} data-testid="add-cv-btn"><Plus size={16} className="mr-1" /> Record Comp / Void</Button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card><CardContent className="p-5"><div className="flex items-center justify-between"><div><p className="text-xs text-gray-500 uppercase">Total Comps</p><p className="text-2xl font-bold mt-1" style={{ color: theme.primary }}>${totalComp.toFixed(2)}</p></div><Gift size={28} className="opacity-30" /></div></CardContent></Card>
        <Card><CardContent className="p-5"><div className="flex items-center justify-between"><div><p className="text-xs text-gray-500 uppercase">Total Voids</p><p className="text-2xl font-bold text-red-600 mt-1">${totalVoid.toFixed(2)}</p></div><Ban size={28} className="opacity-30" /></div></CardContent></Card>
        <Card><CardContent className="p-5"><div><p className="text-xs text-gray-500 uppercase">Total Records</p><p className="text-2xl font-bold mt-1">{records.length}</p></div></CardContent></Card>
      </div>

      <Card>
        <CardContent className="p-0">
          <div className="p-4 flex items-center gap-2 border-b">
            <div className="relative flex-1"><Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" /><Input className="pl-8" placeholder="Search reason or transaction..." value={search} onChange={e => setSearch(e.target.value)} data-testid="cv-search" /></div>
            <select className="p-2 border rounded-md text-sm" value={filter} onChange={e => setFilter(e.target.value)} data-testid="cv-filter">
              <option value="all">All Types</option>
              <option value="comp">Comp Only</option>
              <option value="void">Void Only</option>
            </select>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm" data-testid="cv-table">
              <thead className="bg-gray-50">
                <tr>
                  <th className="text-left p-3">Type</th>
                  <th className="text-left p-3">Reason</th>
                  <th className="text-left p-3">Transaction</th>
                  <th className="text-right p-3">Amount</th>
                  <th className="text-center p-3">Printed</th>
                  <th className="text-left p-3">Date</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map(cv => (
                  <tr key={cv.id} className="border-t hover:bg-gray-50" data-testid={`cv-${cv.id}`}>
                    <td className="p-3"><Badge className={cv.type === 'comp' ? 'bg-blue-100 text-blue-700' : 'bg-red-100 text-red-700'}>{cv.type === 'comp' ? 'COMP' : 'VOID'}</Badge></td>
                    <td className="p-3">{cv.reason}</td>
                    <td className="p-3 text-xs font-mono text-gray-500">{cv.transactionId || '-'}</td>
                    <td className="p-3 text-right font-mono font-bold">${(cv.amount || 0).toFixed(2)}</td>
                    <td className="p-3 text-center">{cv.printVoid ? <Badge variant="outline" className="text-xs">Yes</Badge> : <span className="text-gray-300">-</span>}</td>
                    <td className="p-3 text-xs text-gray-500">{new Date(cv.processedAt).toLocaleString()}</td>
                  </tr>
                ))}
                {filtered.length === 0 && <tr><td colSpan="6" className="p-12 text-center text-gray-400">No comp/void records yet</td></tr>}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      <Dialog open={showDialog} onOpenChange={setShowDialog}>
        <DialogContent className="max-w-sm" data-testid="cv-dialog">
          <DialogHeader><DialogTitle>Record Comp or Void</DialogTitle></DialogHeader>
          <div className="space-y-3 py-2">
            <div className="grid grid-cols-2 gap-2">
              <button onClick={() => setForm({ ...form, type: 'comp' })} className={`p-3 rounded-lg border-2 text-sm font-medium transition-all ${form.type === 'comp' ? 'border-blue-500 bg-blue-50 text-blue-700' : 'border-gray-200 text-gray-600'}`} data-testid="cv-type-comp"><Gift size={16} className="mx-auto mb-1" />Comp</button>
              <button onClick={() => setForm({ ...form, type: 'void' })} className={`p-3 rounded-lg border-2 text-sm font-medium transition-all ${form.type === 'void' ? 'border-red-500 bg-red-50 text-red-700' : 'border-gray-200 text-gray-600'}`} data-testid="cv-type-void"><Ban size={16} className="mx-auto mb-1" />Void</button>
            </div>
            <Input placeholder="Reason (e.g. Wrong order, Customer complaint)" value={form.reason} onChange={e => setForm({ ...form, reason: e.target.value })} data-testid="cv-reason-input" />
            <Input placeholder="Transaction ID (optional)" value={form.transactionId} onChange={e => setForm({ ...form, transactionId: e.target.value })} data-testid="cv-txn-input" />
            <Input type="number" step="0.01" placeholder="Amount ($)" value={form.amount} onChange={e => setForm({ ...form, amount: e.target.value })} data-testid="cv-amount-input" />
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.printVoid} onChange={e => setForm({ ...form, printVoid: e.target.checked })} data-testid="cv-print-input" /> Print void ticket to kitchen</label>
            <Button className="w-full" style={{ backgroundColor: theme.primary }} onClick={handleSave} data-testid="cv-save-btn">Record {form.type === 'comp' ? 'Comp' : 'Void'}</Button>
          </div>
        </DialogContent>
      </Dialog>
      <SensitiveActionReauthDialog
        open={showReauth}
        label={`record this ${form.type === 'comp' ? 'comp' : 'void'}`}
        onVerified={doSave}
        onCancel={() => setShowReauth(false)}
      />
    </div>
  );
}
