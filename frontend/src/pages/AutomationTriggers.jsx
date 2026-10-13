import React, { useEffect, useState, useCallback } from 'react';
import { Card, CardContent } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Badge } from '../components/ui/badge';
import { Textarea } from '../components/ui/textarea';
import { Switch } from '../components/ui/switch';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '../components/ui/tabs';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '../components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import { toast } from 'sonner';
import { Zap, Plus, Trash2, Sparkles, Play, Pause, Brain, History, GitBranch, ChevronRight, Cpu, Activity, ArrowRight, TrendingDown, RefreshCw, AlertTriangle, ShieldCheck } from 'lucide-react';
import axios from 'axios';
import { DialogService } from '../platform';

/* Tiny API wrapper — kept local to avoid polluting services/api.js */
const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const headers = () => ({ Authorization: `Bearer ${localStorage.getItem('nua_token')}` });
const rulesAPI = {
  list: () => axios.get(`${API}/rules`, { headers: headers() }),
  create: (b) => axios.post(`${API}/rules`, b, { headers: headers() }),
  update: (id, b) => axios.patch(`${API}/rules/${id}`, b, { headers: headers() }),
  toggle: (id) => axios.post(`${API}/rules/${id}/toggle`, {}, { headers: headers() }),
  remove: (id) => axios.delete(`${API}/rules/${id}`, { headers: headers() }),
  catalog: () => axios.get(`${API}/rules/catalog`, { headers: headers() }),
  stats: () => axios.get(`${API}/rules/stats`, { headers: headers() }),
  ai: (prompt) => axios.post(`${API}/rules/ai-build`, { prompt }, { headers: headers() }),
  simulate: (b) => axios.post(`${API}/rules/simulate`, b, { headers: headers() }),
  emit: (b) => axios.post(`${API}/rules/emit`, b, { headers: headers() }),
  executions: (params) => axios.get(`${API}/rules/history/executions`, { headers: headers(), params }),
  predictiveStockouts: () => axios.get(`${API}/rules/predictive/stockouts`, { headers: headers() }),
  predictiveScan: () => axios.post(`${API}/rules/predictive/scan`, {}, { headers: headers() }),
  opsErrorStatus: () => axios.get(`${API}/rules/ops/error-status`, { headers: headers() }),
  opsScan: () => axios.post(`${API}/rules/ops/scan`, {}, { headers: headers() }),
};

const emptyRule = {
  name: '', description: '', triggerEvent: 'inventory.low_stock',
  conditions: { mode: 'all', clauses: [] },
  actions: [{ type: 'dock_notify', params: { message: '' } }],
  active: true, priority: 0,
};

const MODULE_COLORS = {
  pos: '#f97316', commerce: '#a855f7', inventory: '#22c55e', crm: '#ec4899',
  bookings: '#3b82f6', labour: '#eab308', kitchen: '#ef4444', finance: '#0ea5e9',
};

export default function AutomationTriggers() {
  const [tab, setTab] = useState('rules');
  const [rules, setRules] = useState([]);
  const [catalog, setCatalog] = useState({ events: [], actions: [], operators: [] });
  const [stats, setStats] = useState(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [aiOpen, setAiOpen] = useState(false);
  const [aiPrompt, setAiPrompt] = useState('');
  const [aiBusy, setAiBusy] = useState(false);
  const [form, setForm] = useState(emptyRule);
  const [editId, setEditId] = useState(null);
  const [executions, setExecutions] = useState([]);
  const [simDialog, setSimDialog] = useState(null); // rule being simulated
  const [simPayload, setSimPayload] = useState('{}');
  const [simResult, setSimResult] = useState(null);
  const [predictions, setPredictions] = useState([]);
  const [predictiveLoading, setPredictiveLoading] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [opsStatus, setOpsStatus] = useState(null);
  const [opsLoading, setOpsLoading] = useState(false);
  const [opsScanning, setOpsScanning] = useState(false);

  const loadAll = useCallback(async () => {
    try {
      const [r, c, s] = await Promise.all([rulesAPI.list(), rulesAPI.catalog(), rulesAPI.stats()]);
      setRules(r.data); setCatalog(c.data); setStats(s.data);
    } catch { toast.error('Could not load rules'); }
  }, []);
  useEffect(() => { loadAll(); }, [loadAll]);

  const loadExecutions = async () => {
    try { setExecutions((await rulesAPI.executions({ limit: 50 })).data); }
    catch { toast.error('Could not load history'); }
  };
  useEffect(() => { if (tab === 'history') loadExecutions(); }, [tab]);

  const loadPredictions = useCallback(async () => {
    setPredictiveLoading(true);
    try { setPredictions((await rulesAPI.predictiveStockouts()).data.predictions); }
    catch { toast.error('Could not load predictions'); }
    finally { setPredictiveLoading(false); }
  }, []);
  useEffect(() => { if (tab === 'predictive') loadPredictions(); }, [tab, loadPredictions]);

  const runPredictiveScan = async () => {
    setScanning(true);
    try {
      const { data } = await rulesAPI.predictiveScan();
      toast.success(data.emitted > 0
        ? `Emitted ${data.emitted} new predicted-stockout event${data.emitted === 1 ? '' : 's'}`
        : 'No new predictions to emit — everything already flagged is inside its 12h dedupe window');
      loadPredictions();
    } catch { toast.error('Scan failed'); }
    finally { setScanning(false); }
  };

  const loadOpsStatus = useCallback(async () => {
    setOpsLoading(true);
    try { setOpsStatus((await rulesAPI.opsErrorStatus()).data); }
    catch { toast.error('Could not load error status'); }
    finally { setOpsLoading(false); }
  }, []);
  useEffect(() => { if (tab === 'ops') loadOpsStatus(); }, [tab, loadOpsStatus]);

  const runOpsScan = async () => {
    setOpsScanning(true);
    try {
      const { data } = await rulesAPI.opsScan();
      const emittedCount = (data.server.emitted ? 1 : 0) + (data.client.emitted ? 1 : 0);
      toast.success(emittedCount > 0
        ? `Emitted ${emittedCount} error-spike event${emittedCount === 1 ? '' : 's'}`
        : 'No new spikes to emit — either everything is quiet, or it’s inside its 2h dedupe window');
      loadOpsStatus();
    } catch { toast.error('Scan failed'); }
    finally { setOpsScanning(false); }
  };

  const openNew = () => { setForm(emptyRule); setEditId(null); setDialogOpen(true); };
  const openEdit = (r) => {
    setForm({
      name: r.name, description: r.description || '', triggerEvent: r.triggerEvent,
      conditions: r.conditions || { mode: 'all', clauses: [] },
      actions: r.actions || [], active: r.active !== false, priority: r.priority || 0,
      aiGenerated: r.aiGenerated, aiPrompt: r.aiPrompt,
    });
    setEditId(r.id); setDialogOpen(true);
  };

  const save = async () => {
    if (!form.name.trim()) return toast.error('Name required');
    try {
      if (editId) await rulesAPI.update(editId, form);
      else await rulesAPI.create(form);
      toast.success(editId ? 'Rule updated' : 'Rule created');
      setDialogOpen(false); loadAll();
    } catch (e) { toast.error(e.response?.data?.detail || 'Failed'); }
  };

  const toggle = async (r) => {
    try { await rulesAPI.toggle(r.id); loadAll(); }
    catch { toast.error('Failed'); }
  };

  const remove = async (r) => {
    if (!await DialogService.confirm(`Delete "${r.name}"?`)) return;
    try { await rulesAPI.remove(r.id); toast.success('Deleted'); loadAll(); }
    catch (e) { toast.error(e.response?.data?.detail || 'Failed'); }
  };

  const aiSuggest = async () => {
    if (!aiPrompt.trim()) return toast.error('Describe the automation');
    setAiBusy(true);
    try {
      const r = await rulesAPI.ai(aiPrompt);
      setForm({
        name: r.data.name || 'AI Automation',
        description: r.data.description || aiPrompt,
        triggerEvent: r.data.triggerEvent || 'inventory.low_stock',
        conditions: r.data.conditions || { mode: 'all', clauses: [] },
        actions: r.data.actions?.length ? r.data.actions : [{ type: 'dock_notify', params: {} }],
        priority: r.data.priority || 0, active: true,
        aiGenerated: true, aiPrompt,
      });
      setAiOpen(false); setEditId(null); setDialogOpen(true);
    } catch (e) { toast.error(e.response?.data?.detail || 'AI failed'); }
    finally { setAiBusy(false); }
  };

  const runSimulate = async () => {
    let payload = {};
    try { payload = JSON.parse(simPayload || '{}'); }
    catch { return toast.error('Payload must be valid JSON'); }
    try {
      const r = await rulesAPI.simulate({ ruleId: simDialog.id, payload });
      setSimResult(r.data);
    } catch (e) { toast.error(e.response?.data?.detail || 'Failed'); }
  };

  const eventMeta = (t) => catalog.events.find(e => e.type === t) || { module: 'unknown', label: t };
  const actionMeta = (t) => catalog.actions.find(a => a.type === t) || { label: t };

  const addAction = () => setForm(f => ({ ...f, actions: [...f.actions, { type: 'dock_notify', params: {} }] }));
  const updateAction = (i, patch) => setForm(f => ({
    ...f, actions: f.actions.map((a, idx) => idx === i ? { ...a, ...patch } : a),
  }));
  const removeAction = (i) => setForm(f => ({ ...f, actions: f.actions.filter((_, idx) => idx !== i) }));

  const addClause = () => setForm(f => ({
    ...f, conditions: { ...f.conditions, clauses: [...(f.conditions?.clauses || []), { path: '', op: 'eq', value: '' }] },
  }));
  const updateClause = (i, patch) => setForm(f => ({
    ...f, conditions: {
      ...f.conditions,
      clauses: (f.conditions?.clauses || []).map((c, idx) => idx === i ? { ...c, ...patch } : c),
    },
  }));
  const removeClause = (i) => setForm(f => ({
    ...f, conditions: {
      ...f.conditions,
      clauses: (f.conditions?.clauses || []).filter((_, idx) => idx !== i),
    },
  }));

  return (
    <div className="space-y-6" data-testid="automation-brain-page">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-2">
            <Brain className="text-indigo-500" /> Automation Brain
          </h1>
          <p className="text-sm text-slate-500 mt-1">Cross-module rules engine — one place to automate inventory, CRM, labour, bookings, kitchen &amp; finance.</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => setAiOpen(true)} data-testid="ai-build-btn">
            <Sparkles size={14} className="mr-1.5" /> AI Builder
          </Button>
          <Button onClick={openNew} data-testid="new-rule-btn"><Plus size={14} className="mr-1.5" /> New Rule</Button>
        </div>
      </div>

      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <StatCard label="Active Rules" value={stats.activeRules} sub={`of ${stats.totalRules}`} icon={GitBranch} color="text-emerald-600" />
          <StatCard label="Events Fired" value={stats.totalEvents} icon={Activity} color="text-blue-600" />
          <StatCard label="Rule Executions" value={stats.totalExecutions} icon={Cpu} color="text-purple-600" />
          <StatCard label="Modules Covered" value={Object.keys(stats.byModule).length} sub={Object.keys(stats.byModule).join(', ') || '—'} icon={Zap} color="text-amber-600" />
        </div>
      )}

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="rules" data-testid="tab-rules"><GitBranch size={14} className="mr-1" /> Rules</TabsTrigger>
          <TabsTrigger value="history" data-testid="tab-history"><History size={14} className="mr-1" /> History</TabsTrigger>
          <TabsTrigger value="catalog" data-testid="tab-catalog"><Cpu size={14} className="mr-1" /> Events &amp; Actions</TabsTrigger>
          <TabsTrigger value="predictive" data-testid="tab-predictive"><TrendingDown size={14} className="mr-1" /> Predictive</TabsTrigger>
          <TabsTrigger value="ops" data-testid="tab-ops"><AlertTriangle size={14} className="mr-1" /> Ops Health</TabsTrigger>
        </TabsList>

        <TabsContent value="rules">
          {rules.length === 0 ? (
            <Card className="border-dashed"><CardContent className="p-12 text-center">
              <Brain size={40} className="mx-auto mb-3 text-slate-300" />
              <p className="text-slate-500 mb-4">No rules yet. Try the AI Builder or create one manually.</p>
              <Button onClick={openNew} data-testid="empty-new-rule"><Plus size={14} className="mr-1" /> New Rule</Button>
            </CardContent></Card>
          ) : (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              {rules.map(r => {
                const em = eventMeta(r.triggerEvent);
                const color = MODULE_COLORS[em.module] || '#64748b';
                return (
                  <Card key={r.id} className="border-0 shadow-sm" data-testid={`rule-card-${r.id}`}>
                    <CardContent className="p-5 space-y-3">
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2 flex-wrap">
                            <h3 className="font-bold text-lg truncate">{r.name}</h3>
                            {r.aiGenerated && <Badge className="bg-purple-100 text-purple-700 text-[10px]"><Sparkles size={10} className="mr-1" /> AI</Badge>}
                            {r.priority > 0 && <Badge variant="outline" className="text-[10px]">P{r.priority}</Badge>}
                          </div>
                          <Badge className="text-xs mt-1" style={{ background: `${color}15`, color, border: `1px solid ${color}40` }}>
                            {em.module} · {em.label}
                          </Badge>
                          {r.description && <p className="text-xs text-slate-500 mt-2 line-clamp-2">{r.description}</p>}
                        </div>
                        <div className="flex items-center gap-1">
                          <Switch checked={!!r.active} onCheckedChange={() => toggle(r)} data-testid={`toggle-${r.id}`} />
                        </div>
                      </div>

                      {(r.conditions?.clauses?.length > 0) && (
                        <div className="text-xs bg-slate-50 rounded p-2 border">
                          <p className="text-slate-400 uppercase tracking-widest text-[10px] mb-1">
                            IF {r.conditions.mode?.toUpperCase() || 'ALL'}
                          </p>
                          {r.conditions.clauses.map((c, i) => (
                            <div key={i} className="font-mono text-[11px]">
                              <span className="text-slate-700">{c.path}</span>
                              <span className="text-indigo-600 mx-1">{c.op}</span>
                              <span className="text-emerald-600">{JSON.stringify(c.value)}</span>
                            </div>
                          ))}
                        </div>
                      )}

                      <div className="space-y-1">
                        <p className="text-slate-400 uppercase tracking-widest text-[10px]">THEN ({(r.actions || []).length})</p>
                        {(r.actions || []).map((a, i) => (
                          <div key={i} className="text-xs flex items-center gap-1.5 bg-indigo-50 rounded px-2 py-1 border border-indigo-100">
                            <ArrowRight size={10} className="text-indigo-500" />
                            <span className="font-medium">{actionMeta(a.type).label}</span>
                            {a.params && Object.keys(a.params).length > 0 && (
                              <span className="text-slate-500 truncate text-[10px]">— {JSON.stringify(a.params)}</span>
                            )}
                          </div>
                        ))}
                      </div>

                      <div className="flex items-center justify-between pt-2 border-t">
                        <div className="flex items-center gap-2 text-[10px] text-slate-400">
                          {r.active ? <Play size={10} className="text-emerald-500" /> : <Pause size={10} />}
                          <span>{r.active ? 'Active' : 'Paused'}</span>
                          {r.triggerCount > 0 && <span>· fired {r.triggerCount}×</span>}
                          {r.lastTriggeredAt && <span>· last {new Date(r.lastTriggeredAt).toLocaleDateString()}</span>}
                        </div>
                        <div className="flex gap-1">
                          <Button size="sm" variant="ghost" onClick={() => { setSimDialog(r); setSimResult(null); setSimPayload('{}'); }} data-testid={`simulate-${r.id}`}>Simulate</Button>
                          <Button size="sm" variant="ghost" onClick={() => openEdit(r)} data-testid={`edit-${r.id}`}>Edit</Button>
                          <Button size="sm" variant="ghost" className="text-rose-500" onClick={() => remove(r)} data-testid={`delete-${r.id}`}>
                            <Trash2 size={14} />
                          </Button>
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                );
              })}
            </div>
          )}
        </TabsContent>

        <TabsContent value="history">
          <Card><CardContent className="p-0" data-testid="history-content">
            <table className="w-full text-sm">
              <thead className="bg-slate-50"><tr>
                <th className="text-left p-2 pl-4 text-xs text-slate-500">Time</th>
                <th className="text-left p-2 text-xs text-slate-500">Event</th>
                <th className="text-left p-2 text-xs text-slate-500">Rules fired</th>
                <th className="text-left p-2 pr-4 text-xs text-slate-500">Outcomes</th>
              </tr></thead>
              <tbody>
                {executions.map(e => (
                  <tr key={e.id} className="border-t align-top">
                    <td className="p-2 pl-4 text-xs">{new Date(e.ts).toLocaleString()}</td>
                    <td className="p-2"><Badge variant="outline">{e.eventType}</Badge></td>
                    <td className="p-2">
                      {e.firings.map((f, i) => (
                        <div key={i} className="text-xs">
                          {f.matched ? '✓' : '·'} {f.name}
                        </div>
                      ))}
                    </td>
                    <td className="p-2 pr-4 text-xs text-slate-500">
                      {e.firings.filter(f => f.matched).flatMap(f => f.outcomes || []).map((o, i) => (
                        <div key={i}>
                          <Badge className="text-[10px] mr-1" variant="secondary">{o.type}</Badge>
                          {o.error ? <span className="text-rose-500">✕ {o.error}</span> : <span>✓</span>}
                        </div>
                      ))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {executions.length === 0 && <p className="text-center text-slate-400 py-8">No executions yet</p>}
          </CardContent></Card>
        </TabsContent>

        <TabsContent value="catalog">
          <div className="grid md:grid-cols-2 gap-4">
            <Card><CardContent className="p-4">
              <h3 className="font-semibold mb-3">Event Catalog · {catalog.events.length}</h3>
              <div className="space-y-2 max-h-[500px] overflow-y-auto">
                {catalog.events.map(ev => {
                  const c = MODULE_COLORS[ev.module] || '#64748b';
                  return (
                    <div key={ev.type} className="text-xs p-2 rounded border" style={{ background: `${c}08`, borderColor: `${c}30` }}>
                      <div className="flex justify-between items-center">
                        <span className="font-mono text-[11px]">{ev.type}</span>
                        <Badge className="text-[10px]" style={{ background: c, color: 'white' }}>{ev.module}</Badge>
                      </div>
                      <p className="text-slate-600 mt-1">{ev.label}</p>
                      {ev.fields && <p className="text-[10px] text-slate-400 mt-0.5 font-mono">payload: {ev.fields.join(', ')}</p>}
                    </div>
                  );
                })}
              </div>
            </CardContent></Card>
            <Card><CardContent className="p-4">
              <h3 className="font-semibold mb-3">Action Library · {catalog.actions.length}</h3>
              <div className="space-y-2 max-h-[500px] overflow-y-auto">
                {catalog.actions.map(a => (
                  <div key={a.type} className="text-xs p-2 rounded border bg-slate-50">
                    <div className="flex justify-between items-center">
                      <span className="font-mono text-[11px]">{a.type}</span>
                      <Badge variant="outline" className="text-[10px]">{(a.params || []).length} params</Badge>
                    </div>
                    <p className="text-slate-600 mt-1">{a.label}</p>
                    {a.params?.length > 0 && (
                      <p className="text-[10px] text-slate-400 mt-0.5 font-mono">params: {a.params.join(', ')}</p>
                    )}
                  </div>
                ))}
              </div>
            </CardContent></Card>
          </div>
        </TabsContent>

        <TabsContent value="predictive">
          <Card>
            <CardContent className="p-4 space-y-4">
              <div className="flex items-center justify-between flex-wrap gap-2">
                <div>
                  <h3 className="font-semibold flex items-center gap-2"><TrendingDown size={16} className="text-amber-600" /> Predicted stockouts</h3>
                  <p className="text-xs text-slate-500 mt-1">
                    Projected from real sales velocity, not just today's stock count — flags anything on track
                    to hit zero within 2 days, before inventory.low_stock or inventory.stockout would ever fire.
                    Runs automatically every hour; emits <span className="font-mono text-[11px]">inventory.predicted_stockout</span> for
                    any rule subscribed to it.
                  </p>
                </div>
                <div className="flex gap-2 flex-shrink-0">
                  <Button size="sm" variant="outline" onClick={loadPredictions} disabled={predictiveLoading} data-testid="predictive-refresh-btn">
                    <RefreshCw size={12} className={`mr-1 ${predictiveLoading ? 'animate-spin' : ''}`} /> Refresh
                  </Button>
                  <Button size="sm" onClick={runPredictiveScan} disabled={scanning} data-testid="predictive-scan-btn">
                    {scanning ? 'Scanning…' : 'Scan now'}
                  </Button>
                </div>
              </div>

              {predictions.length === 0 ? (
                <p className="text-center text-slate-400 py-8 text-sm">
                  {predictiveLoading ? 'Loading…' : 'Nothing projected to run out within 2 days.'}
                </p>
              ) : (
                <div className="space-y-2" data-testid="predictive-list">
                  {predictions.map(p => (
                    <div key={p.productId} className="flex items-center justify-between gap-3 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2"
                      data-testid={`predictive-row-${p.productId}`}>
                      <div className="min-w-0">
                        <p className="text-sm font-medium truncate">{p.productName}</p>
                        <p className="text-xs text-slate-500">
                          {p.currentStock} left · selling ~{p.avgDailyUsage}/day
                        </p>
                      </div>
                      <Badge className="bg-amber-600 text-white flex-shrink-0">
                        {p.daysRemaining < 1 ? '< 1 day left' : `~${p.daysRemaining} days left`}
                      </Badge>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="ops">
          <Card>
            <CardContent className="p-4 space-y-4">
              <div className="flex items-center justify-between flex-wrap gap-2">
                <div>
                  <h3 className="font-semibold flex items-center gap-2"><AlertTriangle size={16} className="text-rose-600" /> Error rate monitoring</h3>
                  <p className="text-xs text-slate-500 mt-1">
                    Server and browser errors are always captured (Audit → Error Log), but nothing acted on them
                    until now — this checks the last 30 minutes hourly and emits{' '}
                    <span className="font-mono text-[11px]">ops.error_spike</span> when either crosses its threshold,
                    so a subscribed rule can notify or page instead of waiting for a complaint.
                  </p>
                </div>
                <div className="flex gap-2 flex-shrink-0">
                  <Button size="sm" variant="outline" onClick={loadOpsStatus} disabled={opsLoading} data-testid="ops-refresh-btn">
                    <RefreshCw size={12} className={`mr-1 ${opsLoading ? 'animate-spin' : ''}`} /> Refresh
                  </Button>
                  <Button size="sm" onClick={runOpsScan} disabled={opsScanning} data-testid="ops-scan-btn">
                    {opsScanning ? 'Scanning…' : 'Scan now'}
                  </Button>
                </div>
              </div>

              {opsStatus && (
                <div className="grid md:grid-cols-2 gap-3">
                  {[{ key: 'server', label: 'Server errors' }, { key: 'client', label: 'Browser errors' }].map(({ key, label }) => {
                    const s = opsStatus[key];
                    return (
                      <div key={key}
                        className={`rounded-lg border px-4 py-3 ${s.triggered ? 'bg-rose-50 border-rose-200' : 'bg-emerald-50 border-emerald-200'}`}
                        data-testid={`ops-status-${key}`}>
                        <div className="flex items-center gap-2">
                          {s.triggered ? <AlertTriangle size={14} className="text-rose-600" /> : <ShieldCheck size={14} className="text-emerald-600" />}
                          <p className="text-sm font-medium">{label}</p>
                        </div>
                        <p className="text-xs text-slate-600 mt-1">
                          {s.count} in the last {s.windowMinutes} min (threshold {s.threshold})
                        </p>
                        {s.triggered && s.topPath && (
                          <p className="text-[11px] text-rose-700 mt-1 font-mono truncate">Most affected: {s.topPath}</p>
                        )}
                        {s.triggered && s.sampleMessage && (
                          <p className="text-[11px] text-rose-700 mt-1 truncate">{s.sampleMessage}</p>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
              {!opsStatus && (
                <p className="text-center text-slate-400 py-8 text-sm">{opsLoading ? 'Loading…' : 'No data yet.'}</p>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      {/* AI Builder Dialog */}
      <Dialog open={aiOpen} onOpenChange={setAiOpen}>
        <DialogContent className="max-w-lg" data-testid="ai-builder-dialog">
          <DialogHeader><DialogTitle className="flex items-center gap-2"><Sparkles size={16} /> Describe your automation in plain English</DialogTitle></DialogHeader>
          <div className="space-y-3 py-2">
            <Textarea rows={4} value={aiPrompt} onChange={e => setAiPrompt(e.target.value)}
              placeholder='e.g. "When a customer spends over $500, upgrade to Platinum and email them a thank-you voucher"'
              data-testid="ai-prompt-input" />
            <p className="text-xs text-slate-500">Powered by GPT-5.2 · You&apos;ll review the generated rule before saving.</p>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setAiOpen(false)}>Cancel</Button>
            <Button onClick={aiSuggest} disabled={aiBusy} data-testid="ai-generate-btn">
              {aiBusy ? 'Thinking…' : 'Generate Rule'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Rule Editor Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-w-3xl max-h-[85vh] overflow-y-auto" data-testid="rule-editor-dialog">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              {form.aiGenerated ? <><Sparkles size={16} /> AI-Generated Rule</> : <><Zap size={16} /> {editId ? 'Edit Rule' : 'New Rule'}</>}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            {form.aiGenerated && form.aiPrompt && (
              <div className="text-xs bg-purple-50 border border-purple-100 rounded p-2 flex items-start gap-1.5">
                <Sparkles size={12} className="text-purple-500 shrink-0 mt-0.5" />
                <span className="text-purple-800">AI prompt: “{form.aiPrompt}”</span>
              </div>
            )}
            <Input placeholder="Rule name" value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} data-testid="rule-name" />
            <Input placeholder="Description (optional)" value={form.description} onChange={e => setForm({ ...form, description: e.target.value })} />

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs font-medium text-slate-500 mb-1 block">WHEN</label>
                <Select value={form.triggerEvent} onValueChange={v => setForm({ ...form, triggerEvent: v })}>
                  <SelectTrigger data-testid="rule-event"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {catalog.events.map(ev => (
                      <SelectItem key={ev.type} value={ev.type}>{ev.module} · {ev.label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <label className="text-xs font-medium text-slate-500 mb-1 block">Priority</label>
                <Input type="number" value={form.priority} onChange={e => setForm({ ...form, priority: parseInt(e.target.value) || 0 })} />
              </div>
            </div>

            <div>
              <div className="flex items-center justify-between mb-1">
                <label className="text-xs font-medium text-slate-500">IF conditions</label>
                <div className="flex gap-1 items-center">
                  <Select value={form.conditions?.mode || 'all'} onValueChange={v => setForm({ ...form, conditions: { ...form.conditions, mode: v } })}>
                    <SelectTrigger className="w-24 h-7 text-xs"><SelectValue /></SelectTrigger>
                    <SelectContent><SelectItem value="all">ALL</SelectItem><SelectItem value="any">ANY</SelectItem></SelectContent>
                  </Select>
                  <Button size="sm" variant="ghost" onClick={addClause} data-testid="add-clause-btn"><Plus size={12} /> Clause</Button>
                </div>
              </div>
              <div className="space-y-2">
                {(form.conditions?.clauses || []).map((c, i) => (
                  <div key={i} className="grid grid-cols-[1fr_100px_1fr_auto] gap-2 items-center">
                    <Input placeholder="payload path" value={c.path || ''} onChange={e => updateClause(i, { path: e.target.value })} className="font-mono text-xs" data-testid={`clause-${i}-path`} />
                    <Select value={c.op || 'eq'} onValueChange={v => updateClause(i, { op: v })}>
                      <SelectTrigger data-testid={`clause-${i}-op`}><SelectValue /></SelectTrigger>
                      <SelectContent>
                        {catalog.operators.map(o => <SelectItem key={o} value={o}>{o}</SelectItem>)}
                      </SelectContent>
                    </Select>
                    <Input placeholder="value" value={typeof c.value === 'string' ? c.value : JSON.stringify(c.value ?? '')}
                      onChange={e => {
                        let v = e.target.value;
                        try { v = JSON.parse(v); } catch { /* keep as string */ }
                        updateClause(i, { value: v });
                      }}
                      className="text-xs" data-testid={`clause-${i}-value`} />
                    <Button size="sm" variant="ghost" className="text-rose-500" onClick={() => removeClause(i)}><Trash2 size={12} /></Button>
                  </div>
                ))}
                {(form.conditions?.clauses || []).length === 0 && (
                  <p className="text-xs text-slate-400 pl-2">No conditions — rule fires on every event.</p>
                )}
              </div>
            </div>

            <div>
              <div className="flex items-center justify-between mb-1">
                <label className="text-xs font-medium text-slate-500">THEN actions</label>
                <Button size="sm" variant="ghost" onClick={addAction} data-testid="add-action-btn"><Plus size={12} /> Action</Button>
              </div>
              <div className="space-y-2">
                {form.actions.map((a, i) => (
                  <div key={i} className="border rounded p-2 bg-slate-50/60" data-testid={`action-row-${i}`}>
                    <div className="flex items-center gap-2 mb-2">
                      <Select value={a.type} onValueChange={v => updateAction(i, { type: v })}>
                        <SelectTrigger className="flex-1" data-testid={`action-${i}-type`}><SelectValue /></SelectTrigger>
                        <SelectContent>
                          {catalog.actions.map(x => <SelectItem key={x.type} value={x.type}>{x.label}</SelectItem>)}
                        </SelectContent>
                      </Select>
                      <Button size="sm" variant="ghost" className="text-rose-500" onClick={() => removeAction(i)}><Trash2 size={12} /></Button>
                    </div>
                    <Textarea rows={2} placeholder='Params JSON — e.g. {"tier":"Gold"}'
                      value={JSON.stringify(a.params || {}, null, 0)}
                      onChange={e => {
                        try { updateAction(i, { params: JSON.parse(e.target.value || '{}') }); }
                        catch { /* ignore mid-typing */ }
                      }} className="font-mono text-xs" data-testid={`action-${i}-params`} />
                    <p className="text-[10px] text-slate-400 mt-1">Available params: {(actionMeta(a.type).params || []).join(', ') || '—'}</p>
                  </div>
                ))}
              </div>
            </div>

            <div className="flex items-center gap-2">
              <Switch checked={form.active} onCheckedChange={v => setForm({ ...form, active: v })} data-testid="rule-active" />
              <span className="text-sm text-slate-600">Active on save</span>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>Cancel</Button>
            <Button onClick={save} data-testid="save-rule-btn">{editId ? 'Update Rule' : 'Create Rule'}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Simulator Dialog */}
      <Dialog open={!!simDialog} onOpenChange={o => !o && setSimDialog(null)}>
        <DialogContent data-testid="simulator-dialog">
          <DialogHeader><DialogTitle>Simulate · {simDialog?.name}</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <p className="text-xs text-slate-500">Provide a JSON payload for event <Badge variant="outline">{simDialog?.triggerEvent}</Badge></p>
            <Textarea rows={5} value={simPayload} onChange={e => setSimPayload(e.target.value)} className="font-mono text-xs" data-testid="sim-payload" />
            <Button onClick={runSimulate} className="w-full" data-testid="sim-run">Run Simulation</Button>
            {simResult && (
              <div className="text-xs border rounded p-3 bg-slate-50">
                <p className="mb-2 font-semibold">Would fire: {simResult.wouldFire ? '✅ YES' : '❌ NO'}</p>
                {simResult.conditionResult?.details?.map((d, i) => (
                  <div key={i} className="font-mono text-[11px]">
                    {d.passed ? '✓' : '✗'} <span className="text-slate-700">{d.path}</span> {d.op} {JSON.stringify(d.expected)} (actual: {JSON.stringify(d.actual)})
                  </div>
                ))}
              </div>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}

const StatCard = ({ label, value, sub, icon: Icon, color }) => (
  <Card><CardContent className="p-4">
    <div className="flex items-center justify-between">
      <div>
        <p className="text-xs uppercase tracking-wider text-slate-500">{label}</p>
        <p className={`text-2xl font-bold mt-1 ${color}`}>{value}</p>
        {sub && <p className="text-[10px] text-slate-500 mt-0.5">{sub}</p>}
      </div>
      <Icon size={32} className={`opacity-30 ${color}`} />
    </div>
  </CardContent></Card>
);
