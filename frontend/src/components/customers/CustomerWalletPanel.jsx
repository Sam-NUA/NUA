import React, { useEffect, useState } from 'react';
import { Card, CardContent } from '../ui/card';
import { Button } from '../ui/button';
import { Badge } from '../ui/badge';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../ui/tabs';
import { finalizeAPI } from '../../services/api';
import { toast } from 'sonner';
import {
  Wallet, Coins, DollarSign, Gift, Award, Users as UsersIcon,
  ShoppingCart, RotateCcw, Star, Sparkles, Calendar,
  Trophy, TrendingUp, Flame, RefreshCcw,
} from 'lucide-react';

const BUCKETS = [
  { key: 'points',       label: 'Points',       icon: Coins,       c: '#f59e0b' },
  { key: 'store_credit', label: 'Store credit', icon: DollarSign,  c: '#10b981' },
  { key: 'gift_card',    label: 'Gift cards',   icon: Gift,        c: '#a855f7' },
  { key: 'voucher',      label: 'Voucher',      icon: Award,       c: '#3b82f6' },
  { key: 'cashback',     label: 'Cashback',     icon: TrendingUp,  c: '#ef4444' },
  { key: 'referral',     label: 'Referral',     icon: UsersIcon,   c: '#0ea5e9' },
];

const ICON_MAP = { booking: Calendar, order: ShoppingCart, refund: RotateCcw, ledger: Wallet, voucher: Gift, review: Star };

export default function CustomerWalletPanel({ customer, theme, onRefresh }) {
  const [wallet, setWallet] = useState(null);
  const [timeline, setTimeline] = useState(null);
  const [loyalty, setLoyalty] = useState(null);
  const [personal, setPersonal] = useState(null);
  const [tab, setTab] = useState('wallet');
  const [busy, setBusy] = useState(false);

  const load = async () => {
    if (!customer?.id) return;
    setBusy(true);
    try {
      const [w, t, l, p] = await Promise.all([
        finalizeAPI.walletGet(customer.id),
        finalizeAPI.walletTimeline(customer.id),
        finalizeAPI.loyaltyStatus(customer.id),
        finalizeAPI.personalisation(customer.id),
      ]);
      setWallet(w.data); setTimeline(t.data); setLoyalty(l.data); setPersonal(p.data);
      if ((l.data?.newlyAwarded || []).length) {
        toast.success(`New milestone: ${l.data.newlyAwarded[0].label}`);
      }
    } catch { /* silent */ }
    finally { setBusy(false); }
  };
  useEffect(() => { load();   }, [customer?.id]);

  const issueFromRecommendation = async (rec) => {
    try {
      await finalizeAPI.issueVoucher({
        label: rec.label,
        sourceType: 'promotion',
        valueType: rec.offer?.valueType || 'percentage',
        value: rec.offer?.value || 10,
        usageType: 'one_time',
        maxRedemptions: 1,
        customerId: customer.id,
        expiresAt: new Date(Date.now() + 30 * 24 * 3600 * 1000).toISOString(),
        rules: {
          activeDays: rec.offer?.activeDays || [],
          startTime: rec.offer?.startTime || null,
          endTime: rec.offer?.endTime || null,
          minSpend: rec.offer?.minSpend || 0,
        },
      });
      toast.success(`Voucher issued for ${customer.name}`);
      load(); onRefresh?.();
    } catch (e) { toast.error(e?.response?.data?.detail || 'Failed'); }
  };

  if (!customer) return null;

  return (
    <Card className="border-0 shadow-sm" data-testid="customer-wallet-panel">
      <CardContent className="p-4 space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Wallet size={16} style={{ color: theme?.primary || '#f97316' }} />
            <h3 className="font-semibold">Customer Wallet & Journey</h3>
            {loyalty?.tier && (
              <Badge className="bg-purple-100 text-purple-700 border-0" data-testid="wallet-tier">
                <Trophy size={11} className="mr-1" /> {loyalty.tier}
              </Badge>
            )}
            {loyalty?.streakWeeks > 0 && (
              <Badge className="bg-amber-100 text-amber-700 border-0" data-testid="wallet-streak">
                <Flame size={11} className="mr-1" /> {loyalty.streakWeeks}-week streak
              </Badge>
            )}
          </div>
          <Button size="sm" variant="ghost" onClick={load} data-testid="wallet-refresh">
            <RefreshCcw size={12} className={`mr-1 ${busy ? 'animate-spin' : ''}`} /> Refresh
          </Button>
        </div>

        {/* Balance buckets */}
        <div className="grid grid-cols-2 md:grid-cols-6 gap-2" data-testid="wallet-buckets">
          {BUCKETS.map(b => {
            const bal = wallet?.balances?.[b.key] || 0;
            const Icon = b.icon;
            const fmt = b.key === 'points' ? `${bal.toFixed(0)}` : `$${bal.toFixed(2)}`;
            return (
              <div key={b.key} className="rounded-lg border p-2.5 bg-gray-50/40" data-testid={`bucket-${b.key}`}>
                <div className="flex items-center gap-1.5 mb-1">
                  <Icon size={12} style={{ color: b.c }} />
                  <span className="text-[10px] uppercase tracking-widest font-semibold text-gray-500">{b.label}</span>
                </div>
                <p className="text-lg font-bold" style={{ color: theme?.text || '#111' }}>{fmt}</p>
              </div>
            );
          })}
        </div>

        {/* Loyalty progress */}
        {loyalty && loyalty.nextTier && (
          <div className="rounded-lg bg-gradient-to-r from-purple-50 to-pink-50 border border-purple-100 p-3" data-testid="loyalty-progress">
            <div className="flex items-center justify-between text-xs mb-1">
              <span className="font-medium">Next tier: <strong>{loyalty.nextTier}</strong></span>
              <span className="text-gray-500">{loyalty.points ?? 0} / {loyalty.nextTierAt} pts</span>
            </div>
            <div className="h-1.5 rounded-full bg-purple-100 overflow-hidden">
              <div className="h-full rounded-full bg-gradient-to-r from-purple-500 to-pink-500" style={{ width: `${Math.min(100, loyalty.tierProgressPct)}%` }} />
            </div>
          </div>
        )}

        {/* Milestones — collapsed row */}
        {(loyalty?.milestones || []).some(m => m.achieved) && (
          <div className="flex flex-wrap gap-1.5" data-testid="milestones-strip">
            {loyalty.milestones.filter(m => m.achieved).map(m => (
              <Badge key={m.key} className="bg-emerald-100 text-emerald-700 border-0 text-[10px]" data-testid={`milestone-${m.key}`}>
                <Trophy size={9} className="mr-1" /> {m.label}
              </Badge>
            ))}
          </div>
        )}

        <Tabs value={tab} onValueChange={setTab}>
          <TabsList className="grid grid-cols-3 w-full">
            <TabsTrigger value="wallet" data-testid="tab-wallet-vouchers">Vouchers</TabsTrigger>
            <TabsTrigger value="timeline" data-testid="tab-timeline">Journey</TabsTrigger>
            <TabsTrigger value="ai" data-testid="tab-ai-recs">
              <Sparkles size={11} className="mr-1" /> AI recs
            </TabsTrigger>
          </TabsList>

          <TabsContent value="wallet" className="mt-3 space-y-2">
            {(wallet?.vouchers || []).length === 0 ? (
              <p className="text-xs text-gray-400 italic text-center py-6">No active vouchers.</p>
            ) : (wallet?.vouchers || []).map(v => (
              <div key={v.id} className="rounded-lg border p-2 flex items-center justify-between" data-testid={`wallet-voucher-${v.id}`}>
                <div>
                  <p className="text-sm font-medium">{v.label}</p>
                  <p className="text-[10px] text-gray-500 font-mono">{v.code}</p>
                </div>
                <div className="text-right">
                  <p className="text-sm font-bold text-emerald-700">
                    {v.valueType === 'amount' ? `$${(v.residualValue || v.value).toFixed(2)}` : `${v.value}%`}
                  </p>
                  {v.expiresAt && <p className="text-[10px] text-gray-500">Expires {v.expiresAt.slice(0, 10)}</p>}
                </div>
              </div>
            ))}
          </TabsContent>

          <TabsContent value="timeline" className="mt-3">
            <div className="max-h-72 overflow-y-auto pr-1 space-y-1" data-testid="timeline-events">
              {(timeline?.events || []).slice(0, 40).map((ev, i) => {
                const Icon = ICON_MAP[ev.type] || Calendar;
                return (
                  <div key={i} className="flex items-start gap-2 py-1.5 border-b last:border-b-0 text-xs">
                    <Icon size={12} className="mt-0.5 text-gray-400" />
                    <div className="flex-1 min-w-0">
                      <p className="font-medium truncate">{ev.title}</p>
                      <p className="text-[10px] text-gray-400">{(ev.at || '').slice(0, 16)}</p>
                    </div>
                    <Badge className="bg-gray-100 text-gray-600 border-0 text-[9px] capitalize">{ev.type}</Badge>
                  </div>
                );
              })}
              {(timeline?.events || []).length === 0 && (
                <p className="text-xs text-gray-400 italic text-center py-6">No history yet.</p>
              )}
            </div>
            {timeline && (
              <div className="mt-3 flex items-center gap-4 text-[10px] uppercase tracking-widest text-gray-500">
                <span data-testid="ltv">LTV <strong className="text-gray-800 text-sm">${(timeline.lifetimeValue || 0).toFixed(0)}</strong></span>
                <span data-testid="total-orders">Orders <strong className="text-gray-800 text-sm">{timeline.totalOrders || 0}</strong></span>
              </div>
            )}
          </TabsContent>

          <TabsContent value="ai" className="mt-3 space-y-2">
            {(personal?.recommendations || []).length === 0 ? (
              <p className="text-xs text-gray-400 italic text-center py-6">No recommendations yet — need more transaction history.</p>
            ) : personal.recommendations.map((rec, i) => (
              <div key={i} className="rounded-lg bg-purple-50 border border-purple-100 p-2.5 flex items-center justify-between gap-2" data-testid={`rec-${i}`}>
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-purple-900 truncate">{rec.label}</p>
                  <p className="text-[10px] text-purple-700">{rec.reason}</p>
                </div>
                <Button size="sm" onClick={() => issueFromRecommendation(rec)} style={{ background: theme?.primary || '#f97316' }} className="text-white shrink-0" data-testid={`rec-issue-${i}`}>
                  Issue
                </Button>
              </div>
            ))}
            {personal?.insights && (
              <div className="text-[10px] text-gray-500 pt-2 border-t">
                Favourite: <strong>{personal.insights.favouriteItems?.[0]?.name || '—'}</strong> · Usual: <strong>{personal.insights.typicalWeekday || '—'} {personal.insights.typicalVisitHour !== null && personal.insights.typicalVisitHour !== undefined ? `@ ${personal.insights.typicalVisitHour}:00` : ''}</strong> · Avg check: <strong>${personal.insights.averageCheck || 0}</strong>
              </div>
            )}
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  );
}
