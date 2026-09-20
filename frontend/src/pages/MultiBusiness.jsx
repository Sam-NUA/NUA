import React, { useEffect, useState } from 'react';
import { Building2, Plus, DollarSign, Users, Package, Award, ShieldCheck, CreditCard, AlertTriangle, Link2, Pencil, Check, X, Download } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Badge } from '../components/ui/badge';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '../components/ui/dialog';
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from '../components/ui/select';
import { useTheme } from '../contexts/ThemeContext';
import { useAuth } from '../contexts/AuthContext';
import { useBusiness } from '../contexts/BusinessContext';
import { businessAPI } from '../services/api';
import { BUSINESS_TYPE_OPTIONS, VERTICAL_LABELS, getVertical } from '../lib/businessVertical';
import { toast } from 'sonner';

const BLANK_FORM = { name: '', type: 'restaurant', abn: '', address: '', phone: '', email: '', timezone: 'Australia/Sydney', currency: 'AUD', taxRate: 10 };

export default function MultiBusiness() {
  const { theme } = useTheme();
  const { user } = useAuth();
  const { refresh: refreshOwnBusiness } = useBusiness();
  const [businesses, setBusinesses] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState(BLANK_FORM);
  const [saving, setSaving] = useState(false);
  const [summaries, setSummaries] = useState({}); // businessId -> summary
  const [editingSlugFor, setEditingSlugFor] = useState(null); // businessId
  const [editingSlugValue, setEditingSlugValue] = useState('');
  const [savingSlug, setSavingSlug] = useState(false);
  const [savingTypeFor, setSavingTypeFor] = useState(null); // businessId
  const [exportingId, setExportingId] = useState(null);

  const load = () => {
    setLoading(true);
    businessAPI.list().then(r => setBusinesses(r.data || [])).catch(() => toast.error('Failed to load businesses')).finally(() => setLoading(false));
  };
  useEffect(load, []);

  const loadSummary = async (id) => {
    if (summaries[id]) return;
    try {
      const r = await businessAPI.summary(id);
      setSummaries(prev => ({ ...prev, [id]: r.data }));
    } catch { /* summary is a nice-to-have, silently skip on failure */ }
  };
  useEffect(() => { businesses.forEach(b => loadSummary(b.id)); }, [businesses]); // eslint-disable-line

  const createBusiness = async () => {
    if (!form.name.trim()) { toast.error('Business name required'); return; }
    setSaving(true);
    try {
      const r = await businessAPI.create(form);
      toast.success(`${form.name} created`);
      if (r.data?.slugAdjusted) {
        toast.info(`Storefront link uses "${r.data.slug}" — another business already had that name`);
      }
      setShowCreate(false);
      setForm(BLANK_FORM);
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Failed to create business');
    } finally { setSaving(false); }
  };

  const copyStorefrontLink = (b) => {
    const url = `${window.location.origin}/order-online?business=${b.slug || b.id}`;
    navigator.clipboard.writeText(url).then(
      () => toast.success('Storefront link copied'),
      () => toast.error('Could not copy — clipboard unavailable'),
    );
  };

  const startEditSlug = (b) => { setEditingSlugFor(b.id); setEditingSlugValue(b.slug || ''); };
  const cancelEditSlug = () => { setEditingSlugFor(null); setEditingSlugValue(''); };
  const saveSlug = async (b) => {
    if (!editingSlugValue.trim()) { toast.error('Slug cannot be empty'); return; }
    setSavingSlug(true);
    try {
      const r = await businessAPI.update(b.id, { slug: editingSlugValue.trim() });
      if (r.data?.slugAdjusted) {
        toast.info(`That slug was taken — using "${r.data.slug}" instead`);
      } else {
        toast.success('Storefront link updated');
      }
      cancelEditSlug();
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Failed to update slug');
    } finally { setSavingSlug(false); }
  };

  const changeType = async (b, newType) => {
    if (newType === b.type) return;
    setSavingTypeFor(b.id);
    try {
      await businessAPI.update(b.id, { type: newType });
      toast.success(`${b.name} is now ${VERTICAL_LABELS[getVertical(newType)]}`);
      load();
      // If this is the business the logged-in owner is currently acting as,
      // the sidebar's cached vertical is now stale — pull the fresh one so
      // the nav switches without a manual reload.
      if (b.id === user?.businessId) refreshOwnBusiness();
    } catch {
      toast.error('Failed to update business type');
    } finally { setSavingTypeFor(null); }
  };

  const exportBusiness = async (b) => {
    setExportingId(b.id);
    try {
      const r = await businessAPI.exportData(b.id);
      const blob = new Blob([JSON.stringify(r.data, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = `${b.slug || b.id}-export-${new Date().toISOString().slice(0, 10)}.json`;
      a.click();
      URL.revokeObjectURL(url);
      toast.success('Export downloaded');
    } catch {
      toast.error('Export failed');
    } finally { setExportingId(null); }
  };

  if (user?.role !== 'owner') {
    return (
      <div className="flex flex-col items-center justify-center py-24 text-center" data-testid="multi-business-forbidden">
        <ShieldCheck size={40} className="text-gray-300 mb-3" />
        <p className="text-gray-500">Owner access only.</p>
      </div>
    );
  }

  return (
    <div className="space-y-6" data-testid="multi-business-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2" style={{ color: theme.text }}>
            <Building2 size={24} /> Multi-Business
          </h1>
          <p className="text-sm text-gray-500">Every business sharing this deployment — create new ones and manage each venue independently.</p>
        </div>
        <div className="flex gap-2">
          <Button onClick={() => setShowCreate(true)} data-testid="create-business-btn">
            <Plus size={14} className="mr-1.5" /> New Business
          </Button>
        </div>
      </div>

      <Card className="bg-amber-50/50 border-amber-200">
        <CardContent className="p-4 text-sm text-amber-900">
          <p><strong>Legacy ownership needs support review.</strong> Older records without a <code>businessId</code> are never assigned to a venue automatically. An authorised operator must use the dry-run ownership-migration workflow, review its evidence and quarantine report, and record evidence for every manual resolution.</p>
        </CardContent>
      </Card>

      {loading ? (
        <p className="text-sm text-gray-400 text-center py-12">Loading businesses…</p>
      ) : businesses.length === 0 ? (
        <Card><CardContent className="p-12 text-center text-gray-400">
          No businesses yet. Every new deployment starts with a "default" business seeded automatically — this list only shows businesses your account owns.
        </CardContent></Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {businesses.map(b => {
            const s = summaries[b.id];
            return (
              <Card key={b.id} data-testid={`business-card-${b.id}`}>
                <CardHeader className="pb-2">
                  <div className="flex items-start justify-between">
                    <div>
                      <CardTitle className="text-base">{b.name}</CardTitle>
                      <p className="text-xs text-gray-400 mt-0.5 font-mono">{b.id}</p>
                    </div>
                    <Badge variant={b.status === 'active' ? 'default' : 'secondary'} className="capitalize">{b.status}</Badge>
                  </div>
                </CardHeader>
                <CardContent className="space-y-3">
                  <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs text-gray-500">
                    <Select value={b.type || 'restaurant'} disabled={savingTypeFor === b.id} onValueChange={(v) => changeType(b, v)}>
                      <SelectTrigger className="h-6 w-auto min-w-[9rem] text-xs" data-testid={`business-type-select-${b.id}`}><SelectValue /></SelectTrigger>
                      <SelectContent>
                        {BUSINESS_TYPE_OPTIONS.map(o => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}
                      </SelectContent>
                    </Select>
                    <Badge variant="outline" className="text-[10px]">{VERTICAL_LABELS[getVertical(b.type)]}</Badge>
                    {b.email && <span>{b.email}</span>}
                    {b.phone && <span>{b.phone}</span>}
                    <span>{b.currency} · {b.taxRate}% tax</span>
                  </div>
                  {editingSlugFor === b.id ? (
                    <div className="flex items-center gap-1.5" data-testid={`edit-slug-row-${b.id}`}>
                      <Input
                        value={editingSlugValue}
                        onChange={e => setEditingSlugValue(e.target.value)}
                        className="h-7 text-xs font-mono"
                        placeholder="storefront-slug"
                        data-testid={`edit-slug-input-${b.id}`}
                      />
                      <Button size="icon" variant="ghost" className="h-7 w-7" disabled={savingSlug} onClick={() => saveSlug(b)} data-testid={`save-slug-${b.id}`}>
                        <Check size={14} />
                      </Button>
                      <Button size="icon" variant="ghost" className="h-7 w-7" disabled={savingSlug} onClick={cancelEditSlug}>
                        <X size={14} />
                      </Button>
                    </div>
                  ) : (
                    <div className="flex items-center gap-3">
                      <button onClick={() => copyStorefrontLink(b)} className="flex items-center gap-1.5 text-xs text-indigo-600 hover:text-indigo-800" data-testid={`copy-storefront-link-${b.id}`}>
                        <Link2 size={12} /> Copy online-ordering link ({b.slug || b.id})
                      </button>
                      <button onClick={() => startEditSlug(b)} className="text-gray-400 hover:text-gray-600" data-testid={`edit-slug-btn-${b.id}`}>
                        <Pencil size={12} />
                      </button>
                    </div>
                  )}
                  {s ? (
                    <div className="grid grid-cols-4 gap-2 pt-2 border-t text-center">
                      <div>
                        <DollarSign size={14} className="mx-auto text-emerald-600" />
                        <p className="text-sm font-bold">${s.totalRevenue?.toFixed(0) ?? 0}</p>
                        <p className="text-[10px] text-gray-400">Revenue</p>
                      </div>
                      <div>
                        <Package size={14} className="mx-auto text-indigo-600" />
                        <p className="text-sm font-bold">{s.totalTransactions ?? 0}</p>
                        <p className="text-[10px] text-gray-400">Sales</p>
                      </div>
                      <div>
                        <Users size={14} className="mx-auto text-amber-600" />
                        <p className="text-sm font-bold">{s.totalCustomers ?? 0}</p>
                        <p className="text-[10px] text-gray-400">Customers</p>
                      </div>
                      <div>
                        <Award size={14} className="mx-auto text-rose-600" />
                        <p className="text-sm font-bold">{s.totalStaff ?? 0}</p>
                        <p className="text-[10px] text-gray-400">Staff</p>
                      </div>
                    </div>
                  ) : (
                    <p className="text-xs text-gray-300 pt-2 border-t">Loading summary…</p>
                  )}
                  {s && ((s.onlineOrdersPaid || 0) + (s.onlineOrdersRefunded || 0) + (s.onlineOrdersRefundFailed || 0) > 0) && (
                    <div className="flex items-center gap-3 pt-2 border-t text-xs" data-testid={`business-payments-${b.id}`}>
                      <span className="flex items-center gap-1 text-gray-500"><CreditCard size={12} /> Online payments</span>
                      <span className="text-emerald-600 font-medium">{s.onlineOrdersPaid} paid</span>
                      {s.onlineOrdersRefunded > 0 && <span className="text-gray-500">{s.onlineOrdersRefunded} refunded</span>}
                      {s.onlineOrdersRefundFailed > 0 && (
                        <span className="flex items-center gap-1 text-red-600 font-medium">
                          <AlertTriangle size={12} /> {s.onlineOrdersRefundFailed} refund failed
                        </span>
                      )}
                    </div>
                  )}
                  <button onClick={() => exportBusiness(b)} disabled={exportingId === b.id}
                    className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-gray-700 pt-2 border-t w-full"
                    data-testid={`export-business-${b.id}`}>
                    <Download size={12} /> {exportingId === b.id ? 'Exporting…' : 'Export all data (JSON)'}
                  </button>
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}

      <Dialog open={showCreate} onOpenChange={setShowCreate}>
        <DialogContent data-testid="create-business-dialog">
          <DialogHeader><DialogTitle>New Business</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <Input placeholder="Business name *" value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} data-testid="business-name-input" />
            <div className="grid grid-cols-2 gap-3">
              <Select value={form.type} onValueChange={v => setForm({ ...form, type: v })}>
                <SelectTrigger data-testid="business-type-input"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {BUSINESS_TYPE_OPTIONS.map(o => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}
                </SelectContent>
              </Select>
              <Input placeholder="ABN" value={form.abn} onChange={e => setForm({ ...form, abn: e.target.value })} />
            </div>
            <Input placeholder="Address" value={form.address} onChange={e => setForm({ ...form, address: e.target.value })} />
            <div className="grid grid-cols-2 gap-3">
              <Input placeholder="Phone" value={form.phone} onChange={e => setForm({ ...form, phone: e.target.value })} />
              <Input placeholder="Email" value={form.email} onChange={e => setForm({ ...form, email: e.target.value })} />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <Input placeholder="Currency" value={form.currency} onChange={e => setForm({ ...form, currency: e.target.value })} />
              <Input type="number" placeholder="Tax rate %" value={form.taxRate} onChange={e => setForm({ ...form, taxRate: parseFloat(e.target.value) || 0 })} />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowCreate(false)}>Cancel</Button>
            <Button onClick={createBusiness} disabled={saving} data-testid="save-business-btn">{saving ? 'Creating…' : 'Create Business'}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
