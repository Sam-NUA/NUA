import React, { useEffect, useState, useMemo } from 'react';
import { Card, CardContent } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Badge } from '../components/ui/badge';
import { Textarea } from '../components/ui/textarea';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '../components/ui/dialog';
import { useTheme } from '../contexts/ThemeContext';
import { finalizeAPI, customersAPI } from '../services/api';
import { toast } from 'sonner';
import { QRCodeSVG } from 'qrcode.react';
import {
  Gift, Plus, Copy, Search, ShieldCheck, ShieldAlert, Sparkles,
  BarChart3, Users, TrendingUp, X, RotateCcw, Layers,
} from 'lucide-react';
import { DialogService } from '../platform';

const emptyForm = {
  label: '', description: '',
  sourceType: 'manual',
  valueType: 'amount', value: 10,
  usageType: 'one_time',
  maxRedemptions: 1,
  partialRedeemable: false,
  expiresAt: '',
  customerId: '',
  bulkCount: 1,
  rules: { activeDays: [], minSpend: 0, eligibleCategories: [], happyHourOnly: false, firstVisitOnly: false, clubMembersOnly: false },
};

const StatusBadge = ({ v }) => {
  const map = {
    active: { c: 'bg-emerald-100 text-emerald-700', l: 'Active' },
    partial: { c: 'bg-blue-100 text-blue-700', l: 'Partial' },
    redeemed: { c: 'bg-gray-200 text-gray-700', l: 'Redeemed' },
    expired: { c: 'bg-amber-100 text-amber-700', l: 'Expired' },
    revoked: { c: 'bg-red-100 text-red-700', l: 'Revoked' },
  };
  const cfg = map[v.status] || map.active;
  return <Badge className={`${cfg.c} border-0`} data-testid={`voucher-status-${v.id}`}>{cfg.l}</Badge>;
};

export default function Vouchers() {
  const { theme } = useTheme();
  const [tab, setTab] = useState('list');
  const [rows, setRows] = useState([]);
  const [filter, setFilter] = useState({ status: '', sourceType: '', search: '' });
  const [analytics, setAnalytics] = useState(null);
  const [openDialog, setOpenDialog] = useState(false);
  const [form, setForm] = useState(emptyForm);
  const [detail, setDetail] = useState(null);
  const [aiGoal, setAiGoal] = useState('');
  const [aiBusy, setAiBusy] = useState(false);
  const [aiResult, setAiResult] = useState(null);
  const [customers, setCustomers] = useState([]);

  const load = async () => {
    try {
      const params = {};
      if (filter.status) params.status = filter.status;
      if (filter.sourceType) params.source_type = filter.sourceType;
      const r = await finalizeAPI.listVouchers(params);
      setRows(r.data || []);
    } catch { toast.error('Could not load vouchers'); }
  };
  const loadAnalytics = async () => {
    try { const r = await finalizeAPI.promoAnalytics(30); setAnalytics(r.data); } catch { /* silent */ }
  };
  const loadCustomers = async () => {
    try {
      const r = await customersAPI.getAll();
      setCustomers(r.data || []);
    } catch { /* silent */ }
  };
  useEffect(() => { load(); loadAnalytics(); loadCustomers(); }, [filter.status, filter.sourceType]);

  const filtered = useMemo(() => {
    if (!filter.search) return rows;
    const q = filter.search.toLowerCase();
    return rows.filter(v => (v.code || '').toLowerCase().includes(q) || (v.label || '').toLowerCase().includes(q) || (v.customerName || '').toLowerCase().includes(q));
  }, [rows, filter.search]);

  const create = async () => {
    if (!form.label.trim()) return toast.error('Label required');
    const body = {
      label: form.label, description: form.description || undefined,
      sourceType: form.sourceType,
      valueType: form.valueType, value: parseFloat(form.value) || 0,
      usageType: form.usageType,
      maxRedemptions: form.usageType === 'unlimited' ? null : parseInt(form.maxRedemptions) || 1,
      partialRedeemable: form.partialRedeemable,
      customerId: form.customerId || undefined,
      expiresAt: form.expiresAt ? new Date(form.expiresAt).toISOString() : undefined,
      rules: form.rules,
    };
    try {
      if (parseInt(form.bulkCount) > 1) {
        const r = await finalizeAPI.bulkVoucher({ ...body, count: parseInt(form.bulkCount) });
        toast.success(`Issued ${r.data.issued} vouchers`);
      } else {
        await finalizeAPI.issueVoucher(body);
        toast.success('Voucher issued');
      }
      setOpenDialog(false); setForm(emptyForm); load(); loadAnalytics();
    } catch (e) { toast.error(e?.response?.data?.detail || 'Failed'); }
  };

  const revoke = async (v) => {
    const reason = await DialogService.prompt('Reason for revoking?', 'Owner revoked');
    if (!reason) return;
    try {
      await finalizeAPI.revokeVoucher(v.id, reason);
      toast.success('Voucher revoked'); load();
    } catch (e) { toast.error(e?.response?.data?.detail || 'Failed'); }
  };

  const copyCode = async (v) => {
    try { await navigator.clipboard.writeText(v.code); toast.success('Code copied'); }
    catch { /* silent */ }
  };

  const runAi = async () => {
    if (!aiGoal.trim()) return;
    setAiBusy(true);
    try {
      const r = await finalizeAPI.aiPromotionGoal(aiGoal);
      setAiResult(r.data);
    } catch (e) { toast.error(e?.response?.data?.detail || 'AI failed'); }
    finally { setAiBusy(false); }
  };

  const applyAiResult = () => {
    if (!aiResult) return;
    const v = aiResult.voucherTemplate || {};
    setForm({
      ...emptyForm,
      label: aiResult.name || aiResult.offerHeadline || '',
      description: aiResult.offerBody || '',
      sourceType: 'promotion',
      valueType: v.valueType || 'amount',
      value: v.value || 10,
      usageType: v.usageType || 'one_time',
      partialRedeemable: !!v.partialRedeemable,
      rules: {
        activeDays: aiResult.rules?.activeDays || [],
        startTime: aiResult.rules?.startTime || '',
        endTime: aiResult.rules?.endTime || '',
        minSpend: aiResult.rules?.minSpend || 0,
        eligibleCategories: aiResult.rules?.eligibleCategories || [],
        happyHourOnly: false, firstVisitOnly: false, clubMembersOnly: false,
      },
    });
    setTab('list');
    setOpenDialog(true);
  };

  return (
    <div className="space-y-6" data-testid="vouchers-page">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2" style={{ color: theme.text }}>
            <Gift style={{ color: theme.primary }} /> Universal Vouchers
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            Every offer, gift, refund, referral & birthday reward — one engine, one audit trail, one QR.
          </p>
        </div>
        <Button onClick={() => { setForm(emptyForm); setOpenDialog(true); }} style={{ background: theme.primary }} className="text-white" data-testid="new-voucher-btn">
          <Plus size={14} className="mr-1.5" /> Issue voucher
        </Button>
      </div>

      {/* Analytics strip */}
      {analytics && (
        <div className="grid grid-cols-2 lg:grid-cols-5 gap-3" data-testid="analytics-strip">
          {[
            { l: 'Issued (30d)', v: analytics.issued, icon: Layers, c: theme.primary },
            { l: 'Redeemed', v: analytics.redeemed, icon: ShieldCheck, c: '#10b981' },
            { l: 'Redemption rate', v: `${analytics.redemptionRate}%`, icon: TrendingUp, c: theme.accent },
            { l: 'Face value', v: `$${(analytics.faceValueIssued || 0).toFixed(0)}`, icon: BarChart3, c: '#3b82f6' },
            { l: 'Revenue', v: `$${(analytics.revenueGenerated || 0).toFixed(0)}`, icon: Users, c: '#a855f7' },
          ].map((s, i) => {
            const Icon = s.icon;
            return (
              <Card key={i} className="border-0 shadow-sm">
                <CardContent className="p-3 flex items-center gap-3">
                  <div className="w-9 h-9 rounded-lg flex items-center justify-center" style={{ background: `${s.c}15` }}>
                    <Icon size={16} style={{ color: s.c }} />
                  </div>
                  <div>
                    <p className="text-lg font-bold" style={{ color: theme.text }}>{s.v}</p>
                    <p className="text-[10px] text-gray-500 uppercase tracking-widest">{s.l}</p>
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="list" data-testid="tab-voucher-list">Vouchers</TabsTrigger>
          <TabsTrigger value="ai" data-testid="tab-ai-builder">
            <Sparkles size={12} className="mr-1" /> AI Promotion Builder
          </TabsTrigger>
        </TabsList>

        <TabsContent value="list" className="mt-4 space-y-3">
          <div className="flex flex-wrap gap-2">
            <div className="relative flex-1 min-w-[220px]">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
              <Input value={filter.search} onChange={e => setFilter({ ...filter, search: e.target.value })}
                placeholder="Search code, label, customer…" className="pl-9" data-testid="voucher-search" />
            </div>
            <Select value={filter.status || 'all'} onValueChange={v => setFilter({ ...filter, status: v === 'all' ? '' : v })}>
              <SelectTrigger className="w-40" data-testid="voucher-filter-status"><SelectValue placeholder="Status" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All statuses</SelectItem>
                <SelectItem value="active">Active</SelectItem>
                <SelectItem value="partial">Partial</SelectItem>
                <SelectItem value="redeemed">Redeemed</SelectItem>
                <SelectItem value="expired">Expired</SelectItem>
                <SelectItem value="revoked">Revoked</SelectItem>
              </SelectContent>
            </Select>
            <Select value={filter.sourceType || 'all'} onValueChange={v => setFilter({ ...filter, sourceType: v === 'all' ? '' : v })}>
              <SelectTrigger className="w-44" data-testid="voucher-filter-source"><SelectValue placeholder="Source" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All sources</SelectItem>
                {['promotion','refund','gift_card','referral','birthday','anniversary','staff','corporate','event','manual'].map(s => (
                  <SelectItem key={s} value={s}>{s}</SelectItem>
                ))}
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
                      <th className="p-2 text-left">Label</th>
                      <th className="p-2 text-left">Source</th>
                      <th className="p-2 text-right">Value</th>
                      <th className="p-2 text-right">Redemptions</th>
                      <th className="p-2 text-left">Customer</th>
                      <th className="p-2 text-left">Expires</th>
                      <th className="p-2 text-left">Status</th>
                      <th className="p-2 text-right"></th>
                    </tr>
                  </thead>
                  <tbody data-testid="voucher-rows">
                    {filtered.map(v => (
                      <tr key={v.id} className="border-t hover:bg-gray-50" data-testid={`voucher-row-${v.id}`}>
                        <td className="p-2">
                          <button onClick={() => setDetail(v)} className="font-mono text-xs font-semibold hover:underline" data-testid={`voucher-open-${v.id}`}>
                            {v.code}
                          </button>
                        </td>
                        <td className="p-2">
                          <p className="font-medium truncate max-w-[220px]" title={v.label}>{v.label}</p>
                        </td>
                        <td className="p-2 text-xs text-gray-500 capitalize">{(v.sourceType || 'manual').replace('_', ' ')}</td>
                        <td className="p-2 text-right font-mono">
                          {v.valueType === 'percentage' ? `${v.value}%` : v.valueType === 'free_item' ? 'Free item' : `$${(v.residualValue || v.value || 0).toFixed(2)}`}
                          {v.partialRedeemable && v.status === 'partial' && (
                            <span className="ml-1 text-[10px] text-gray-400">of ${v.faceValue?.toFixed(2)}</span>
                          )}
                        </td>
                        <td className="p-2 text-right text-xs">
                          {v.redemptionCount || 0}
                          {v.maxRedemptions ? <span className="text-gray-400"> / {v.maxRedemptions}</span> : <span className="text-gray-400"> / ∞</span>}
                        </td>
                        <td className="p-2 text-xs">
                          {v.customerName ? <span className="text-gray-700">{v.customerName}</span> : <span className="text-gray-400">Unassigned</span>}
                        </td>
                        <td className="p-2 text-xs text-gray-500">{v.expiresAt ? v.expiresAt.slice(0, 10) : '—'}</td>
                        <td className="p-2"><StatusBadge v={v} /></td>
                        <td className="p-2 text-right whitespace-nowrap">
                          <Button variant="ghost" size="sm" onClick={() => copyCode(v)} data-testid={`voucher-copy-${v.id}`}><Copy size={12} /></Button>
                          {['active', 'partial'].includes(v.status) && (
                            <Button variant="ghost" size="sm" onClick={() => revoke(v)} className="text-red-500" data-testid={`voucher-revoke-${v.id}`}>
                              <X size={12} />
                            </Button>
                          )}
                        </td>
                      </tr>
                    ))}
                    {filtered.length === 0 && (
                      <tr><td colSpan={9} className="p-8 text-center text-sm text-gray-400">No vouchers yet — issue your first one.</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="ai" className="mt-4 space-y-3">
          <Card className="border-2 border-dashed border-purple-200 bg-purple-50/30">
            <CardContent className="p-5 space-y-3">
              <div className="flex items-center gap-2">
                <Sparkles size={16} className="text-purple-600" />
                <h3 className="font-semibold text-purple-800">AI Promotion Builder</h3>
                <Badge className="bg-purple-100 text-purple-700 border-0 text-[10px]">Goal → Campaign</Badge>
              </div>
              <p className="text-xs text-purple-700">
                Type a business goal — NUA will compose the offer, voucher, SMS + email copy, and target rules.
              </p>
              <div className="flex gap-2">
                <Input value={aiGoal} onChange={e => setAiGoal(e.target.value)}
                  placeholder="e.g. Bring back inactive customers · Boost Tuesday lunch · Fill empty tables tonight"
                  data-testid="ai-goal-input" />
                <Button onClick={runAi} disabled={aiBusy} style={{ background: theme.primary }} className="text-white" data-testid="ai-generate-campaign">
                  {aiBusy ? 'Thinking…' : 'Generate campaign'}
                </Button>
              </div>
              {aiResult && (
                <div className="mt-2 rounded-lg bg-white border p-4 space-y-3" data-testid="ai-result">
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-xs uppercase tracking-widest text-gray-500">Campaign</p>
                      <p className="font-bold text-lg">{aiResult.name}</p>
                    </div>
                    <Badge className="bg-purple-100 text-purple-700 border-0 text-[10px]">{aiResult.source}</Badge>
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
                    <div>
                      <p className="text-gray-500 uppercase tracking-widest text-[10px]">Voucher</p>
                      <p className="font-mono">{aiResult.voucherTemplate?.valueType === 'amount' ? `$${aiResult.voucherTemplate?.value}` : `${aiResult.voucherTemplate?.value}%`} · {aiResult.voucherTemplate?.usageType}</p>
                    </div>
                    <div>
                      <p className="text-gray-500 uppercase tracking-widest text-[10px]">Est. ROI</p>
                      <p className="font-mono">{aiResult.estimatedROI}</p>
                    </div>
                    <div className="md:col-span-2">
                      <p className="text-gray-500 uppercase tracking-widest text-[10px]">SMS</p>
                      <p className="rounded bg-gray-50 p-2 font-mono text-[11px]">{aiResult.smsCopy}</p>
                    </div>
                    {aiResult.emailBody && (
                      <div className="md:col-span-2">
                        <p className="text-gray-500 uppercase tracking-widest text-[10px]">Email · {aiResult.emailSubject}</p>
                        <p className="rounded bg-gray-50 p-2 text-[11px] whitespace-pre-wrap">{aiResult.emailBody}</p>
                      </div>
                    )}
                  </div>
                  <Button onClick={applyAiResult} style={{ background: theme.primary }} className="text-white" data-testid="ai-apply-btn">
                    <Plus size={14} className="mr-1.5" /> Turn into voucher
                  </Button>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      {/* Create dialog */}
      <Dialog open={openDialog} onOpenChange={setOpenDialog}>
        <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto" data-testid="voucher-create-dialog">
          <DialogHeader><DialogTitle>Issue voucher</DialogTitle></DialogHeader>
          <div className="space-y-3 py-2">
            <Input placeholder="Label (e.g. 'Family Feast', 'Refund voucher $10')"
              value={form.label} onChange={e => setForm({ ...form, label: e.target.value })}
              data-testid="voucher-form-label" />
            <Textarea rows={2} placeholder="Description (optional)"
              value={form.description} onChange={e => setForm({ ...form, description: e.target.value })} />

            <div className="grid grid-cols-3 gap-2">
              <Select value={form.sourceType} onValueChange={v => setForm({ ...form, sourceType: v })}>
                <SelectTrigger data-testid="voucher-form-source"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {['manual','promotion','refund','gift_card','referral','birthday','anniversary','staff','corporate','event'].map(x => (
                    <SelectItem key={x} value={x}>{x}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Select value={form.valueType} onValueChange={v => setForm({ ...form, valueType: v })}>
                <SelectTrigger data-testid="voucher-form-valuetype"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="amount">Amount ($)</SelectItem>
                  <SelectItem value="percentage">Percentage (%)</SelectItem>
                  <SelectItem value="free_item">Free item</SelectItem>
                </SelectContent>
              </Select>
              <Input type="number" step="0.01" placeholder="Value"
                value={form.value} onChange={e => setForm({ ...form, value: e.target.value })}
                data-testid="voucher-form-value" />
            </div>

            <div className="grid grid-cols-3 gap-2">
              <Select value={form.usageType} onValueChange={v => setForm({ ...form, usageType: v })}>
                <SelectTrigger data-testid="voucher-form-usage"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="one_time">One-time</SelectItem>
                  <SelectItem value="multi_use">Multi-use</SelectItem>
                  <SelectItem value="unlimited">Unlimited</SelectItem>
                </SelectContent>
              </Select>
              {form.usageType === 'multi_use' && (
                <Input type="number" min="2" placeholder="Max redemptions"
                  value={form.maxRedemptions} onChange={e => setForm({ ...form, maxRedemptions: e.target.value })}
                  data-testid="voucher-form-max" />
              )}
              <Input type="datetime-local" placeholder="Expires"
                value={form.expiresAt} onChange={e => setForm({ ...form, expiresAt: e.target.value })}
                data-testid="voucher-form-expires" />
            </div>

            <div className="flex items-center gap-4 flex-wrap">
              <label className="flex items-center gap-1.5 text-sm">
                <input type="checkbox" checked={form.partialRedeemable}
                  onChange={e => setForm({ ...form, partialRedeemable: e.target.checked })}
                  data-testid="voucher-form-partial" />
                Partial redemption (retains residual)
              </label>
              <label className="flex items-center gap-1.5 text-sm">
                <input type="checkbox" checked={form.rules.firstVisitOnly}
                  onChange={e => setForm({ ...form, rules: { ...form.rules, firstVisitOnly: e.target.checked } })} />
                First visit only
              </label>
              <label className="flex items-center gap-1.5 text-sm">
                <input type="checkbox" checked={form.rules.clubMembersOnly}
                  onChange={e => setForm({ ...form, rules: { ...form.rules, clubMembersOnly: e.target.checked } })} />
                Club members only
              </label>
              <label className="flex items-center gap-1.5 text-sm">
                <input type="checkbox" checked={form.rules.happyHourOnly}
                  onChange={e => setForm({ ...form, rules: { ...form.rules, happyHourOnly: e.target.checked } })} />
                Happy Hour only
              </label>
            </div>

            <div className="grid grid-cols-2 gap-2">
              <Select value={form.customerId || 'none'} onValueChange={v => setForm({ ...form, customerId: v === 'none' ? '' : v })}>
                <SelectTrigger data-testid="voucher-form-customer"><SelectValue placeholder="Assign to customer" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">Unassigned</SelectItem>
                  {customers.map(c => (<SelectItem key={c.id} value={c.id}>{c.name}</SelectItem>))}
                </SelectContent>
              </Select>
              <Input type="number" min="1" placeholder="Bulk count (staff/corporate)"
                value={form.bulkCount} onChange={e => setForm({ ...form, bulkCount: e.target.value })}
                data-testid="voucher-form-bulk" />
            </div>

            <div>
              <label className="text-[10px] uppercase tracking-widest font-semibold text-gray-500 mb-1 block">Active days</label>
              <div className="flex flex-wrap gap-1.5">
                {['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'].map(d => {
                  const on = form.rules.activeDays.includes(d);
                  return (
                    <button key={d} type="button"
                      onClick={() => setForm({ ...form, rules: {
                        ...form.rules,
                        activeDays: on ? form.rules.activeDays.filter(x => x !== d) : [...form.rules.activeDays, d],
                      } })}
                      className={`px-2.5 py-1 text-xs rounded-full font-medium ${on ? 'bg-gray-900 text-white' : 'bg-gray-100 text-gray-600'}`}
                      data-testid={`voucher-day-${d.toLowerCase()}`}>{d.slice(0, 3)}</button>
                  );
                })}
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpenDialog(false)}>Cancel</Button>
            <Button onClick={create} style={{ background: theme.primary }} className="text-white" data-testid="voucher-form-save">
              Issue voucher
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Detail dialog — QR + audit trail */}
      <Dialog open={!!detail} onOpenChange={(o) => { if (!o) setDetail(null); }}>
        <DialogContent className="max-w-lg max-h-[85vh] overflow-y-auto" data-testid="voucher-detail-dialog">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Gift size={16} /> {detail?.code}
            </DialogTitle>
          </DialogHeader>
          {detail && (
            <div className="space-y-3">
              <div className="bg-gradient-to-br from-slate-900 to-purple-700 text-white rounded-2xl p-4 flex items-center gap-4">
                <div className="bg-white rounded-lg p-2">
                  <QRCodeSVG value={detail.qrPayload || detail.code} size={110} level="M" data-testid="voucher-qr" />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-[10px] uppercase tracking-widest text-white/60">{detail.sourceType}</p>
                  <p className="font-bold text-lg leading-tight truncate">{detail.label}</p>
                  <p className="text-sm mt-1">
                    {detail.valueType === 'amount' && <>${(detail.residualValue || detail.value || 0).toFixed(2)}</>}
                    {detail.valueType === 'percentage' && <>{detail.value}% off</>}
                    {detail.valueType === 'free_item' && <>Free item</>}
                    {detail.partialRedeemable && detail.status === 'partial' && (
                      <span className="text-white/70 text-xs ml-1">of ${detail.faceValue?.toFixed(2)}</span>
                    )}
                  </p>
                  <p className="text-[10px] font-mono mt-1 opacity-70">{detail.code}</p>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-2 text-xs">
                <div><span className="text-gray-500">Usage:</span> <strong>{detail.usageType}</strong></div>
                <div><span className="text-gray-500">Redemptions:</span> <strong>{detail.redemptionCount || 0}{detail.maxRedemptions ? ` / ${detail.maxRedemptions}` : ' / ∞'}</strong></div>
                <div><span className="text-gray-500">Issued:</span> {(detail.issuedAt || '').slice(0, 16)}</div>
                <div><span className="text-gray-500">Expires:</span> {detail.expiresAt ? detail.expiresAt.slice(0, 16) : '—'}</div>
                {detail.customerName && <div className="col-span-2"><span className="text-gray-500">Customer:</span> <strong>{detail.customerName}</strong></div>}
              </div>

              <div>
                <p className="text-[10px] uppercase tracking-widest font-semibold text-gray-500 mb-1">Redemption audit ({(detail.redemptions || []).length})</p>
                <div className="rounded border divide-y max-h-40 overflow-y-auto" data-testid="voucher-audit">
                  {(detail.redemptions || []).length === 0 ? (
                    <p className="p-3 text-xs text-gray-400 italic">No redemptions yet.</p>
                  ) : detail.redemptions.map((r, i) => (
                    <div key={r.id || i} className="p-2 text-xs" data-testid={`voucher-redemption-${i}`}>
                      <div className="flex justify-between">
                        <span>${(r.amount || 0).toFixed(2)} · {r.staffName || '—'}</span>
                        <span className="text-gray-500">{(r.at || '').slice(0, 16)}</span>
                      </div>
                      <p className="text-[10px] text-gray-500">
                        Terminal {r.terminalId || '—'} · Txn {r.transactionId || '—'} · Loc {r.locationId || '—'}
                      </p>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setDetail(null)}>Close</Button>
            {detail && ['active', 'partial'].includes(detail.status) && (
              <Button variant="outline" onClick={() => { revoke(detail); setDetail(null); }} className="text-red-600" data-testid="voucher-detail-revoke">
                <RotateCcw size={14} className="mr-1" /> Revoke
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
