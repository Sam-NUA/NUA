import React, { useState, useEffect, useCallback } from 'react';
import { financeAPI } from '../../services/api';
import { toast } from 'sonner';
import { Card, CardContent } from '../../components/ui/card';
import { Button } from '../../components/ui/button';
import { Input } from '../../components/ui/input';
import { Badge } from '../../components/ui/badge';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '../../components/ui/dialog';
import { PlusCircle } from 'lucide-react';
import { DialogService } from '../../platform';
import { FMT, today } from './helpers';

const STATUS_BADGE = { held: 'outline', applied: 'default', refunded: 'secondary' };

const Deposits = () => {
  const [deposits, setDeposits] = useState([]);
  const [show, setShow] = useState(false);
  const [form, setForm] = useState({
    customerId: '', customerName: '', bookingId: '', amount: 0,
    receivedAt: today(), method: 'card',
  });
  const [applyFor, setApplyFor] = useState(null);
  const [applyTxnId, setApplyTxnId] = useState('');

  const load = useCallback(async () => {
    try { setDeposits((await financeAPI.listDeposits()).data); }
    catch { toast.error('Could not load deposits'); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const save = async () => {
    if (!form.customerId || !form.amount) return toast.error('Customer ID + amount required');
    try {
      await financeAPI.createDeposit({ ...form, amount: parseFloat(form.amount) });
      toast.success('Deposit recorded'); setShow(false);
      setForm({ customerId: '', customerName: '', bookingId: '', amount: 0, receivedAt: today(), method: 'card' });
      load();
    } catch (e) { toast.error(e.response?.data?.detail || 'Failed'); }
  };

  const apply = async () => {
    if (!applyTxnId.trim()) return toast.error('Transaction ID required');
    try {
      await financeAPI.applyDeposit(applyFor.id, { transactionId: applyTxnId.trim() });
      toast.success('Deposit applied to sale'); setApplyFor(null); setApplyTxnId(''); load();
    } catch (e) { toast.error(e.response?.data?.detail || 'Failed'); }
  };

  const refund = async (d) => {
    if (!await DialogService.confirm(`Refund ${FMT(d.amount)} held for ${d.customerName || d.customerId}? This cannot be undone.`)) return;
    try {
      await financeAPI.refundDeposit(d.id);
      toast.success('Deposit refunded'); load();
    } catch (e) { toast.error(e.response?.data?.detail || 'Failed'); }
  };

  // Held deposits are a real liability — the business owes that $ back
  // (as a refund or a credit toward the eventual sale) the moment it's
  // taken, same accounting posture as gratuity being tracked separately
  // from revenue. Computed client-side from the already-loaded list
  // rather than a new endpoint, since the page already has everything.
  const heldTotal = deposits.filter(d => d.status === 'held').reduce((s, d) => s + d.amount, 0);
  const appliedTotal = deposits.filter(d => d.status === 'applied').reduce((s, d) => s + d.amount, 0);
  const refundedTotal = deposits.filter(d => d.status === 'refunded').reduce((s, d) => s + d.amount, 0);
  const heldCount = deposits.filter(d => d.status === 'held').length;

  return (
    <div className="space-y-4" data-testid="deposits-page">
      <div className="flex justify-between items-center">
        <div>
          <h3 className="text-lg font-semibold">Customer Deposits</h3>
          <p className="text-xs text-slate-500">Held against a future booking or event, applied to the sale once it happens.</p>
        </div>
        <Button size="sm" onClick={() => setShow(true)} data-testid="deposit-new-btn"><PlusCircle size={14} className="mr-1" /> Record Deposit</Button>
      </div>

      {deposits.length > 0 && (
        <div className="grid grid-cols-3 gap-3">
          <Card><CardContent className="p-3 text-center">
            <p className="text-lg font-bold" data-testid="deposits-held-total">{FMT(heldTotal)}</p>
            <p className="text-[11px] text-slate-500 uppercase tracking-wide">Currently held ({heldCount})</p>
          </CardContent></Card>
          <Card><CardContent className="p-3 text-center">
            <p className="text-lg font-bold text-emerald-600">{FMT(appliedTotal)}</p>
            <p className="text-[11px] text-slate-500 uppercase tracking-wide">Applied to sales</p>
          </CardContent></Card>
          <Card><CardContent className="p-3 text-center">
            <p className="text-lg font-bold text-slate-500">{FMT(refundedTotal)}</p>
            <p className="text-[11px] text-slate-500 uppercase tracking-wide">Refunded</p>
          </CardContent></Card>
        </div>
      )}

      <Card><CardContent className="p-0">
        <table className="w-full text-sm">
          <thead className="bg-slate-50"><tr>
            <th className="p-2 pl-4 text-left text-xs text-slate-500">Customer</th>
            <th className="p-2 text-left text-xs text-slate-500">Booking / Event</th>
            <th className="p-2 text-left text-xs text-slate-500">Received</th>
            <th className="p-2 text-left text-xs text-slate-500">Method</th>
            <th className="p-2 text-right text-xs text-slate-500">Amount</th>
            <th className="p-2 text-center text-xs text-slate-500">Status</th>
            <th className="p-2 pr-4"></th>
          </tr></thead>
          <tbody>
            {deposits.map(d => (
              <tr key={d.id} className="border-t hover:bg-slate-50" data-testid={`deposit-row-${d.id.slice(0, 6)}`}>
                <td className="p-2 pl-4">{d.customerName || d.customerId}</td>
                <td className="p-2 text-xs font-mono">{d.bookingId || d.eventId || '—'}</td>
                <td className="p-2">{d.receivedAt}</td>
                <td className="p-2 capitalize">{d.method}</td>
                <td className="p-2 text-right font-medium">{FMT(d.amount)}</td>
                <td className="p-2 text-center"><Badge variant={STATUS_BADGE[d.status] || 'outline'} className="capitalize">{d.status}</Badge></td>
                <td className="p-2 pr-4 text-right space-x-2">
                  {d.status === 'held' && (
                    <>
                      <Button size="sm" onClick={() => setApplyFor(d)} data-testid={`deposit-apply-${d.id.slice(0, 6)}`}>Apply to Sale</Button>
                      <Button size="sm" variant="outline" onClick={() => refund(d)} data-testid={`deposit-refund-${d.id.slice(0, 6)}`}>Refund</Button>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {deposits.length === 0 && <p className="text-center text-slate-400 py-8">No deposits recorded yet</p>}
      </CardContent></Card>

      <Dialog open={show} onOpenChange={setShow}>
        <DialogContent data-testid="deposit-new-dialog">
          <DialogHeader><DialogTitle>Record a Customer Deposit</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <Input placeholder="Customer ID" value={form.customerId} onChange={e => setForm({ ...form, customerId: e.target.value })} data-testid="deposit-customer-id" />
            <Input placeholder="Customer name" value={form.customerName} onChange={e => setForm({ ...form, customerName: e.target.value })} data-testid="deposit-customer-name" />
            <Input placeholder="Booking / event ID (optional)" value={form.bookingId} onChange={e => setForm({ ...form, bookingId: e.target.value })} />
            <div className="grid grid-cols-2 gap-3">
              <Input type="number" placeholder="Amount" value={form.amount} onChange={e => setForm({ ...form, amount: e.target.value })} data-testid="deposit-amount" />
              <Input type="date" value={form.receivedAt} onChange={e => setForm({ ...form, receivedAt: e.target.value })} />
            </div>
            <Button className="w-full" onClick={save} data-testid="deposit-save-btn">Record Deposit</Button>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={!!applyFor} onOpenChange={o => { if (!o) { setApplyFor(null); setApplyTxnId(''); } }}>
        <DialogContent data-testid="deposit-apply-dialog">
          <DialogHeader><DialogTitle>Apply Deposit · {applyFor?.customerName}</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <p className="text-sm text-slate-500">Applying {FMT(applyFor?.amount)} against the transaction ID for the completed sale.</p>
            <Input placeholder="Transaction ID" value={applyTxnId} onChange={e => setApplyTxnId(e.target.value)} data-testid="deposit-apply-txn-id" />
            <Button className="w-full" onClick={apply} data-testid="deposit-apply-submit">Apply Deposit</Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default Deposits;
