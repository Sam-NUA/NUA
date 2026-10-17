import React, { useEffect, useMemo, useState } from 'react';
import { Card, CardContent } from '../../components/ui/card';
import { Badge } from '../../components/ui/badge';
import { Button } from '../../components/ui/button';
import { Input } from '../../components/ui/input';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '../../components/ui/dialog';
import { v25API, v26API, customersAPI } from '../../services/api';
import { useTheme } from '../../contexts/ThemeContext';
import { useToast } from '../../hooks/use-toast';
import { Star, Plus, Pencil, Trash2, Users, Pause, Play, X, Check, UserPlus, Tag } from 'lucide-react';
import { DialogService } from '../../platform';

/**
 * Subscription Memberships console — owners can:
 *   • Create / Edit / Delete plans (rich perks list + monthly + annual price + T&Cs)
 *   • Enroll a customer into a plan
 *   • Edit a member: switch plan, pause / resume / cancel
 *
 * Backend wiring:
 *   GET    /api/v25/subscriptions/plans          → list_sub_plans
 *   POST   /api/v25/subscriptions/plans          → add_sub_plan        (owner)
 *   PATCH  /api/v26/subscriptions/plans/:id      → update_sub_plan     (owner)
 *   DELETE /api/v26/subscriptions/plans/:id      → delete_sub_plan     (owner)
 *   POST   /api/v25/subscriptions/enroll         → enroll a customer
 *   GET    /api/v25/subscriptions/members        → list_sub_members
 *   PATCH  /api/v25/subscriptions/members/:id    → switch plan / pause / resume (owner)
 *   DELETE /api/v25/subscriptions/members/:id    → soft-cancel              (owner)
 */
const STATUS_STYLE = {
  active:    'bg-emerald-100 text-emerald-700',
  paused:    'bg-amber-100 text-amber-700',
  cancelled: 'bg-gray-200 text-gray-600',
};

const emptyPlanForm = {
  name: '', priceMonthly: '', priceAnnual: '',
  perks: '', termsAndConditions: '', trialDays: '0', active: true,
};

export default function Subscriptions() {
  const { theme } = useTheme();
  const { toast } = useToast();
  const [plans, setPlans] = useState([]);
  const [members, setMembers] = useState([]);
  const [customers, setCustomers] = useState([]);
  const [busy, setBusy] = useState(false);

  const [planDialog, setPlanDialog] = useState(false);
  const [editingPlan, setEditingPlan] = useState(null);     // null = new, otherwise existing plan
  const [planForm, setPlanForm] = useState({ ...emptyPlanForm });

  const [enrollDialog, setEnrollDialog] = useState(false);
  const [enrollForm, setEnrollForm] = useState({ customerId: '', planId: '' });

  const [memberDialog, setMemberDialog] = useState(null);   // the member being edited
  const [memberForm, setMemberForm] = useState({ planId: '', status: 'active' });

  const load = async () => {
    setBusy(true);
    try {
      const [p, m, c] = await Promise.all([
        v25API.subPlans(),
        v25API.subMembers(),
        customersAPI.getAll(),
      ]);
      setPlans(p.data || []);
      setMembers(m.data || []);
      setCustomers(c.data || []);
    } catch (e) {
      toast({ title: 'Failed to load', description: e?.response?.data?.detail, variant: 'destructive' });
    } finally { setBusy(false); }
  };
  useEffect(() => { load(); }, []);

  const customersById = useMemo(() => {
    const m = {}; (customers || []).forEach(c => { m[c.id] = c; }); return m;
  }, [customers]);
  const plansById = useMemo(() => {
    const m = {}; (plans || []).forEach(p => { m[p.id] = p; }); return m;
  }, [plans]);

  const openNewPlan = () => {
    setEditingPlan(null);
    setPlanForm({ ...emptyPlanForm });
    setPlanDialog(true);
  };
  const openEditPlan = (plan) => {
    setEditingPlan(plan);
    setPlanForm({
      name: plan.name || '',
      priceMonthly: plan.priceMonthly?.toString() || '',
      priceAnnual: plan.priceAnnual?.toString() || '',
      perks: (plan.perks || []).join('\n'),
      termsAndConditions: plan.termsAndConditions || '',
      trialDays: plan.trialDays?.toString() || '0',
      active: plan.active !== false,
    });
    setPlanDialog(true);
  };
  const savePlan = async () => {
    const body = {
      name: planForm.name.trim(),
      priceMonthly: parseFloat(planForm.priceMonthly || '0'),
      priceAnnual: parseFloat(planForm.priceAnnual || '0'),
      perks: planForm.perks.split('\n').map(s => s.trim()).filter(Boolean),
      termsAndConditions: planForm.termsAndConditions,
      trialDays: parseInt(planForm.trialDays || '0', 10),
      active: !!planForm.active,
    };
    if (!body.name) return toast({ title: 'Plan name is required', variant: 'destructive' });
    if (body.priceMonthly < 0) return toast({ title: 'Monthly price must be ≥ 0', variant: 'destructive' });
    setBusy(true);
    try {
      if (editingPlan) {
        await v26API.updateSubPlan(editingPlan.id, body);
        toast({ title: 'Plan updated' });
      } else {
        await v25API.addSubPlan(body);
        toast({ title: 'Plan created' });
      }
      setPlanDialog(false);
      load();
    } catch (e) {
      toast({ title: 'Save failed', description: e?.response?.data?.detail, variant: 'destructive' });
    } finally { setBusy(false); }
  };
  const deletePlan = async (plan) => {
    const members_on_plan = members.filter(m => m.planId === plan.id && m.status === 'active');
    if (members_on_plan.length > 0) {
      const proceed = await DialogService.confirm(`${members_on_plan.length} active member(s) are on this plan. Delete anyway?`);
      if (!proceed) return;
    } else {
      if (!await DialogService.confirm(`Delete plan "${plan.name}"?`)) return;
    }
    setBusy(true);
    try {
      await v26API.deleteSubPlan(plan.id);
      toast({ title: 'Plan deleted' });
      load();
    } catch (e) {
      toast({ title: 'Delete failed', description: e?.response?.data?.detail, variant: 'destructive' });
    } finally { setBusy(false); }
  };

  const openEnroll = () => {
    setEnrollForm({ customerId: '', planId: plans[0]?.id || '' });
    setEnrollDialog(true);
  };
  const submitEnroll = async () => {
    if (!enrollForm.customerId || !enrollForm.planId) {
      return toast({ title: 'Pick a customer and a plan', variant: 'destructive' });
    }
    setBusy(true);
    try {
      await v25API.enrollSub(enrollForm.customerId, enrollForm.planId);
      toast({ title: 'Customer enrolled' });
      setEnrollDialog(false);
      load();
    } catch (e) {
      toast({ title: 'Enrol failed', description: e?.response?.data?.detail, variant: 'destructive' });
    } finally { setBusy(false); }
  };

  const openMember = (m) => {
    setMemberDialog(m);
    setMemberForm({ planId: m.planId, status: m.status || 'active' });
  };
  const saveMember = async () => {
    setBusy(true);
    try {
      await v25API.updateSubMember(memberDialog.id, {
        planId: memberForm.planId,
        status: memberForm.status,
      });
      toast({ title: 'Membership updated' });
      setMemberDialog(null);
      load();
    } catch (e) {
      toast({ title: 'Update failed', description: e?.response?.data?.detail, variant: 'destructive' });
    } finally { setBusy(false); }
  };
  const cancelMember = async (m) => {
    if (!await DialogService.confirm(`Cancel ${customersById[m.customerId]?.name || 'this member'}'s subscription?`)) return;
    setBusy(true);
    try {
      await v25API.cancelSubMember(m.id);
      toast({ title: 'Subscription cancelled' });
      load();
    } catch (e) {
      toast({ title: 'Cancel failed', description: e?.response?.data?.detail, variant: 'destructive' });
    } finally { setBusy(false); }
  };
  const togglePause = async (m) => {
    const next = m.status === 'paused' ? 'active' : 'paused';
    setBusy(true);
    try {
      await v25API.updateSubMember(m.id, { status: next });
      toast({ title: next === 'paused' ? 'Membership paused' : 'Membership resumed' });
      load();
    } catch (e) {
      toast({ title: 'Update failed', description: e?.response?.data?.detail, variant: 'destructive' });
    } finally { setBusy(false); }
  };

  const kpi = useMemo(() => {
    const active = members.filter(m => m.status === 'active').length;
    const paused = members.filter(m => m.status === 'paused').length;
    const mrr = members.reduce((s, m) => {
      if (m.status !== 'active') return s;
      const p = plansById[m.planId];
      return s + (p ? Number(p.priceMonthly || 0) : 0);
    }, 0);
    return { active, paused, mrr, plans: plans.length };
  }, [members, plans, plansById]);

  return (
    <div className="space-y-6" data-testid="subs-page">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-2" style={{ color: theme.text }}>
            <Star className="text-yellow-500" /> Subscription Memberships
          </h1>
          <p className="text-sm text-gray-500 mt-1">Recurring revenue: plans, members and renewals at a glance.</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={openEnroll} data-testid="enrol-btn">
            <UserPlus size={14} className="mr-1.5" /> Enrol Customer
          </Button>
          <Button onClick={openNewPlan} style={{ background: theme.primary }} className="text-white" data-testid="new-plan-btn">
            <Plus size={14} className="mr-1.5" /> New Plan
          </Button>
        </div>
      </div>

      {/* KPI row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3" data-testid="sub-kpis">
        <KpiCard label="Plans"            value={kpi.plans}  tone="bg-amber-50 border-amber-200 text-amber-800" testid="kpi-plans" />
        <KpiCard label="Active members"   value={kpi.active} tone="bg-emerald-50 border-emerald-200 text-emerald-800" testid="kpi-active" />
        <KpiCard label="Paused"           value={kpi.paused} tone="bg-gray-50 border-gray-200 text-gray-700" testid="kpi-paused" />
        <KpiCard label="Monthly recurring" value={`$${kpi.mrr.toFixed(2)}`} tone="bg-violet-50 border-violet-200 text-violet-800" testid="kpi-mrr" />
      </div>

      {/* Plans grid */}
      <section data-testid="plans-section">
        <h2 className="text-sm font-semibold uppercase tracking-widest text-gray-500 mb-2">Plans</h2>
        {plans.length === 0 ? (
          <Card><CardContent className="py-10 text-center text-gray-400">
            No plans yet — click <strong>New Plan</strong> to create your first one.
          </CardContent></Card>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {plans.map(p => (
              <Card key={p.id} className="bg-gradient-to-br from-amber-50 to-yellow-100 relative" data-testid={`plan-${p.id}`}>
                <CardContent className="p-5">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <p className="font-bold text-lg">{p.name}</p>
                        {p.active === false && <Badge className="bg-gray-200 text-gray-600 text-[10px]">inactive</Badge>}
                      </div>
                      <p className="text-3xl font-bold mt-2">
                        ${Number(p.priceMonthly || 0).toFixed(0)}
                        <span className="text-sm text-gray-500">/mo</span>
                      </p>
                      {p.priceAnnual > 0 && (
                        <p className="text-xs text-gray-500">or ${Number(p.priceAnnual).toFixed(0)}/year</p>
                      )}
                    </div>
                    <div className="flex flex-col gap-1">
                      <button
                        onClick={() => openEditPlan(p)}
                        className="p-1 rounded hover:bg-amber-200 transition"
                        title="Edit plan"
                        data-testid={`edit-plan-${p.id}`}
                      ><Pencil size={14} /></button>
                      <button
                        onClick={() => deletePlan(p)}
                        className="p-1 rounded hover:bg-red-200 transition text-red-600"
                        title="Delete plan"
                        data-testid={`delete-plan-${p.id}`}
                      ><Trash2 size={14} /></button>
                    </div>
                  </div>
                  <ul className="text-sm mt-3 space-y-1 min-h-[60px]">
                    {(p.perks || []).map((perk, i) => <li key={i}>· {perk}</li>)}
                    {(p.perks || []).length === 0 && <li className="text-gray-400 italic">No perks listed</li>}
                  </ul>
                  {p.trialDays > 0 && (
                    <p className="text-[10px] text-emerald-700 mt-2">🎁 {p.trialDays}-day free trial</p>
                  )}
                  {p.manualCode && (
                    <p className="text-[10px] text-gray-500 mt-2 font-mono flex items-center gap-1"><Tag size={10} /> {p.manualCode}</p>
                  )}
                  <Badge className="mt-3" data-testid={`member-count-${p.id}`}>
                    <Users size={11} className="mr-1" /> {members.filter(m => m.planId === p.id).length} members
                  </Badge>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </section>

      {/* Members table */}
      <section data-testid="members-section">
        <h2 className="text-sm font-semibold uppercase tracking-widest text-gray-500 mb-2">Members</h2>
        <Card>
          <CardContent className="p-0">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-xs uppercase text-gray-500">
                <tr>
                  <th className="text-left px-5 py-3">Member</th>
                  <th className="text-left px-5 py-3">Plan</th>
                  <th className="text-center px-5 py-3">Status</th>
                  <th className="text-left px-5 py-3">Since</th>
                  <th className="text-right px-5 py-3">Actions</th>
                </tr>
              </thead>
              <tbody>
                {members.length === 0 ? (
                  <tr><td colSpan={5} className="text-center py-10 text-gray-400" data-testid="no-members">
                    <Users size={28} className="mx-auto mb-2 opacity-40" />
                    No subscribers yet — enrol a customer to begin.
                  </td></tr>
                ) : members.map(m => {
                  const cust = customersById[m.customerId];
                  const plan = plansById[m.planId];
                  return (
                    <tr key={m.id} className="border-t hover:bg-gray-50" data-testid={`member-${m.id}`}>
                      <td className="px-5 py-3">
                        <div className="font-semibold">{cust?.name || <span className="text-gray-400">Unknown ({m.customerId})</span>}</div>
                        {cust?.email && <div className="text-xs text-gray-500">{cust.email}</div>}
                      </td>
                      <td className="px-5 py-3">{plan?.name || <span className="text-gray-400">— deleted plan —</span>}</td>
                      <td className="px-5 py-3 text-center">
                        <Badge className={`${STATUS_STYLE[m.status] || 'bg-gray-100 text-gray-600'} font-semibold capitalize`}>
                          {m.status || 'active'}
                        </Badge>
                      </td>
                      <td className="px-5 py-3 text-xs text-gray-500">
                        {m.startedAt ? new Date(m.startedAt).toLocaleDateString() : '—'}
                      </td>
                      <td className="px-5 py-3 text-right">
                        <div className="inline-flex gap-1">
                          <Button size="sm" variant="outline" onClick={() => openMember(m)} data-testid={`edit-member-${m.id}`}>
                            <Pencil size={11} className="mr-1" /> Edit
                          </Button>
                          {m.status !== 'cancelled' && (
                            <Button size="sm" variant="outline" onClick={() => togglePause(m)} data-testid={`pause-member-${m.id}`}>
                              {m.status === 'paused' ? <><Play size={11} className="mr-1" /> Resume</> : <><Pause size={11} className="mr-1" /> Pause</>}
                            </Button>
                          )}
                          {m.status !== 'cancelled' && (
                            <Button size="sm" variant="ghost" className="text-red-500" onClick={() => cancelMember(m)} data-testid={`cancel-member-${m.id}`}>
                              <X size={11} className="mr-1" /> Cancel
                            </Button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </CardContent>
        </Card>
      </section>

      {/* Plan create/edit dialog */}
      <Dialog open={planDialog} onOpenChange={setPlanDialog}>
        <DialogContent className="max-w-md max-h-[90vh] overflow-y-auto" data-testid="plan-dialog">
          <DialogHeader>
            <DialogTitle>{editingPlan ? 'Edit Plan' : 'New Plan'}</DialogTitle>
            <DialogDescription className="text-xs text-gray-500">
              Define what your members get and how much it costs.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3 py-2">
            <Field label="Name *">
              <Input value={planForm.name} onChange={e => setPlanForm({ ...planForm, name: e.target.value })} placeholder="e.g. Coffee Club" data-testid="plan-name" />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Monthly price ($)">
                <Input type="number" step="0.01" min="0" value={planForm.priceMonthly}
                  onChange={e => setPlanForm({ ...planForm, priceMonthly: e.target.value })}
                  placeholder="29" data-testid="plan-price-monthly" />
              </Field>
              <Field label="Annual price ($)">
                <Input type="number" step="0.01" min="0" value={planForm.priceAnnual}
                  onChange={e => setPlanForm({ ...planForm, priceAnnual: e.target.value })}
                  placeholder="300" data-testid="plan-price-annual" />
              </Field>
            </div>
            <Field label="Perks (one per line)">
              <textarea
                value={planForm.perks}
                onChange={e => setPlanForm({ ...planForm, perks: e.target.value })}
                rows={5}
                className="w-full p-2 border rounded text-sm"
                placeholder="1 free coffee daily&#10;10% off food&#10;Priority booking"
                data-testid="plan-perks"
              />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Trial days">
                <Input type="number" min="0" value={planForm.trialDays}
                  onChange={e => setPlanForm({ ...planForm, trialDays: e.target.value })}
                  data-testid="plan-trial-days" />
              </Field>
              <label className="flex items-center gap-2 pt-6 text-sm" data-testid="plan-active-toggle">
                <input type="checkbox" checked={planForm.active}
                  onChange={e => setPlanForm({ ...planForm, active: e.target.checked })} />
                Active (visible to customers)
              </label>
            </div>
            <Field label="Terms & Conditions">
              <textarea
                value={planForm.termsAndConditions}
                onChange={e => setPlanForm({ ...planForm, termsAndConditions: e.target.value })}
                rows={3}
                className="w-full p-2 border rounded text-sm"
                placeholder="Optional fine print"
                data-testid="plan-terms"
              />
            </Field>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setPlanDialog(false)} data-testid="plan-cancel">Cancel</Button>
            <Button onClick={savePlan} disabled={busy} style={{ background: theme.primary }} className="text-white" data-testid="plan-save">
              {busy ? 'Saving…' : (editingPlan ? 'Save changes' : 'Create plan')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Enrol customer dialog */}
      <Dialog open={enrollDialog} onOpenChange={setEnrollDialog}>
        <DialogContent className="max-w-sm" data-testid="enrol-dialog">
          <DialogHeader>
            <DialogTitle>Enrol Customer</DialogTitle>
            <DialogDescription className="text-xs text-gray-500">Add a customer to one of your active plans.</DialogDescription>
          </DialogHeader>
          <div className="space-y-3 py-2">
            <Field label="Customer">
              <select
                value={enrollForm.customerId}
                onChange={e => setEnrollForm({ ...enrollForm, customerId: e.target.value })}
                className="w-full p-2 border rounded text-sm"
                data-testid="enrol-customer-select"
              >
                <option value="">— Pick a customer —</option>
                {customers.map(c => (
                  <option key={c.id} value={c.id}>{c.name} ({c.email})</option>
                ))}
              </select>
            </Field>
            <Field label="Plan">
              <select
                value={enrollForm.planId}
                onChange={e => setEnrollForm({ ...enrollForm, planId: e.target.value })}
                className="w-full p-2 border rounded text-sm"
                data-testid="enrol-plan-select"
              >
                <option value="">— Pick a plan —</option>
                {plans.filter(p => p.active !== false).map(p => (
                  <option key={p.id} value={p.id}>{p.name} (${Number(p.priceMonthly || 0).toFixed(0)}/mo)</option>
                ))}
              </select>
            </Field>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEnrollDialog(false)}>Cancel</Button>
            <Button onClick={submitEnroll} disabled={busy} style={{ background: theme.primary }} className="text-white" data-testid="enrol-submit">
              {busy ? 'Enrolling…' : <><Check size={12} className="mr-1" /> Enrol</>}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Member edit dialog */}
      <Dialog open={!!memberDialog} onOpenChange={(o) => { if (!o) setMemberDialog(null); }}>
        <DialogContent className="max-w-sm" data-testid="member-dialog">
          <DialogHeader>
            <DialogTitle>Edit Membership</DialogTitle>
            <DialogDescription className="text-xs text-gray-500">
              {memberDialog && customersById[memberDialog.customerId]?.name}
            </DialogDescription>
          </DialogHeader>
          {memberDialog && (
            <div className="space-y-3 py-2">
              <Field label="Plan">
                <select
                  value={memberForm.planId}
                  onChange={e => setMemberForm({ ...memberForm, planId: e.target.value })}
                  className="w-full p-2 border rounded text-sm"
                  data-testid="member-plan-select"
                >
                  {plans.map(p => (
                    <option key={p.id} value={p.id}>{p.name} (${Number(p.priceMonthly || 0).toFixed(0)}/mo)</option>
                  ))}
                </select>
              </Field>
              <Field label="Status">
                <select
                  value={memberForm.status}
                  onChange={e => setMemberForm({ ...memberForm, status: e.target.value })}
                  className="w-full p-2 border rounded text-sm"
                  data-testid="member-status-select"
                >
                  <option value="active">Active</option>
                  <option value="paused">Paused</option>
                  <option value="cancelled">Cancelled</option>
                </select>
              </Field>
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setMemberDialog(null)}>Cancel</Button>
            <Button onClick={saveMember} disabled={busy} style={{ background: theme.primary }} className="text-white" data-testid="member-save">
              {busy ? 'Saving…' : 'Save'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

const KpiCard = ({ label, value, tone, testid }) => (
  <div className={`rounded-xl border px-3 py-2 ${tone}`} data-testid={testid}>
    <div className="text-[10px] uppercase tracking-widest font-semibold opacity-80">{label}</div>
    <div className="text-xl font-bold mt-0.5">{value}</div>
  </div>
);

const Field = ({ label, children }) => (
  <div>
    <label className="text-[10px] uppercase tracking-widest text-gray-500 block mb-1 font-semibold">{label}</label>
    {children}
  </div>
);
