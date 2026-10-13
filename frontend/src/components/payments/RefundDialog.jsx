import React, { useEffect, useState, useMemo } from 'react';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '../ui/dialog';
import { Button } from '../ui/button';
import { Input } from '../ui/input';
import { Badge } from '../ui/badge';
import { Textarea } from '../ui/textarea';
import { finalizeAPI } from '../../services/api';
import { toast } from 'sonner';
import { CreditCard, DollarSign, Coins, Gift, Plus, X, RotateCcw } from 'lucide-react';
import SensitiveActionReauthDialog from '../security/SensitiveActionReauthDialog';

const MODE_META = {
  card:         { label: 'Original card',  icon: CreditCard, c: '#3b82f6' },
  store_credit: { label: 'Store credit',   icon: DollarSign, c: '#10b981' },
  points:       { label: 'Loyalty points', icon: Coins,      c: '#f59e0b' },
  voucher:      { label: 'Voucher',        icon: Gift,       c: '#a855f7' },
};

/**
 * Flexible refund with split modes.
 * Callers pass `transaction` (must include id, total, customerId?)
 * and receive the refund via `onDone(refund)` on success.
 */
export default function RefundDialog({ open, onClose, transaction, onDone }) {
  const [reason, setReason] = useState('');
  const [note, setNote] = useState('');
  const [splits, setSplits] = useState([]);
  const [saving, setSaving] = useState(false);
  // Directive Phase 5 — a refund is a sensitive action: gated behind PIN
  // reauth (or biometric, once/if a platform ever supports it) before the
  // actual API call fires. See SensitiveActionReauthDialog.
  const [showReauth, setShowReauth] = useState(false);

  useEffect(() => {
    if (open && transaction) {
      // Default: refund the full amount to the original payment method.
      setSplits([{ mode: 'card', amount: parseFloat((transaction.total || 0).toFixed(2)) }]);
      setReason(''); setNote('');
    }
  }, [open, transaction]);

  const total = useMemo(() => splits.reduce((s, x) => s + (parseFloat(x.amount) || 0), 0), [splits]);
  const original = parseFloat(transaction?.total || 0);
  const remaining = Math.max(0, original - total);

  const addSplit = (mode) => setSplits([...splits, { mode, amount: parseFloat(remaining.toFixed(2)) }]);
  const removeSplit = (i) => setSplits(splits.filter((_, idx) => idx !== i));
  const updateSplit = (i, patch) => setSplits(splits.map((s, idx) => idx === i ? { ...s, ...patch } : s));

  const submit = async () => {
    if (!transaction?.id) return toast.error('No transaction selected');
    if (Math.abs(total - original) > 0.01 && total > 0) {
      const ok = window.confirm(`Refund total $${total.toFixed(2)} does not equal original $${original.toFixed(2)}. Proceed as partial refund?`);
      if (!ok) return;
    }
    if (splits.some(s => s.mode !== 'card' && !transaction.customerId)) {
      return toast.error('Non-card refunds require a customer on the transaction');
    }
    setShowReauth(true);
  };

  const doRefund = async () => {
    setShowReauth(false);
    setSaving(true);
    try {
      const r = await finalizeAPI.createRefund({
        transactionId: transaction.id,
        customerId: transaction.customerId,
        amount: parseFloat(total.toFixed(2)),
        reason, note,
        splits: splits.map(s => ({
          mode: s.mode,
          amount: parseFloat(parseFloat(s.amount || 0).toFixed(2)),
          ...(s.mode === 'points' ? { pointsPerDollar: parseFloat(s.pointsPerDollar || 10) } : {}),
          ...(s.mode === 'voucher' ? { expireInDays: parseInt(s.expireInDays || 180), partialRedeemable: true, label: s.label } : {}),
        })),
      });
      toast.success(`Refund $${r.data.amount.toFixed(2)} processed`);
      onDone?.(r.data);
      onClose?.();
    } catch (e) { toast.error(e?.response?.data?.detail || 'Refund failed'); }
    finally { setSaving(false); }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose?.(); }}>
      <DialogContent className="max-w-lg max-h-[85vh] overflow-y-auto" data-testid="refund-dialog">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <RotateCcw size={16} /> Refund transaction {transaction?.id}
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-3 py-2">
          <div className="rounded-lg bg-gray-50 border p-3 flex items-center justify-between text-sm">
            <div>
              <p className="text-[10px] uppercase tracking-widest text-gray-500">Original total</p>
              <p className="font-bold text-lg">${original.toFixed(2)}</p>
            </div>
            <div className="text-right">
              <p className="text-[10px] uppercase tracking-widest text-gray-500">Refund total</p>
              <p className="font-bold text-lg" style={{ color: Math.abs(total - original) < 0.01 ? '#10b981' : '#f59e0b' }} data-testid="refund-total">
                ${total.toFixed(2)}
              </p>
            </div>
          </div>

          <Input placeholder="Reason (visible on receipt)"
            value={reason} onChange={e => setReason(e.target.value)} data-testid="refund-reason" />
          <Textarea rows={2} placeholder="Internal note (optional)"
            value={note} onChange={e => setNote(e.target.value)} />

          <div className="space-y-2" data-testid="refund-splits">
            {splits.map((s, i) => {
              const M = MODE_META[s.mode] || MODE_META.card;
              const Icon = M.icon;
              return (
                <div key={i} className="rounded-lg border p-2.5 space-y-1.5" data-testid={`refund-split-${i}`}>
                  <div className="flex items-center gap-2">
                    <div className="w-7 h-7 rounded-lg flex items-center justify-center" style={{ background: `${M.c}15` }}>
                      <Icon size={14} style={{ color: M.c }} />
                    </div>
                    <Badge className="border-0 text-[10px]" style={{ background: `${M.c}18`, color: M.c }}>{M.label}</Badge>
                    <div className="flex-1" />
                    <Input type="number" step="0.01" min="0" value={s.amount}
                      onChange={e => updateSplit(i, { amount: e.target.value })}
                      className="w-28 h-8" data-testid={`refund-amount-${i}`} />
                    {splits.length > 1 && (
                      <Button size="sm" variant="ghost" onClick={() => removeSplit(i)} className="text-red-500" data-testid={`refund-remove-${i}`}>
                        <X size={12} />
                      </Button>
                    )}
                  </div>
                  {s.mode === 'points' && (
                    <div className="flex items-center gap-2 text-xs">
                      <span className="text-gray-500">Points per $:</span>
                      <Input type="number" min="1" value={s.pointsPerDollar || 10}
                        onChange={e => updateSplit(i, { pointsPerDollar: e.target.value })}
                        className="w-20 h-7" />
                      <span className="text-gray-400">= {((parseFloat(s.amount) || 0) * (parseFloat(s.pointsPerDollar) || 10)).toFixed(0)} pts</span>
                    </div>
                  )}
                  {s.mode === 'voucher' && (
                    <div className="grid grid-cols-2 gap-2">
                      <Input placeholder="Voucher label" value={s.label || ''} onChange={e => updateSplit(i, { label: e.target.value })} className="h-7 text-xs" />
                      <Input type="number" min="1" placeholder="Valid for (days)" value={s.expireInDays || 180}
                        onChange={e => updateSplit(i, { expireInDays: e.target.value })} className="h-7 text-xs" />
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[10px] uppercase tracking-widest text-gray-500">Add split:</span>
            {['card','store_credit','points','voucher'].map(m => {
              const M = MODE_META[m];
              const Icon = M.icon;
              return (
                <Button key={m} size="sm" variant="outline" onClick={() => addSplit(m)} data-testid={`add-split-${m}`}>
                  <Plus size={11} className="mr-1" /> <Icon size={11} className="mr-1" /> {M.label}
                </Button>
              );
            })}
          </div>

          {remaining > 0.01 && (
            <div className="text-xs text-amber-700 rounded bg-amber-50 border border-amber-100 p-2">
              ${remaining.toFixed(2)} of the original total is not yet allocated — add another split or leave as partial refund.
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={submit} disabled={saving || total <= 0} className="text-white" style={{ background: '#dc2626' }} data-testid="refund-submit">
            {saving ? 'Processing…' : `Refund $${total.toFixed(2)}`}
          </Button>
        </DialogFooter>
      </DialogContent>
      <SensitiveActionReauthDialog
        open={showReauth}
        label={`issue a $${total.toFixed(2)} refund`}
        onVerified={doRefund}
        onCancel={() => setShowReauth(false)}
      />
    </Dialog>
  );
}
