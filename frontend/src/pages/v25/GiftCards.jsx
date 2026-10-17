import React, { useEffect, useMemo, useState } from 'react';
import { Card, CardContent } from '../../components/ui/card';
import { Button } from '../../components/ui/button';
import { Badge } from '../../components/ui/badge';
import { Input } from '../../components/ui/input';
import { Textarea } from '../../components/ui/textarea';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '../../components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../../components/ui/select';
import { v26API, customersAPI } from '../../services/api';
import Barcode128 from '../../components/Barcode128';
import { useTheme } from '../../contexts/ThemeContext';
import { useAuth } from '../../contexts/AuthContext';
import { useToast } from '../../hooks/use-toast';
import { Gift, Search, Plus, Ban, RotateCcw, Send, PlusCircle, Pencil, Save, History } from 'lucide-react';
import { DialogService } from '../../platform';

const STATUS_STYLE = {
  active: 'bg-emerald-100 text-emerald-700',
  pending_activation: 'bg-amber-100 text-amber-700',
  depleted: 'bg-gray-200 text-gray-600',
  stopped: 'bg-red-100 text-red-700',
};

const emptySale = {
  amount: 50, bonus: 0, recipientName: '', recipientEmail: '',
  purchaserName: '', purchaserEmail: '', customerId: '',
  channel: 'counter', paymentMethod: 'card', occasion: 'general', message: '',
};

export default function GiftCards() {
  const { theme } = useTheme();
  const { user } = useAuth();
  const { toast } = useToast();
  const canManage = user?.role === 'owner' || user?.role === 'manager';

  const [cards, setCards] = useState([]);
  const [customers, setCustomers] = useState([]);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');

  const [sellOpen, setSellOpen] = useState(false);
  const [sellForm, setSellForm] = useState(emptySale);
  const [justIssued, setJustIssued] = useState(null);

  const [detail, setDetail] = useState(null);
  const [txns, setTxns] = useState([]);
  const [editing, setEditing] = useState(false);
  const [editForm, setEditForm] = useState(null);
  const [reloadAmount, setReloadAmount] = useState('');
  const [resendEmail, setResendEmail] = useState('');

  const load = () => v26API.listGiftCards().then(r => setCards(r.data || [])).catch(() => {});
  useEffect(() => { load(); customersAPI.getAll().then(r => setCustomers(r.data || [])).catch(() => {}); }, []);

  const filtered = useMemo(() => {
    let rows = cards;
    if (statusFilter !== 'all') rows = rows.filter(c => c.status === statusFilter);
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      rows = rows.filter(c =>
        (c.code || '').toLowerCase().includes(q) ||
        (c.recipientName || '').toLowerCase().includes(q) ||
        (c.recipientEmail || '').toLowerCase().includes(q) ||
        (c.purchaserName || '').toLowerCase().includes(q));
    }
    return rows;
  }, [cards, statusFilter, search]);

  const balanceOf = (c) => c.currentBalance ?? c.amount ?? 0;

  const sell = async () => {
    try {
      const r = await v26API.sellGift(sellForm);
      setJustIssued(r.data);
      toast({ title: 'Gift card issued', description: `${r.data.code} — $${balanceOf(r.data).toFixed(2)}` });
      load();
    } catch (e) {
      toast({ title: 'Failed to issue card', description: e?.response?.data?.detail, variant: 'destructive' });
    }
  };

  const openDetail = async (card) => {
    setDetail(card); setEditing(false); setReloadAmount(''); setResendEmail('');
    try { const r = await v26API.giftTransactions(card.code); setTxns(r.data || []); }
    catch { setTxns([]); }
  };

  const refreshDetail = async (code) => {
    const fresh = cards.find(c => c.code === code);
    const [listRes, txnsRes] = await Promise.allSettled([
      v26API.listGiftCards(),
      v26API.giftTransactions(code),
    ]);
    if (listRes.status === 'fulfilled') {
      setCards(listRes.value.data || []);
      const updated = (listRes.value.data || []).find(c => c.code === code) || fresh;
      setDetail(updated);
    }
    if (txnsRes.status === 'fulfilled') setTxns(txnsRes.value.data || []);
  };

  const startEdit = () => {
    setEditForm({
      recipientName: detail.recipientName || '', recipientEmail: detail.recipientEmail || '',
      purchaserName: detail.purchaserName || '', purchaserEmail: detail.purchaserEmail || '',
      occasion: detail.occasion || '', message: detail.message || '',
    });
    setEditing(true);
  };

  const saveEdit = async () => {
    try {
      await v26API.editGiftCard(detail.code, editForm);
      toast({ title: 'Card updated' });
      setEditing(false);
      await refreshDetail(detail.code);
    } catch (e) {
      toast({ title: 'Failed to save', description: e?.response?.data?.detail, variant: 'destructive' });
    }
  };

  const doReload = async () => {
    const amount = parseFloat(reloadAmount);
    if (!amount || amount <= 0) { toast({ title: 'Enter an amount', variant: 'destructive' }); return; }
    try {
      const r = await v26API.reloadGiftCard(detail.code, amount);
      toast({ title: 'Credit added', description: `New balance: $${r.data.newBalance.toFixed(2)}` });
      setReloadAmount('');
      await refreshDetail(detail.code);
    } catch (e) {
      toast({ title: 'Failed to reload', description: e?.response?.data?.detail, variant: 'destructive' });
    }
  };

  const doStop = async () => {
    if (!await DialogService.confirm(`Stop card ${detail.code}? This blocks it from being redeemed until reactivated.`)) return;
    try {
      await v26API.stopGiftCard(detail.code);
      toast({ title: 'Card stopped' });
      await refreshDetail(detail.code);
    } catch (e) {
      toast({ title: 'Failed to stop card', description: e?.response?.data?.detail, variant: 'destructive' });
    }
  };

  const doReactivate = async () => {
    try {
      await v26API.reactivateGiftCard(detail.code);
      toast({ title: 'Card reactivated' });
      await refreshDetail(detail.code);
    } catch (e) {
      toast({ title: 'Failed to reactivate', description: e?.response?.data?.detail, variant: 'destructive' });
    }
  };

  const doResend = async () => {
    try {
      const r = await v26API.resendGiftCard(detail.code, resendEmail.trim() || undefined);
      if (r.data.sent) toast({ title: 'Email sent', description: `Resent to ${r.data.to}` });
      else toast({ title: 'Email not sent', description: r.data.reason === 'not_configured' ? 'Email delivery is not configured for this venue yet — ask your owner to add a SendGrid key in Settings.' : (r.data.reason || 'Delivery failed'), variant: 'destructive' });
    } catch (e) {
      toast({ title: 'Failed to resend', description: e?.response?.data?.detail, variant: 'destructive' });
    }
  };

  return (
    <div className="space-y-6" data-testid="gift-cards-page">
      <div className="flex justify-between items-center flex-wrap gap-3">
        <h1 className="text-2xl font-bold flex items-center gap-2" style={{ color: theme.text }}>
          <Gift className="text-rose-600" /> Gift Cards
        </h1>
        <Button onClick={() => { setSellForm(emptySale); setJustIssued(null); setSellOpen(true); }}
          style={{ background: theme.primary }} className="text-white" data-testid="sell-gift-btn">
          <Plus size={14} className="mr-1.5" /> Sell Gift Card
        </Button>
      </div>

      <div className="flex flex-wrap gap-2">
        <div className="relative flex-1 min-w-[220px]">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
          <Input value={search} onChange={e => setSearch(e.target.value)}
            placeholder="Search code, recipient, purchaser…" className="pl-9" data-testid="gift-search" />
        </div>
        <Select value={statusFilter} onValueChange={setStatusFilter}>
          <SelectTrigger className="w-44" data-testid="gift-status-filter"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All statuses</SelectItem>
            <SelectItem value="active">Active</SelectItem>
            <SelectItem value="pending_activation">Pending activation</SelectItem>
            <SelectItem value="depleted">Depleted</SelectItem>
            <SelectItem value="stopped">Stopped</SelectItem>
          </SelectContent>
        </Select>
      </div>

      <Card className="border-0 shadow-sm">
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-xs uppercase tracking-widest text-gray-500 bg-gray-50">
                <tr>
                  <th className="p-2 text-left">Code</th>
                  <th className="p-2 text-left">Recipient</th>
                  <th className="p-2 text-left">Occasion</th>
                  <th className="p-2 text-right">Balance</th>
                  <th className="p-2 text-left">Status</th>
                  <th className="p-2 text-left">Issued</th>
                </tr>
              </thead>
              <tbody data-testid="gift-rows">
                {filtered.map(c => (
                  <tr key={c.id} className="border-t hover:bg-gray-50 cursor-pointer" onClick={() => openDetail(c)} data-testid={`gift-row-${c.id}`}>
                    <td className="p-2 font-mono text-xs font-semibold">{c.code}</td>
                    <td className="p-2">
                      <p className="font-medium truncate max-w-[180px]">{c.recipientName || '—'}</p>
                      <p className="text-[11px] text-gray-400 truncate max-w-[180px]">{c.recipientEmail}</p>
                    </td>
                    <td className="p-2 text-xs text-gray-500 capitalize">{c.occasion || '—'}</td>
                    <td className="p-2 text-right font-mono">${(balanceOf(c) || 0).toFixed(2)}
                      {c.bonus > 0 && <span className="ml-1 text-[10px] text-emerald-600">+${c.bonus} bonus</span>}
                    </td>
                    <td className="p-2"><Badge className={`${STATUS_STYLE[c.status] || 'bg-gray-100 text-gray-600'} border-0`}>{(c.status || 'active').replace('_', ' ')}</Badge></td>
                    <td className="p-2 text-xs text-gray-500">{(c.createdAt || '').slice(0, 10)}</td>
                  </tr>
                ))}
                {filtered.length === 0 && (
                  <tr><td colSpan={6} className="p-8 text-center text-sm text-gray-400">No gift cards yet — sell your first one.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      {/* Sell dialog */}
      <Dialog open={sellOpen} onOpenChange={setSellOpen}>
        <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto" data-testid="gc-sale-form">
          <DialogHeader><DialogTitle>Sell Gift Card</DialogTitle></DialogHeader>
          {!justIssued ? (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 py-2">
              <div><label className="text-xs uppercase text-gray-500">Amount $</label>
                <Input type="number" value={sellForm.amount} onChange={e => setSellForm({ ...sellForm, amount: parseFloat(e.target.value) || 0 })} data-testid="gc-amount" /></div>
              <div><label className="text-xs uppercase text-gray-500">Bonus $</label>
                <Input type="number" value={sellForm.bonus} onChange={e => setSellForm({ ...sellForm, bonus: parseFloat(e.target.value) || 0 })} data-testid="gc-bonus" /></div>
              <div><label className="text-xs uppercase text-gray-500">Channel</label>
                <select className="w-full p-2 border rounded text-sm" value={sellForm.channel} onChange={e => setSellForm({ ...sellForm, channel: e.target.value })}>
                  <option value="counter">Counter</option><option value="online">Online</option>
                </select></div>
              <div><label className="text-xs uppercase text-gray-500">Payment</label>
                <select className="w-full p-2 border rounded text-sm" value={sellForm.paymentMethod} onChange={e => setSellForm({ ...sellForm, paymentMethod: e.target.value })}>
                  <option>card</option><option>cash</option><option>stripe</option><option>bank</option>
                </select></div>
              <div><label className="text-xs uppercase text-gray-500">Recipient Name</label>
                <Input value={sellForm.recipientName} onChange={e => setSellForm({ ...sellForm, recipientName: e.target.value })} data-testid="gc-recipient-name" /></div>
              <div><label className="text-xs uppercase text-gray-500">Recipient Email</label>
                <Input type="email" value={sellForm.recipientEmail} onChange={e => setSellForm({ ...sellForm, recipientEmail: e.target.value })} data-testid="gc-recipient-email" /></div>
              <div><label className="text-xs uppercase text-gray-500">Purchaser Name</label>
                <Input value={sellForm.purchaserName} onChange={e => setSellForm({ ...sellForm, purchaserName: e.target.value })} /></div>
              <div><label className="text-xs uppercase text-gray-500">Purchaser Email</label>
                <Input type="email" value={sellForm.purchaserEmail} onChange={e => setSellForm({ ...sellForm, purchaserEmail: e.target.value })} /></div>
              <div className="col-span-2"><label className="text-xs uppercase text-gray-500">Assign to existing customer (optional)</label>
                <select className="w-full p-2 border rounded text-sm" value={sellForm.customerId} onChange={e => setSellForm({ ...sellForm, customerId: e.target.value })} data-testid="gc-customer">
                  <option value="">— None —</option>
                  {customers.map(c => <option key={c.id} value={c.id}>{c.name} · {c.email || c.phone}</option>)}
                </select></div>
              <div><label className="text-xs uppercase text-gray-500">Occasion</label>
                <Input value={sellForm.occasion} onChange={e => setSellForm({ ...sellForm, occasion: e.target.value })} /></div>
              <div className="col-span-2"><label className="text-xs uppercase text-gray-500">Message</label>
                <Textarea rows={2} value={sellForm.message} onChange={e => setSellForm({ ...sellForm, message: e.target.value })} /></div>
            </div>
          ) : (
            <div className="text-center space-y-3 py-2" data-testid="gc-issued">
              <p className="font-bold text-lg">Card Issued</p>
              <p className="text-3xl font-bold">${balanceOf(justIssued).toFixed(2)}{justIssued.bonus > 0 && <span className="text-base text-emerald-600"> (+${justIssued.bonus} bonus)</span>}</p>
              <div className="flex justify-center"><Barcode128 value={justIssued.code} /></div>
              <p className="text-xs text-gray-500">Recipient: {justIssued.recipientName} · {justIssued.recipientEmail}</p>
              <Button variant="outline" onClick={() => window.print()}>Print</Button>
            </div>
          )}
          <DialogFooter>
            {!justIssued ? (
              <>
                <Button variant="outline" onClick={() => setSellOpen(false)}>Cancel</Button>
                <Button onClick={sell} style={{ background: theme.primary }} className="text-white" disabled={sellForm.amount <= 0} data-testid="gc-sell-btn">
                  <Gift size={14} className="mr-1.5" /> Issue Card
                </Button>
              </>
            ) : (
              <Button onClick={() => setSellOpen(false)} style={{ background: theme.primary }} className="text-white">Done</Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Detail / manage dialog */}
      <Dialog open={!!detail} onOpenChange={(o) => { if (!o) setDetail(null); }}>
        <DialogContent className="max-w-lg max-h-[85vh] overflow-y-auto" data-testid="gift-detail-dialog">
          <DialogHeader><DialogTitle className="flex items-center gap-2"><Gift size={16} /> {detail?.code}</DialogTitle></DialogHeader>
          {detail && (
            <div className="space-y-4">
              <div className="bg-gradient-to-br from-rose-500 to-pink-600 text-white rounded-2xl p-4 flex items-center gap-4">
                <div className="bg-white rounded-lg p-2"><Barcode128 value={detail.code} height={48} width={180} /></div>
                <div className="flex-1 min-w-0">
                  <p className="text-[10px] uppercase tracking-widest text-white/70">{detail.occasion || 'general'}</p>
                  <p className="font-bold text-xl">${balanceOf(detail).toFixed(2)}</p>
                  <Badge className={`${STATUS_STYLE[detail.status] || ''} border-0 mt-1`}>{(detail.status || 'active').replace('_', ' ')}</Badge>
                </div>
              </div>

              {!editing ? (
                <div className="grid grid-cols-2 gap-2 text-xs">
                  <div><span className="text-gray-500">Recipient:</span> <strong>{detail.recipientName || '—'}</strong></div>
                  <div><span className="text-gray-500">Recipient email:</span> {detail.recipientEmail || '—'}</div>
                  <div><span className="text-gray-500">Purchaser:</span> {detail.purchaserName || '—'}</div>
                  <div><span className="text-gray-500">Purchaser email:</span> {detail.purchaserEmail || '—'}</div>
                  <div className="col-span-2"><span className="text-gray-500">Message:</span> {detail.message || '—'}</div>
                  <div><span className="text-gray-500">Issued:</span> {(detail.createdAt || '').slice(0, 16)}</div>
                  {detail.status === 'stopped' && <div><span className="text-gray-500">Stopped:</span> {(detail.stoppedAt || '').slice(0, 16)}</div>}
                  {canManage && (
                    <div className="col-span-2">
                      <Button size="sm" variant="outline" onClick={startEdit} data-testid="gc-edit-btn"><Pencil size={12} className="mr-1" /> Edit details</Button>
                    </div>
                  )}
                </div>
              ) : (
                <div className="space-y-2">
                  <div className="grid grid-cols-2 gap-2">
                    <Input placeholder="Recipient name" value={editForm.recipientName} onChange={e => setEditForm({ ...editForm, recipientName: e.target.value })} data-testid="gc-edit-recipient-name" />
                    <Input placeholder="Recipient email" value={editForm.recipientEmail} onChange={e => setEditForm({ ...editForm, recipientEmail: e.target.value })} data-testid="gc-edit-recipient-email" />
                    <Input placeholder="Purchaser name" value={editForm.purchaserName} onChange={e => setEditForm({ ...editForm, purchaserName: e.target.value })} />
                    <Input placeholder="Purchaser email" value={editForm.purchaserEmail} onChange={e => setEditForm({ ...editForm, purchaserEmail: e.target.value })} />
                    <Input placeholder="Occasion" value={editForm.occasion} onChange={e => setEditForm({ ...editForm, occasion: e.target.value })} />
                  </div>
                  <Textarea rows={2} placeholder="Message" value={editForm.message} onChange={e => setEditForm({ ...editForm, message: e.target.value })} />
                  <div className="flex gap-2">
                    <Button size="sm" onClick={saveEdit} style={{ background: theme.primary }} className="text-white" data-testid="gc-edit-save"><Save size={12} className="mr-1" /> Save</Button>
                    <Button size="sm" variant="outline" onClick={() => setEditing(false)}>Cancel</Button>
                  </div>
                </div>
              )}

              {canManage && !editing && (
                <div className="rounded-lg border p-3 space-y-3">
                  <p className="text-[10px] uppercase tracking-widest font-semibold text-gray-500">Owner actions</p>
                  <div className="flex flex-wrap items-center gap-2">
                    <Input type="number" placeholder="Add credit $" value={reloadAmount} onChange={e => setReloadAmount(e.target.value)}
                      className="w-32 h-8" data-testid="gc-reload-amount" />
                    <Button size="sm" variant="outline" onClick={doReload} data-testid="gc-reload-btn"><PlusCircle size={12} className="mr-1" /> Add credit</Button>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <Input placeholder="Resend to email (optional override)" value={resendEmail} onChange={e => setResendEmail(e.target.value)}
                      className="w-56 h-8" data-testid="gc-resend-email" />
                    <Button size="sm" variant="outline" onClick={doResend} data-testid="gc-resend-btn"><Send size={12} className="mr-1" /> Resend</Button>
                  </div>
                  <div className="flex gap-2">
                    {detail.status === 'stopped' ? (
                      <Button size="sm" variant="outline" onClick={doReactivate} className="text-emerald-600" data-testid="gc-reactivate-btn">
                        <RotateCcw size={12} className="mr-1" /> Reactivate
                      </Button>
                    ) : (
                      <Button size="sm" variant="outline" onClick={doStop} className="text-red-600" data-testid="gc-stop-btn">
                        <Ban size={12} className="mr-1" /> Stop card
                      </Button>
                    )}
                  </div>
                </div>
              )}

              <div>
                <p className="text-[10px] uppercase tracking-widest font-semibold text-gray-500 mb-1 flex items-center gap-1">
                  <History size={11} /> Transaction history ({txns.length})
                </p>
                <div className="rounded border divide-y max-h-40 overflow-y-auto" data-testid="gc-transactions">
                  {txns.length === 0 ? (
                    <p className="p-3 text-xs text-gray-400 italic">No activity yet.</p>
                  ) : txns.map((t, i) => (
                    <div key={t.id || i} className="p-2 text-xs" data-testid={`gc-txn-${i}`}>
                      <div className="flex justify-between">
                        <span className="capitalize font-medium">{t.type}</span>
                        <span className="text-gray-500">{(t.createdAt || '').slice(0, 16)}</span>
                      </div>
                      <p className="text-[10px] text-gray-500">
                        ${t.amount?.toFixed?.(2) ?? t.amount} · balance ${t.balanceBefore?.toFixed?.(2)} → ${t.balanceAfter?.toFixed?.(2)}
                      </p>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setDetail(null)}>Close</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
