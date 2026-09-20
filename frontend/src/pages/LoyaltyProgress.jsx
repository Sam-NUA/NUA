import React, { useEffect, useState, useCallback } from 'react';
import axios from 'axios';
import { Card, CardContent } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Input } from '../components/ui/input';
import { Textarea } from '../components/ui/textarea';
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from '../components/ui/select';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '../components/ui/tabs';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '../components/ui/dialog';
import { toast } from 'sonner';
import {
  Award, RefreshCw, Sparkles, Coffee, Heart, Trophy, DollarSign, Crown, Sunrise,
  Wine, Users, Gift, Search, Plus, Trash2, Lock, CheckCircle2, Target, UserPlus,
  AlertTriangle, Wallet, TrendingUp,
} from 'lucide-react';

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const H = () => ({ Authorization: `Bearer ${localStorage.getItem('nua_token')}` });


function LeaderboardPanel() {
  const [metric, setMetric] = React.useState('points');
  const [data, setData] = React.useState({ metric: 'points', entries: [] });
  const [loading, setLoading] = React.useState(false);
  const load = React.useCallback(async () => {
    setLoading(true);
    try {
      const r = await axios.get(`${API}/loyalty/v2/leaderboard?metric=${metric}&limit=25`, { headers: H() });
      setData(r.data);
    } catch { toast.error('Failed to load leaderboard'); }
    finally { setLoading(false); }
  }, [metric]);
  React.useEffect(() => { load(); }, [load]);

  const METRIC_LABEL = { points: 'Points', visits: 'Visits', spend: 'Spend ($)', referrals: 'Referrals' };
  const METRIC_ICON = { points: Award, visits: Users, spend: DollarSign, referrals: UserPlus };
  const CIcon = METRIC_ICON[metric] || Award;

  return (
    <Card><CardContent className="p-5 space-y-4">
      <div className="flex justify-between items-center flex-wrap gap-2">
        <div className="flex gap-1 flex-wrap">
          {Object.entries(METRIC_LABEL).map(([m, l]) => (
            <Button key={m} size="sm" variant={metric === m ? 'default' : 'outline'}
              onClick={() => setMetric(m)} data-testid={`leader-metric-${m}`}>
              {l}
            </Button>
          ))}
        </div>
        <Button size="sm" variant="outline" onClick={load} disabled={loading} data-testid="leader-refresh">
          <RefreshCw size={12} className={`mr-1 ${loading ? 'animate-spin' : ''}`} /> Refresh
        </Button>
      </div>
      <div className="space-y-1">
        {data.entries.length === 0 && <p className="text-center text-sm text-slate-400 py-8">No data yet.</p>}
        {data.entries.map(e => (
          <div key={e.customerId} className={`flex items-center gap-3 p-3 rounded border ${e.rank <= 3 ? 'bg-gradient-to-r from-amber-50 to-white' : ''}`}
            data-testid={`leader-row-${e.rank}`}>
            <div className={`h-9 w-9 rounded-full flex items-center justify-center font-bold ${
              e.rank === 1 ? 'bg-amber-400 text-white' :
              e.rank === 2 ? 'bg-slate-300 text-white' :
              e.rank === 3 ? 'bg-orange-400 text-white' :
              'bg-slate-100 text-slate-500'
            }`}>{e.rank}</div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium truncate">{e.name}</p>
              <p className="text-[10px] text-slate-500">{e.tier || 'Bronze'} · {e.totalVisits || 0} visits · {e.referrals || 0} referrals</p>
            </div>
            <div className="text-right">
              <p className="font-bold text-lg flex items-center gap-1" style={{ color: '#6366f1' }}>
                <CIcon size={14} /> {(e.value || 0).toLocaleString()}
              </p>
              <p className="text-[10px] text-slate-400">{METRIC_LABEL[metric].toLowerCase()}</p>
            </div>
          </div>
        ))}
      </div>
    </CardContent></Card>
  );
}


function ReportsPanel() {
  const [liability, setLiability] = React.useState(null);
  const [roi, setRoi] = React.useState(null);
  const [flags, setFlags] = React.useState(null);
  const [locked, setLocked] = React.useState(null);
  const [loading, setLoading] = React.useState(false);
  const load = React.useCallback(async () => {
    setLoading(true);
    try {
      const [l, r, f, lk] = await Promise.all([
        axios.get(`${API}/loyalty/reports/liability`, { headers: H() }),
        axios.get(`${API}/loyalty/reports/roi`, { headers: H() }),
        axios.get(`${API}/loyalty/reports/fraud-flags`, { headers: H() }),
        axios.get(`${API}/loyalty/reports/locked-accounts`, { headers: H() }),
      ]);
      setLiability(l.data);
      setRoi(r.data);
      setFlags(f.data);
      setLocked(lk.data);
    } catch { toast.error('Failed to load loyalty reports'); }
    finally { setLoading(false); }
  }, []);
  React.useEffect(() => { load(); }, [load]);

  const [resolving, setResolving] = React.useState(null);
  const resolveFlag = async (flagId, status) => {
    setResolving(flagId);
    try {
      const r = await axios.put(`${API}/loyalty/reports/fraud-flags/${flagId}`, { status }, { headers: H() });
      toast.success(status === 'confirmed_abuse' ? (r.data.actionTaken || 'Confirmed') : 'Marked reviewed');
      load();
    } catch (e) { toast.error(e.response?.data?.detail || 'Failed to resolve flag'); }
    finally { setResolving(null); }
  };

  const [unlocking, setUnlocking] = React.useState(null);
  const unlockAccount = async (customerId) => {
    setUnlocking(customerId);
    try {
      await axios.post(`${API}/loyalty/customers/${customerId}/unlock`, {}, { headers: H() });
      toast.success('Loyalty account unlocked');
      load();
    } catch (e) { toast.error(e.response?.data?.detail || 'Failed to unlock account'); }
    finally { setUnlocking(null); }
  };

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <Button size="sm" variant="outline" onClick={load} disabled={loading} data-testid="reports-refresh">
          <RefreshCw size={12} className={`mr-1 ${loading ? 'animate-spin' : ''}`} /> Refresh
        </Button>
      </div>

      <Card><CardContent className="p-5">
        <h3 className="font-semibold flex items-center gap-2 mb-1"><Wallet size={16} /> Outstanding Points Liability</h3>
        <p className="text-xs text-slate-500 mb-4">Points sitting on customer balances are $ the business owes in future discounts — same accounting posture as gratuity being tracked as a liability, not revenue.</p>
        {liability && (
          <div className="grid grid-cols-3 gap-4 mb-4">
            <div className="text-center p-3 rounded border bg-slate-50">
              <p className="text-2xl font-bold" data-testid="liability-value">${liability.totalLiabilityValue.toLocaleString()}</p>
              <p className="text-[11px] text-slate-500 uppercase tracking-wide">Liability value</p>
            </div>
            <div className="text-center p-3 rounded border bg-slate-50">
              <p className="text-2xl font-bold">{liability.totalPointsOutstanding.toLocaleString()}</p>
              <p className="text-[11px] text-slate-500 uppercase tracking-wide">Points outstanding</p>
            </div>
            <div className="text-center p-3 rounded border bg-slate-50">
              <p className="text-2xl font-bold">{liability.customersWithBalance.toLocaleString()}</p>
              <p className="text-[11px] text-slate-500 uppercase tracking-wide">Customers with balance</p>
            </div>
          </div>
        )}
        {liability?.topHolders?.length > 0 && (
          <div className="space-y-1">
            <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">Top balance holders</p>
            {liability.topHolders.slice(0, 8).map(h => (
              <div key={h.customerId} className="flex justify-between text-sm py-1 border-b last:border-0" data-testid={`liability-holder-${h.customerId}`}>
                <span>{h.name}</span>
                <span className="text-slate-500">{h.points.toLocaleString()} pts · ${h.value.toFixed(2)}</span>
              </div>
            ))}
          </div>
        )}
      </CardContent></Card>

      <Card><CardContent className="p-5">
        <h3 className="font-semibold flex items-center gap-2 mb-1"><TrendingUp size={16} className="text-emerald-600" /> Loyalty ROI</h3>
        <p className="text-xs text-slate-500 mb-4">{roi?.methodology || 'What the program has actually paid out in redemptions, vs. how much more engaged members spend on average — a directional signal, not a certified figure.'}</p>
        {roi && (
          <>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-4">
              <div className="text-center p-3 rounded border bg-slate-50">
                <p className="text-2xl font-bold" data-testid="roi-program-cost">${roi.programCost.toLocaleString()}</p>
                <p className="text-[11px] text-slate-500 uppercase tracking-wide">Redeemed (cost)</p>
              </div>
              <div className="text-center p-3 rounded border bg-slate-50">
                <p className="text-2xl font-bold" data-testid="roi-incremental-spend">${roi.estimatedIncrementalSpend.toLocaleString()}</p>
                <p className="text-[11px] text-slate-500 uppercase tracking-wide">Est. incremental spend</p>
              </div>
              <div className="text-center p-3 rounded border bg-slate-50">
                <p className="text-2xl font-bold" data-testid="roi-multiple">{roi.roiMultiple == null ? '—' : `${roi.roiMultiple}×`}</p>
                <p className="text-[11px] text-slate-500 uppercase tracking-wide">ROI multiple</p>
              </div>
              <div className="text-center p-3 rounded border bg-slate-50">
                <p className="text-2xl font-bold">{roi.engagedCustomers.toLocaleString()}</p>
                <p className="text-[11px] text-slate-500 uppercase tracking-wide">Engaged members</p>
              </div>
            </div>
            <div className="flex justify-between text-xs text-slate-500 mb-3 px-1">
              <span>Avg spend, engaged: <strong className="text-slate-700">${roi.avgSpendEngaged.toLocaleString()}</strong></span>
              <span>Avg spend, never engaged: <strong className="text-slate-700">${roi.avgSpendNeverEngaged.toLocaleString()}</strong></span>
            </div>
            {roi.byTier?.length > 0 && (
              <div className="space-y-1">
                <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">By tier</p>
                {roi.byTier.map(t => (
                  <div key={t.tier} className="flex justify-between text-sm py-1 border-b last:border-0" data-testid={`roi-tier-${t.tier}`}>
                    <span>{t.tier} <span className="text-slate-400">({t.customerCount})</span></span>
                    <span className="text-slate-500">${t.avgSpend.toLocaleString()} avg spend · {t.avgVisits} avg visits</span>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </CardContent></Card>

      <Card><CardContent className="p-5">
        <h3 className="font-semibold flex items-center gap-2 mb-1"><AlertTriangle size={16} className="text-amber-500" /> Fraud Flags</h3>
        <p className="text-xs text-slate-500 mb-4">Point farming (unusually many earn events in 24h) and voucher sharing (same code redeemed from different terminals within 10 minutes).</p>
        {flags?.flags?.length === 0 && <p className="text-center text-sm text-slate-400 py-6">No flags — nothing unusual in the last check.</p>}
        <div className="space-y-2">
          {(flags?.flags || []).map((f) => (
            <div key={f.id} className="flex items-start gap-3 p-3 rounded border border-amber-200 bg-amber-50" data-testid={`fraud-flag-${f.id}`}>
              <AlertTriangle size={14} className="text-amber-500 mt-0.5 flex-shrink-0" />
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium">
                  {f.type === 'point_farming' ? `${f.customerName || f.customerId} — point farming` : `Voucher ${f.code || f.voucherId} — possible sharing`}
                </p>
                <p className="text-xs text-slate-500">{f.reason}</p>
                {f.status !== 'open' && (
                  <p className="text-xs mt-1">
                    <Badge className={f.status === 'confirmed_abuse' ? 'bg-red-100 text-red-700' : 'bg-emerald-100 text-emerald-700'}>
                      {f.status === 'confirmed_abuse' ? 'Confirmed abuse' : 'Reviewed OK'}
                    </Badge>
                    {f.actionTaken && <span className="text-slate-400 ml-2">{f.actionTaken}</span>}
                  </p>
                )}
              </div>
              {f.status === 'open' ? (
                <div className="flex gap-1.5 flex-shrink-0">
                  <Button size="sm" variant="outline" className="h-7 text-xs" disabled={resolving === f.id}
                    onClick={() => resolveFlag(f.id, 'reviewed_ok')} data-testid={`flag-ok-${f.id}`}>
                    Reviewed OK
                  </Button>
                  <Button size="sm" className="h-7 text-xs bg-red-600 hover:bg-red-700 text-white" disabled={resolving === f.id}
                    onClick={() => resolveFlag(f.id, 'confirmed_abuse')} data-testid={`flag-confirm-${f.id}`}>
                    Confirm Abuse
                  </Button>
                </div>
              ) : (
                <Badge variant="outline" className="text-[10px] flex-shrink-0">{f.type.replace('_', ' ')}</Badge>
              )}
            </div>
          ))}
        </div>
      </CardContent></Card>

      <Card><CardContent className="p-5">
        <h3 className="font-semibold flex items-center gap-2 mb-1"><Lock size={16} className="text-red-500" /> Locked Loyalty Accounts</h3>
        <p className="text-xs text-slate-500 mb-4">Confirming a point-farming flag above locks the account here — no redemption until it's unlocked.</p>
        {locked?.accounts?.length === 0 && <p className="text-center text-sm text-slate-400 py-6">No locked accounts.</p>}
        <div className="space-y-2">
          {(locked?.accounts || []).map(c => (
            <div key={c.id} className="flex items-center justify-between gap-3 p-3 rounded border border-red-200 bg-red-50" data-testid={`locked-account-${c.id}`}>
              <div className="min-w-0">
                <p className="text-sm font-medium truncate">{c.name || c.id}</p>
                <p className="text-xs text-slate-500">{c.email || '—'} · {(c.points || 0).toLocaleString()} pts</p>
              </div>
              <Button size="sm" variant="outline" className="h-7 text-xs flex-shrink-0" disabled={unlocking === c.id}
                onClick={() => unlockAccount(c.id)} data-testid={`unlock-account-${c.id}`}>
                {unlocking === c.id ? 'Unlocking...' : 'Unlock'}
              </Button>
            </div>
          ))}
        </div>
      </CardContent></Card>
    </div>
  );
}


function ReferralsPanel({ customers }) {
  const [refs, setRefs] = React.useState([]);
  const [newRef, setNewRef] = React.useState({ referrerId: '', refereeEmail: '', refereeId: '' });
  const [loading, setLoading] = React.useState(false);
  const load = React.useCallback(async () => {
    setLoading(true);
    try {
      const r = await axios.get(`${API}/loyalty/v2/referrals`, { headers: H() });
      setRefs(r.data);
    } catch { toast.error('Failed to load referrals'); }
    finally { setLoading(false); }
  }, []);
  React.useEffect(() => { load(); }, [load]);

  const create = async () => {
    if (!newRef.referrerId || (!newRef.refereeEmail && !newRef.refereeId)) {
      toast.error('Pick a referrer and either a referee customer or email');
      return;
    }
    try {
      await axios.post(`${API}/loyalty/v2/referrals`, newRef, { headers: H() });
      toast.success('Referral created');
      setNewRef({ referrerId: '', refereeEmail: '', refereeId: '' });
      load();
    } catch { toast.error('Failed to create referral'); }
  };

  const complete = async (id, refereeId) => {
    try {
      await axios.post(`${API}/loyalty/v2/referrals/${id}/complete`, { refereeId }, { headers: H() });
      toast.success('Referral completed — vouchers issued');
      load();
    } catch { toast.error('Failed to complete'); }
  };

  const nameFor = (id) => (customers.find(c => c.id === id) || {}).name || id?.slice(0, 8) || '—';

  return (
    <div className="space-y-4">
      <Card><CardContent className="p-5 space-y-3">
        <div className="flex items-center gap-2">
          <UserPlus size={16} className="text-indigo-600" />
          <h3 className="font-semibold text-sm">Create a referral</h3>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-4 gap-2">
          <Select value={newRef.referrerId} onValueChange={v => setNewRef(f => ({ ...f, referrerId: v }))}>
            <SelectTrigger data-testid="ref-referrer"><SelectValue placeholder="Referrer" /></SelectTrigger>
            <SelectContent className="max-h-64">
              {customers.map(c => <SelectItem key={c.id} value={c.id}>{c.name || c.email}</SelectItem>)}
            </SelectContent>
          </Select>
          <Select value={newRef.refereeId} onValueChange={v => setNewRef(f => ({ ...f, refereeId: v, refereeEmail: '' }))}>
            <SelectTrigger data-testid="ref-referee"><SelectValue placeholder="Existing referee (optional)" /></SelectTrigger>
            <SelectContent className="max-h-64">
              {customers.filter(c => c.id !== newRef.referrerId).map(c => <SelectItem key={c.id} value={c.id}>{c.name || c.email}</SelectItem>)}
            </SelectContent>
          </Select>
          <Input placeholder="Or referee email" value={newRef.refereeEmail}
            onChange={e => setNewRef(f => ({ ...f, refereeEmail: e.target.value, refereeId: '' }))}
            data-testid="ref-email" />
          <Button onClick={create} data-testid="ref-create">Create</Button>
        </div>
      </CardContent></Card>

      <Card><CardContent className="p-5">
        <div className="flex justify-between items-center mb-3">
          <h3 className="font-semibold text-sm">Referrals ({refs.length})</h3>
          <Button size="sm" variant="outline" onClick={load} disabled={loading} data-testid="ref-refresh">
            <RefreshCw size={12} className={`mr-1 ${loading ? 'animate-spin' : ''}`} /> Refresh
          </Button>
        </div>
        {refs.length === 0 && <p className="text-center text-sm text-slate-400 py-6">No referrals yet.</p>}
        <div className="space-y-2">
          {refs.map(r => (
            <div key={r.id} className="p-3 border rounded flex justify-between items-center gap-3" data-testid={`ref-row-${r.id}`}>
              <div className="min-w-0 flex-1">
                <p className="text-sm">
                  <b>{nameFor(r.referrerId)}</b> → {r.refereeId ? <b>{nameFor(r.refereeId)}</b> : <span className="italic">{r.refereeEmail}</span>}
                </p>
                <p className="text-[10px] text-slate-500 mt-0.5">
                  Code <code>{r.code}</code> · created {new Date(r.createdAt).toLocaleDateString()}
                </p>
              </div>
              <Badge className={r.status === 'completed' ? 'bg-emerald-500' : 'bg-amber-500'}>{r.status}</Badge>
              {r.status === 'pending' && r.refereeId && (
                <Button size="sm" onClick={() => complete(r.id, r.refereeId)} data-testid={`ref-complete-${r.id}`}>
                  Mark completed
                </Button>
              )}
            </div>
          ))}
        </div>
      </CardContent></Card>
    </div>
  );
}

// Map lucide icon names in DB → components
const ICONS = {
  sparkles: Sparkles, coffee: Coffee, heart: Heart, trophy: Trophy,
  'dollar-sign': DollarSign, crown: Crown, sunrise: Sunrise, wine: Wine,
  users: Users, gift: Gift,
};

const TIER_COLOR = {
  Bronze: '#a16207', Silver: '#94a3b8', Gold: '#eab308', Platinum: '#a855f7',
};

export default function LoyaltyProgress() {
  const [customers, setCustomers] = useState([]);
  const [selected, setSelected] = useState(null);
  const [progress, setProgress] = useState(null);
  const [query, setQuery] = useState('');
  const [refreshing, setRefreshing] = useState(false);
  const [challenges, setChallenges] = useState([]);
  const [addChallengeOpen, setAddChallengeOpen] = useState(false);
  const [challengeForm, setChallengeForm] = useState({
    name: '', description: '', metric: 'visits', target: 3,
    startDate: new Date().toISOString().slice(0, 10),
    endDate: new Date(Date.now() + 30 * 24 * 60 * 60 * 1000).toISOString().slice(0, 10),
    reward: { type: 'voucher', value: 20, label: '$20 voucher' },
  });

  const loadCustomers = useCallback(async () => {
    try {
      const r = await axios.get(`${API}/customers`, { headers: H() });
      setCustomers(r.data || []);
    } catch { /* ignore */ }
  }, []);

  const loadChallenges = useCallback(async () => {
    try {
      const r = await axios.get(`${API}/loyalty/v2/challenges?active_only=false`, { headers: H() });
      setChallenges(r.data || []);
    } catch { /* ignore */ }
  }, []);

  const loadProgress = useCallback(async (id) => {
    if (!id) return;
    setRefreshing(true);
    try {
      // Evaluate first (idempotent) so any newly-earned items show
      await axios.post(`${API}/loyalty/v2/evaluate/${id}`, {}, { headers: H() });
      const r = await axios.get(`${API}/loyalty/v2/progress/${id}`, { headers: H() });
      setProgress(r.data);
    } catch { toast.error('Failed to load progress'); }
    finally { setRefreshing(false); }
  }, []);

  useEffect(() => { loadCustomers(); loadChallenges(); }, [loadCustomers, loadChallenges]);
  useEffect(() => { if (selected) loadProgress(selected.id); }, [selected, loadProgress]);

  const filtered = customers.filter(c =>
    (c.name || '').toLowerCase().includes(query.toLowerCase()) ||
    (c.email || '').toLowerCase().includes(query.toLowerCase())
  ).slice(0, 100);

  const createChallenge = async () => {
    if (!challengeForm.name) return;
    try {
      await axios.post(`${API}/loyalty/v2/challenges`, {
        ...challengeForm,
        startDate: new Date(challengeForm.startDate).toISOString(),
        endDate: new Date(challengeForm.endDate + 'T23:59:59').toISOString(),
      }, { headers: H() });
      toast.success('Challenge created');
      setAddChallengeOpen(false);
      loadChallenges();
    } catch { toast.error('Failed'); }
  };

  const deleteChallenge = async (id) => {
    if (!window.confirm('Delete this challenge?')) return;
    try {
      await axios.delete(`${API}/loyalty/v2/challenges/${id}`, { headers: H() });
      loadChallenges();
    } catch { toast.error('Failed'); }
  };

  return (
    <div className="space-y-6" data-testid="loyalty-progress-page">
      <div className="flex justify-between items-center flex-wrap gap-3">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-2">
            <Award className="text-indigo-600" /> Loyalty 2.0
          </h1>
          <p className="text-sm text-slate-500 mt-1">Badges, milestones, seasonal challenges &amp; tier progression.</p>
        </div>
        {selected && (
          <Button variant="outline" onClick={() => loadProgress(selected.id)} disabled={refreshing} data-testid="loyalty-refresh-btn">
            <RefreshCw size={14} className={`mr-1.5 ${refreshing ? 'animate-spin' : ''}`} /> Refresh
          </Button>
        )}
      </div>

      <Tabs defaultValue="customer">
        <TabsList>
          <TabsTrigger value="customer" data-testid="tab-customer"><Award size={14} className="mr-1" /> Per-customer</TabsTrigger>
          <TabsTrigger value="leaderboard" data-testid="tab-leaderboard"><Trophy size={14} className="mr-1" /> Leaderboard</TabsTrigger>
          <TabsTrigger value="referrals" data-testid="tab-referrals"><UserPlus size={14} className="mr-1" /> Referrals</TabsTrigger>
          <TabsTrigger value="challenges" data-testid="tab-challenges"><Target size={14} className="mr-1" /> Challenges</TabsTrigger>
          <TabsTrigger value="reports" data-testid="tab-reports"><AlertTriangle size={14} className="mr-1" /> Reports</TabsTrigger>
        </TabsList>

        <TabsContent value="customer" className="space-y-4">
          <div className="grid md:grid-cols-12 gap-4">
            {/* Customer picker */}
            <div className="md:col-span-4">
              <Card><CardContent className="p-3 space-y-2">
                <div className="relative">
                  <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                  <Input placeholder="Search customer\u2026" value={query} onChange={e => setQuery(e.target.value)} className="pl-9" data-testid="loyalty-search" />
                </div>
                <div className="max-h-[520px] overflow-y-auto space-y-1">
                  {filtered.map(c => (
                    <button
                      key={c.id}
                      onClick={() => setSelected(c)}
                      className={`w-full text-left p-2 rounded transition ${selected?.id === c.id ? 'bg-indigo-50 border border-indigo-300' : 'hover:bg-slate-50'}`}
                      data-testid={`cust-${c.id}`}
                    >
                      <p className="text-sm font-medium truncate">{c.name || c.email}</p>
                      <p className="text-[10px] text-slate-500">
                        {c.membershipTier || 'Bronze'} &middot; {c.loyaltyPoints || 0} pts &middot; {c.totalVisits || c.visits || 0} visits
                      </p>
                    </button>
                  ))}
                  {filtered.length === 0 && <p className="text-xs text-slate-400 text-center py-6">No customers match.</p>}
                </div>
              </CardContent></Card>
            </div>

            {/* Progress panel */}
            <div className="md:col-span-8">
              {!progress ? (
                <Card><CardContent className="p-12 text-center text-sm text-slate-500">
                  <Award className="mx-auto mb-2 opacity-40" size={28} />
                  Pick a customer to see badges, milestones and tier progress.
                </CardContent></Card>
              ) : (
                <div className="space-y-4" data-testid="progress-panel">
                  {/* Tier hero */}
                  <Card><CardContent className="p-6">
                    <div className="flex justify-between items-start gap-4 flex-wrap">
                      <div>
                        <p className="text-xs uppercase tracking-wider text-slate-400">Tier</p>
                        <h2 className="text-2xl font-bold mt-1" style={{ color: TIER_COLOR[progress.tier] || '#334155' }} data-testid="tier-name">
                          {progress.tier || 'Bronze'}
                        </h2>
                        <p className="text-sm text-slate-500 mt-1">{progress.points} points &middot; {progress.customerName}</p>
                      </div>
                      {progress.tierProgress?.next && (
                        <div className="text-right">
                          <p className="text-xs text-slate-500">Next tier</p>
                          <p className="font-semibold" style={{ color: TIER_COLOR[progress.tierProgress.next] || '#334155' }}>
                            {progress.tierProgress.next}
                          </p>
                          <p className="text-[10px] text-slate-500 mt-1">
                            {progress.tierProgress.pointsNeeded} pts to go
                          </p>
                        </div>
                      )}
                    </div>
                    {progress.tierProgress && (
                      <div className="mt-4">
                        <div className="h-3 bg-slate-100 rounded-full overflow-hidden">
                          <div className="h-full transition-all"
                            style={{
                              width: `${progress.tierProgress.percent}%`,
                              background: `linear-gradient(to right, ${TIER_COLOR[progress.tierProgress.current]}, ${TIER_COLOR[progress.tierProgress.next] || TIER_COLOR[progress.tierProgress.current]})`,
                            }} />
                        </div>
                        <p className="text-[10px] text-slate-500 mt-1">{progress.tierProgress.percent}% to next tier</p>
                      </div>
                    )}
                  </CardContent></Card>

                  {/* Badges */}
                  <Card><CardContent className="p-5">
                    <p className="text-xs uppercase tracking-wider text-slate-400 mb-3">Badges</p>
                    <div className="grid grid-cols-3 sm:grid-cols-5 gap-3">
                      {progress.badges.map(b => {
                        const Icon = ICONS[b.icon] || Sparkles;
                        return (
                          <div key={b.id} className={`text-center p-3 rounded-lg border ${b.earned ? '' : 'opacity-40'}`}
                            data-testid={`badge-${b.id}`}>
                            <div className="h-12 w-12 rounded-full mx-auto flex items-center justify-center text-white mb-2"
                              style={{ background: b.earned ? b.color : '#94a3b8' }}>
                              {b.earned ? <Icon size={22} /> : <Lock size={16} />}
                            </div>
                            <p className="text-[11px] font-medium">{b.name}</p>
                            <p className="text-[9px] text-slate-500 mt-0.5 leading-tight">{b.description}</p>
                          </div>
                        );
                      })}
                    </div>
                  </CardContent></Card>

                  {/* Milestones */}
                  <Card><CardContent className="p-5">
                    <p className="text-xs uppercase tracking-wider text-slate-400 mb-3">Milestones</p>
                    <div className="space-y-3">
                      {progress.milestones.map(m => (
                        <div key={m.id} className="p-3 rounded border" data-testid={`milestone-${m.id}`}>
                          <div className="flex justify-between items-center mb-1">
                            <div className="flex items-center gap-2">
                              {m.achieved ? <CheckCircle2 size={16} className="text-emerald-500" /> : <Target size={16} className="text-slate-400" />}
                              <p className="text-sm font-medium">{m.name}</p>
                            </div>
                            <Badge variant={m.achieved ? 'default' : 'outline'} className={m.achieved ? 'bg-emerald-500' : ''}>
                              {m.reward?.label}
                            </Badge>
                          </div>
                          <div className="h-2 bg-slate-100 rounded-full overflow-hidden mt-2">
                            <div className={`h-full ${m.achieved ? 'bg-emerald-500' : 'bg-indigo-500'}`}
                              style={{ width: `${m.progressPercent}%` }} />
                          </div>
                          <p className="text-[10px] text-slate-500 mt-1">
                            {Math.round(m.current)} / {m.threshold} {m.metric}
                          </p>
                        </div>
                      ))}
                    </div>
                  </CardContent></Card>

                  {/* Challenges */}
                  {progress.challenges.length > 0 && (
                    <Card><CardContent className="p-5">
                      <p className="text-xs uppercase tracking-wider text-slate-400 mb-3">Seasonal Challenges</p>
                      <div className="space-y-3">
                        {progress.challenges.map(ch => (
                          <div key={ch.id} className="p-3 rounded border bg-gradient-to-r from-indigo-50 to-purple-50" data-testid={`challenge-${ch.id}`}>
                            <div className="flex justify-between items-start gap-3">
                              <div>
                                <p className="font-medium text-sm">{ch.name}</p>
                                <p className="text-xs text-slate-600 mt-0.5">{ch.description}</p>
                              </div>
                              <Badge className={ch.completed ? 'bg-emerald-500' : 'bg-indigo-500'}>
                                {ch.reward?.label || 'reward'}
                              </Badge>
                            </div>
                            <div className="h-2 bg-white/60 rounded-full overflow-hidden mt-2">
                              <div className={`h-full ${ch.completed ? 'bg-emerald-500' : 'bg-indigo-600'}`}
                                style={{ width: `${ch.progressPercent || 0}%` }} />
                            </div>
                            <p className="text-[10px] text-slate-500 mt-1">
                              {Math.round(ch.current || 0)} / {ch.target} {ch.metric} &middot; ends {(ch.endDate || '').slice(0, 10)}
                            </p>
                          </div>
                        ))}
                      </div>
                    </CardContent></Card>
                  )}
                </div>
              )}
            </div>
          </div>
        </TabsContent>

        <TabsContent value="leaderboard">
          <LeaderboardPanel customers={customers} />
        </TabsContent>

        <TabsContent value="referrals">
          <ReferralsPanel customers={customers} />
        </TabsContent>

        <TabsContent value="challenges">
          <Card><CardContent className="p-5 space-y-4">
            <div className="flex justify-between items-center">
              <div>
                <h3 className="font-semibold">Seasonal Challenges</h3>
                <p className="text-xs text-slate-500">Time-boxed missions that drive engagement and repeat visits.</p>
              </div>
              <Dialog open={addChallengeOpen} onOpenChange={setAddChallengeOpen}>
                <DialogTrigger asChild>
                  <Button data-testid="add-challenge-btn"><Plus size={14} className="mr-1" /> New challenge</Button>
                </DialogTrigger>
                <DialogContent>
                  <DialogHeader><DialogTitle>New seasonal challenge</DialogTitle></DialogHeader>
                  <div className="space-y-3">
                    <div>
                      <label className="text-xs text-slate-500">Name</label>
                      <Input value={challengeForm.name} onChange={e => setChallengeForm(f => ({ ...f, name: e.target.value }))}
                        placeholder="Winter Warmer" data-testid="ch-name" />
                    </div>
                    <div>
                      <label className="text-xs text-slate-500">Description</label>
                      <Textarea rows={2} value={challengeForm.description}
                        onChange={e => setChallengeForm(f => ({ ...f, description: e.target.value }))}
                        placeholder="Visit us 3 times in winter — earn a $20 voucher"
                        data-testid="ch-desc" />
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <label className="text-xs text-slate-500">Metric</label>
                        <Select value={challengeForm.metric} onValueChange={v => setChallengeForm(f => ({ ...f, metric: v }))}>
                          <SelectTrigger data-testid="ch-metric"><SelectValue /></SelectTrigger>
                          <SelectContent>
                            <SelectItem value="visits">Visits</SelectItem>
                            <SelectItem value="spend">Spend ($)</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                      <div>
                        <label className="text-xs text-slate-500">Target</label>
                        <Input type="number" value={challengeForm.target}
                          onChange={e => setChallengeForm(f => ({ ...f, target: parseFloat(e.target.value) || 0 }))}
                          data-testid="ch-target" />
                      </div>
                      <div>
                        <label className="text-xs text-slate-500">Start</label>
                        <Input type="date" value={challengeForm.startDate}
                          onChange={e => setChallengeForm(f => ({ ...f, startDate: e.target.value }))} />
                      </div>
                      <div>
                        <label className="text-xs text-slate-500">End</label>
                        <Input type="date" value={challengeForm.endDate}
                          onChange={e => setChallengeForm(f => ({ ...f, endDate: e.target.value }))} />
                      </div>
                      <div>
                        <label className="text-xs text-slate-500">Reward type</label>
                        <Select value={challengeForm.reward.type}
                          onValueChange={v => setChallengeForm(f => ({ ...f, reward: { ...f.reward, type: v } }))}>
                          <SelectTrigger><SelectValue /></SelectTrigger>
                          <SelectContent>
                            <SelectItem value="voucher">Voucher</SelectItem>
                            <SelectItem value="points">Points</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                      <div>
                        <label className="text-xs text-slate-500">Reward value</label>
                        <Input type="number" value={challengeForm.reward.value}
                          onChange={e => setChallengeForm(f => ({
                            ...f, reward: { ...f.reward, value: parseFloat(e.target.value) || 0, label: `${f.reward.type === 'voucher' ? '$' : ''}${e.target.value}${f.reward.type === 'points' ? ' pts' : ''}` }
                          }))} />
                      </div>
                    </div>
                    <Button className="w-full" onClick={createChallenge} disabled={!challengeForm.name} data-testid="save-ch-btn">
                      Create challenge
                    </Button>
                  </div>
                </DialogContent>
              </Dialog>
            </div>
            {challenges.length === 0 ? (
              <p className="text-center py-8 text-sm text-slate-400">No challenges yet. Create your first one.</p>
            ) : (
              <div className="space-y-2">
                {challenges.map(ch => (
                  <div key={ch.id} className="flex justify-between items-center p-3 border rounded" data-testid={`ch-row-${ch.id}`}>
                    <div>
                      <p className="text-sm font-medium">{ch.name}</p>
                      <p className="text-xs text-slate-500">
                        {ch.metric} \u2265 {ch.target} \u00b7 {(ch.startDate || '').slice(0, 10)} \u2192 {(ch.endDate || '').slice(0, 10)} \u00b7 {ch.reward?.label}
                      </p>
                    </div>
                    <button onClick={() => deleteChallenge(ch.id)} className="text-slate-400 hover:text-rose-500" data-testid={`del-ch-${ch.id}`}>
                      <Trash2 size={14} />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </CardContent></Card>
        </TabsContent>

        <TabsContent value="reports">
          <ReportsPanel />
        </TabsContent>
      </Tabs>
    </div>
  );
}
