import React, { useEffect, useState, useCallback } from 'react';
import axios from 'axios';
import { Card, CardContent } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Textarea } from '../components/ui/textarea';
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from '../components/ui/select';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '../components/ui/dialog';
import { toast } from 'sonner';
import { Sparkles, Play, X, ChevronRight, Loader2, ListChecks, Target, RefreshCw, CheckCircle2, Circle, AlertCircle, TestTube2 } from 'lucide-react';
import { SecureStorageService } from '../platform';

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const H = async () => ({ Authorization: `Bearer ${await SecureStorageService.getToken()}` });

const STATUS_TONE = {
  proposed: 'bg-indigo-500',
  executing: 'bg-blue-500',
  awaiting_approvals: 'bg-amber-500',
  completed: 'bg-emerald-500',
  partial_failed: 'bg-orange-500',
  rejected: 'bg-slate-400',
};

const STEP_ICON = {
  pending: Circle,
  executed: CheckCircle2,
  pending_approval: Loader2,
  blocked: X,
  rejected: X,
  error: AlertCircle,
  invalid: AlertCircle,
};

const STEP_TONE = {
  pending: 'text-slate-400',
  executed: 'text-emerald-500',
  pending_approval: 'text-amber-500 animate-spin',
  blocked: 'text-rose-500',
  rejected: 'text-slate-500',
  error: 'text-rose-600',
  invalid: 'text-rose-600',
};

export default function AshPlans() {
  const [plans, setPlans] = useState([]);
  const [personas, setPersonas] = useState([]);
  const [selected, setSelected] = useState(null);
  const [genOpen, setGenOpen] = useState(false);
  const [goal, setGoal] = useState('');
  const [persona, setPersona] = useState('executive');
  const [busy, setBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [simulation, setSimulation] = useState(null);
  const [simulating, setSimulating] = useState(false);

  const load = useCallback(async () => {
    setRefreshing(true);
    try {
      const [p, pl] = await Promise.all([
        axios.get(`${API}/nua/plans?limit=100`, { headers: await H() }),
        axios.get(`${API}/nua/personas`, { headers: await H() }),
      ]);
      setPlans(p.data);
      setPersonas(pl.data);
      if (selected) {
        const fresh = p.data.find(x => x.id === selected.id);
        if (fresh) setSelected(fresh);
      }
    } catch { toast.error('Failed to load plans'); }
    finally { setRefreshing(false); }
  }, [selected]);

  useEffect(() => { load(); }, [load]);

  const generatePlan = async () => {
    if (!goal.trim()) return;
    setBusy(true);
    try {
      const r = await axios.post(`${API}/nua/plans/generate`, { goal, persona }, { headers: await H() });
      toast.success(`Plan proposed (${r.data.steps.length} steps)`);
      setGenOpen(false);
      setGoal('');
      await load();
      setSelected(r.data);
    } catch { toast.error('Failed to generate'); }
    finally { setBusy(false); }
  };

  const approvePlan = async (id) => {
    try {
      const r = await axios.post(`${API}/nua/plans/${id}/approve`, {}, { headers: await H() });
      toast.success(`Plan walk complete: ${r.data.plan?.status}`);
      await load();
    } catch { toast.error('Approve failed'); }
  };

  const rejectPlan = async (id) => {
    try {
      await axios.post(`${API}/nua/plans/${id}/reject`, { reason: 'Owner declined' }, { headers: await H() });
      toast('Plan rejected');
      await load();
    } catch { toast.error('Reject failed'); }
  };

  const approveStep = async (id, idx) => {
    try {
      const r = await axios.post(`${API}/nua/plans/${id}/steps/${idx}/approve`, {}, { headers: await H() });
      toast.success(`Step ${idx + 1}: ${r.data.status || 'ok'}`);
      await load();
    } catch { toast.error('Step failed'); }
  };

  const rejectStep = async (id, idx) => {
    try {
      await axios.post(`${API}/nua/plans/${id}/steps/${idx}/reject`, { reason: 'not needed' }, { headers: await H() });
      toast('Step rejected');
      await load();
    } catch { toast.error('Reject failed'); }
  };

  const simulatePlan = async (id) => {
    setSimulating(true);
    setSimulation(null);
    try {
      const r = await axios.post(`${API}/nua/plans/${id}/simulate`, {}, { headers: await H() });
      setSimulation(r.data);
      toast.success('Simulation complete');
    } catch { toast.error('Simulation failed'); }
    finally { setSimulating(false); }
  };

  // Reset simulation whenever selected plan changes
  useEffect(() => { setSimulation(null); }, [selected?.id]);

  return (
    <div className="space-y-6" data-testid="ash-plans-page">
      <div className="flex justify-between items-center flex-wrap gap-3">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-2">
            <Target className="text-indigo-600" /> NUA Planner
          </h1>
          <p className="text-sm text-slate-500 mt-1">Multi-step plans NUA proposes — you approve the plan or individual steps.</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={load} disabled={refreshing} data-testid="plans-refresh-btn">
            <RefreshCw size={14} className={`mr-1.5 ${refreshing ? 'animate-spin' : ''}`} /> Refresh
          </Button>
          <Dialog open={genOpen} onOpenChange={setGenOpen}>
            <DialogTrigger asChild>
              <Button data-testid="new-plan-btn"><Sparkles size={14} className="mr-1" /> Ask NUA to plan</Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Ask NUA to build a plan</DialogTitle>
              </DialogHeader>
              <div className="space-y-3">
                <div>
                  <label className="text-xs text-slate-500">Persona</label>
                  <Select value={persona} onValueChange={setPersona}>
                    <SelectTrigger data-testid="plan-persona-select"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {personas.map(p => (
                        <SelectItem key={p.id} value={p.id}>{p.label}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <label className="text-xs text-slate-500">Goal</label>
                  <Textarea
                    rows={4}
                    placeholder="e.g. Reduce food waste by 20% this month"
                    value={goal}
                    onChange={e => setGoal(e.target.value)}
                    data-testid="plan-goal-input"
                  />
                </div>
                <Button
                  className="w-full"
                  disabled={busy || !goal.trim()}
                  onClick={generatePlan}
                  data-testid="generate-plan-btn"
                >
                  {busy ? <><Loader2 size={14} className="mr-2 animate-spin" /> Thinking&hellip;</> : <><Sparkles size={14} className="mr-2" /> Generate plan</>}
                </Button>
              </div>
            </DialogContent>
          </Dialog>
        </div>
      </div>

      <div className="grid md:grid-cols-12 gap-4">
        {/* Left: plans list */}
        <div className="md:col-span-4 space-y-2" data-testid="plans-list">
          {plans.length === 0 && (
            <Card><CardContent className="p-8 text-center text-sm text-slate-500">
              <ListChecks className="mx-auto mb-2 opacity-50" size={28} />
              No plans yet. Ask NUA to propose one.
            </CardContent></Card>
          )}
          {plans.map(p => (
            <Card
              key={p.id}
              className={`cursor-pointer transition hover:border-indigo-300 ${selected?.id === p.id ? 'border-indigo-500 ring-1 ring-indigo-200' : ''}`}
              onClick={() => setSelected(p)}
              data-testid={`plan-card-${p.id}`}
            >
              <CardContent className="p-4">
                <div className="flex justify-between items-start gap-2 mb-2">
                  <p className="font-semibold text-sm line-clamp-2">{p.goal}</p>
                  <Badge className={STATUS_TONE[p.status] || 'bg-slate-500'}>{p.status}</Badge>
                </div>
                <div className="flex items-center gap-2 text-[10px] text-slate-500">
                  <span>{p.personaLabel}</span>
                  <span>&middot;</span>
                  <span>{p.steps?.length || 0} steps</span>
                  <span>&middot;</span>
                  <span>risk {p.risk}</span>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>

        {/* Right: plan detail */}
        <div className="md:col-span-8">
          {!selected ? (
            <Card><CardContent className="p-12 text-center text-slate-500">
              <ChevronRight className="mx-auto mb-2 opacity-40" size={28} />
              Select a plan to inspect its steps.
            </CardContent></Card>
          ) : (
            <Card data-testid="plan-detail">
              <CardContent className="p-6 space-y-4">
                <div>
                  <div className="flex justify-between items-start gap-3">
                    <div>
                      <p className="text-xs uppercase tracking-wider text-slate-400">{selected.personaLabel} &middot; risk {selected.risk}</p>
                      <h2 className="text-lg font-semibold mt-1" data-testid="plan-goal">{selected.goal}</h2>
                    </div>
                    <Badge className={STATUS_TONE[selected.status] || 'bg-slate-500'}>{selected.status}</Badge>
                  </div>
                  {selected.rationale && (
                    <p className="text-sm text-slate-600 mt-2 leading-relaxed">{selected.rationale}</p>
                  )}
                  {selected.expectedOutcome && (
                    <div className="mt-3 p-3 bg-emerald-50 border border-emerald-100 rounded text-xs">
                      <b>Expected outcome:</b> {selected.expectedOutcome}
                    </div>
                  )}
                </div>

                {selected.status === 'proposed' && (
                  <div className="flex gap-2 pt-2 border-t flex-wrap">
                    <Button onClick={() => approvePlan(selected.id)} data-testid="approve-plan-btn">
                      <Play size={14} className="mr-1" /> Approve & walk
                    </Button>
                    <Button variant="outline" onClick={() => simulatePlan(selected.id)} disabled={simulating} data-testid="simulate-plan-btn">
                      {simulating ? <Loader2 size={14} className="mr-1 animate-spin" /> : <TestTube2 size={14} className="mr-1" />}
                      Simulate first
                    </Button>
                    <Button variant="outline" onClick={() => rejectPlan(selected.id)} data-testid="reject-plan-btn">
                      <X size={14} className="mr-1" /> Reject
                    </Button>
                  </div>
                )}

                {simulation && (
                  <div className="p-4 bg-indigo-50 border border-indigo-100 rounded-lg space-y-3" data-testid="simulation-panel">
                    <div className="flex items-center gap-2">
                      <TestTube2 size={16} className="text-indigo-600" />
                      <p className="font-semibold text-sm">What-if projection</p>
                    </div>
                    <p className="text-sm text-slate-700 leading-relaxed whitespace-pre-wrap">{simulation.narrative}</p>
                    <details className="text-xs">
                      <summary className="cursor-pointer text-indigo-700">Per-step simulation ({simulation.simulatedSteps.length} steps)</summary>
                      <div className="mt-2 space-y-1">
                        {simulation.simulatedSteps.map((s, i) => (
                          <div key={i} className="p-2 bg-white rounded border text-[11px]">
                            <div className="flex gap-2 items-center">
                              <Badge variant="outline" className="text-[9px]">{s.simStatus}</Badge>
                              <span className="font-mono">{s.tool}</span>
                            </div>
                            {s.simOutcome && (
                              <pre className="text-[10px] mt-1 whitespace-pre-wrap">{JSON.stringify(s.simOutcome, null, 2).slice(0, 400)}</pre>
                            )}
                          </div>
                        ))}
                      </div>
                    </details>
                  </div>
                )}

                <div className="space-y-2">
                  <p className="text-xs uppercase tracking-wider text-slate-400">Steps</p>
                  {selected.steps.map((s, i) => {
                    const Icon = STEP_ICON[s.status] || Circle;
                    return (
                      <div key={i} className="flex items-start gap-3 p-3 rounded border" data-testid={`step-${i}`}>
                        <Icon className={`shrink-0 mt-0.5 ${STEP_TONE[s.status] || 'text-slate-400'}`} size={18} />
                        <div className="flex-1 min-w-0">
                          <div className="flex justify-between items-center gap-2 flex-wrap">
                            <p className="font-mono text-xs">{s.tool}</p>
                            <Badge variant="outline" className="text-[9px]">{s.status.replace('_', ' ')}</Badge>
                          </div>
                          {s.rationale && <p className="text-xs text-slate-600 mt-1">{s.rationale}</p>}
                          {s.args && Object.keys(s.args).length > 0 && (
                            <details className="mt-1">
                              <summary className="text-[10px] text-slate-500 cursor-pointer">args</summary>
                              <pre className="text-[10px] bg-slate-50 p-2 rounded overflow-x-auto">{JSON.stringify(s.args, null, 2)}</pre>
                            </details>
                          )}
                          {s.outcome && (
                            <details className="mt-1">
                              <summary className="text-[10px] text-slate-500 cursor-pointer">outcome</summary>
                              <pre className="text-[10px] bg-slate-50 p-2 rounded overflow-x-auto">{JSON.stringify(s.outcome, null, 2)}</pre>
                            </details>
                          )}
                          {s.approvalId && (
                            <p className="text-[10px] text-amber-600 mt-1">
                              Queued in Approvals as <code>{s.approvalId.slice(0, 8)}</code> &middot;{' '}
                              <a href="/approvals" className="underline">review</a>
                            </p>
                          )}
                          {s.status === 'pending' && selected.status === 'proposed' && (
                            <div className="flex gap-1 mt-2">
                              <Button size="sm" variant="outline" className="h-6 text-[10px]" onClick={() => approveStep(selected.id, i)} data-testid={`approve-step-${i}`}>
                                Run this step
                              </Button>
                              <Button size="sm" variant="ghost" className="h-6 text-[10px] text-rose-600" onClick={() => rejectStep(selected.id, i)} data-testid={`reject-step-${i}`}>
                                Skip
                              </Button>
                            </div>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
