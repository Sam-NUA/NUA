import React, { useEffect, useState, useCallback } from 'react';
import axios from 'axios';
import { Card, CardContent } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '../components/ui/tabs';
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from '../components/ui/select';
import { toast } from 'sonner';
import { Activity, AlertTriangle, TrendingUp, ShieldCheck, RefreshCw, Sparkles, Brain, Sunrise, Wrench } from 'lucide-react';
import { SecureStorageService } from '../platform';

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const H = async () => ({ Authorization: `Bearer ${await SecureStorageService.getToken()}` });

const TIER_COLOR = {
  excellent: '#10b981', healthy: '#22c55e', watch: '#f59e0b',
  at_risk: '#f97316', critical: '#ef4444',
};

const SEV_ORDER = ['high', 'warning', 'notice', 'info'];
const SEV_COLOR = { high: '#ef4444', warning: '#f59e0b', notice: '#3b82f6', info: '#94a3b8' };

export default function AshCommandCenter() {
  const [health, setHealth] = useState(null);
  const [insights, setInsights] = useState([]);
  const [briefing, setBriefing] = useState(null);
  const [approvals, setApprovals] = useState([]);
  const [tools, setTools] = useState([]);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    setRefreshing(true);
    try {
      const [h, i, b, a, t] = await Promise.all([
        axios.get(`${API}/nua/health-score`, { headers: await H() }),
        axios.get(`${API}/nua/insights?limit=100`, { headers: await H() }),
        axios.get(`${API}/nua/briefing`, { headers: await H() }),
        axios.get(`${API}/approvals?status=pending`, { headers: await H() }),
        axios.get(`${API}/nua/tools`, { headers: await H() }),
      ]);
      setHealth(h.data); setInsights(i.data); setBriefing(b.data);
      setApprovals(a.data); setTools(t.data);
    } catch { toast.error('Failed to load Command Center'); }
    finally { setRefreshing(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const regenerateBriefing = async () => {
    try {
      const r = await axios.post(`${API}/nua/briefing/regenerate`, {}, { headers: await H() });
      setBriefing(r.data);
      toast.success('Briefing regenerated');
    } catch { toast.error('Failed'); }
  };

  const setPermission = async (toolName, permission) => {
    try {
      await axios.put(`${API}/nua/tools/${toolName}/permission`, { permission }, { headers: await H() });
      toast.success(`${toolName} → ${permission}`);
      load();
    } catch { toast.error('Failed'); }
  };

  const sortedInsights = [...insights].sort((a, b) =>
    SEV_ORDER.indexOf(a.severity) - SEV_ORDER.indexOf(b.severity)
  );
  const critical = sortedInsights.filter(i => i.severity === 'high').length;
  const warnings = sortedInsights.filter(i => i.severity === 'warning').length;
  const moderate = sortedInsights.filter(i => i.severity === 'notice').length;

  return (
    <div className="space-y-6" data-testid="ash-command-center">
      <div className="flex justify-between items-center flex-wrap gap-3">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-2">
            <Brain className="text-indigo-600" /> NUA Command Center
          </h1>
          <p className="text-sm text-slate-500 mt-1">Hospitality AI Operating Agent — Observe · Analyse · Recommend · Execute · Learn</p>
        </div>
        <Button variant="outline" onClick={load} disabled={refreshing} data-testid="cc-refresh-btn">
          <RefreshCw size={14} className={`mr-1.5 ${refreshing ? 'animate-spin' : ''}`} /> Refresh
        </Button>
      </div>

      {/* Business Health Score gauge */}
      {health && (
        <Card><CardContent className="p-6">
          <div className="flex items-center gap-8 flex-wrap">
            <div className="relative flex-shrink-0" style={{ width: 180, height: 180 }} data-testid="health-gauge">
              <svg viewBox="0 0 200 200" className="w-full h-full -rotate-90">
                <circle cx="100" cy="100" r="80" strokeWidth="16" stroke="#e2e8f0" fill="none" />
                <circle cx="100" cy="100" r="80" strokeWidth="16"
                  stroke={TIER_COLOR[health.tier] || '#64748b'}
                  fill="none" strokeLinecap="round"
                  strokeDasharray={`${(health.overall / 100) * 502.65} 502.65`} />
              </svg>
              <div className="absolute inset-0 flex flex-col items-center justify-center">
                <p className="text-4xl font-bold" style={{ color: TIER_COLOR[health.tier] }}>{health.overall}</p>
                <p className="text-xs uppercase tracking-wider text-slate-400 mt-1">{health.tier.replace('_', ' ')}</p>
              </div>
            </div>
            <div className="flex-1 min-w-[300px]">
              <p className="text-xs uppercase tracking-wider text-slate-500 mb-2">Business Health Score · 10 sub-scores</p>
              <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
                {Object.entries(health.subscores).map(([k, v]) => (
                  <div key={k} className="p-2 bg-slate-50 rounded" data-testid={`sub-${k}`}>
                    <div className="flex justify-between items-center">
                      <span className="text-[10px] uppercase text-slate-500">{k.replace(/([A-Z])/g, ' $1').trim()}</span>
                      <span className="text-xs font-semibold" style={{ color: v.score >= 70 ? '#10b981' : v.score >= 40 ? '#f59e0b' : '#ef4444' }}>{v.score}</span>
                    </div>
                    <div className="h-1 mt-1 bg-slate-200 rounded overflow-hidden">
                      <div className="h-full" style={{
                        width: `${v.score}%`,
                        background: v.score >= 70 ? '#10b981' : v.score >= 40 ? '#f59e0b' : '#ef4444',
                      }} />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </CardContent></Card>
      )}

      {/* Alerts + Priorities row */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card className="border-rose-100" data-testid="alerts-panel">
          <CardContent className="p-5">
            <div className="flex justify-between items-center mb-3">
              <h3 className="font-semibold flex items-center gap-2"><AlertTriangle size={16} className="text-rose-500" /> Live Alerts</h3>
              <div className="flex gap-1">
                <Badge className="bg-rose-500">{critical}</Badge>
                <Badge className="bg-amber-500">{warnings}</Badge>
                <Badge className="bg-blue-500">{moderate}</Badge>
              </div>
            </div>
            <div className="space-y-1 max-h-56 overflow-y-auto">
              {sortedInsights.slice(0, 8).map(i => (
                <div key={i.id} className="text-xs p-2 rounded border-l-2 bg-slate-50"
                  style={{ borderColor: SEV_COLOR[i.severity] || '#94a3b8' }}>
                  <p className="font-medium">{i.title}</p>
                  <p className="text-[10px] text-slate-500 mt-0.5">{i.category}</p>
                </div>
              ))}
              {sortedInsights.length === 0 && <p className="text-xs text-slate-400 text-center py-4">All clear.</p>}
            </div>
          </CardContent>
        </Card>

        <Card data-testid="priorities-panel">
          <CardContent className="p-5">
            <h3 className="font-semibold flex items-center gap-2 mb-3"><Sparkles size={16} className="text-indigo-500" /> Today&apos;s Priorities</h3>
            <div className="space-y-2">
              {sortedInsights.slice(0, 5).map(i => (
                <div key={i.id} className="text-xs">
                  <p className="font-medium truncate">{i.title}</p>
                  <div className="flex gap-1 flex-wrap mt-1">
                    {(i.recommendedActions || []).slice(0, 2).map((a, idx) => (
                      <Badge key={idx} variant="outline" className="text-[9px] font-mono">{a.type}</Badge>
                    ))}
                  </div>
                </div>
              ))}
              {sortedInsights.length === 0 && <p className="text-xs text-slate-400 text-center py-4">Nothing urgent — see the briefing.</p>}
            </div>
          </CardContent>
        </Card>

        <Card className="border-amber-100" data-testid="approvals-summary">
          <CardContent className="p-5">
            <h3 className="font-semibold flex items-center gap-2 mb-3"><ShieldCheck size={16} className="text-amber-600" /> Awaiting your review</h3>
            {approvals.length === 0 ? (
              <p className="text-xs text-slate-400 text-center py-6">No pending approvals.</p>
            ) : (
              <div className="space-y-1 max-h-56 overflow-y-auto">
                {approvals.slice(0, 6).map(a => (
                  <div key={a.id} className="text-xs p-2 rounded bg-amber-50 border border-amber-100">
                    <p className="font-medium">{a.actionType.replace(/_/g, ' ')}</p>
                    <p className="text-[10px] text-slate-500">by {a.requestedBy}</p>
                  </div>
                ))}
              </div>
            )}
            <Button size="sm" variant="outline" className="w-full mt-3" onClick={() => window.location.assign('/approvals')} data-testid="cc-approvals-btn">
              Open Approval Queue
            </Button>
          </CardContent>
        </Card>
      </div>

      <Tabs defaultValue="briefing">
        <TabsList>
          <TabsTrigger value="briefing" data-testid="cc-tab-briefing"><Sunrise size={14} className="mr-1" /> Morning Briefing</TabsTrigger>
          <TabsTrigger value="tools" data-testid="cc-tab-tools"><Wrench size={14} className="mr-1" /> Tools &amp; Permissions</TabsTrigger>
        </TabsList>
        <TabsContent value="briefing">
          {briefing && (
            <Card data-testid="briefing-card"><CardContent className="p-6">
              <div className="flex justify-between items-start mb-4">
                <p className="text-xs uppercase tracking-wider text-slate-400">Briefing for {briefing.date}</p>
                <Button size="sm" variant="outline" onClick={regenerateBriefing} data-testid="regen-briefing-btn"><RefreshCw size={12} className="mr-1" /> Regenerate</Button>
              </div>
              <p className="text-slate-700 whitespace-pre-wrap leading-relaxed">{briefing.narrative}</p>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-6 pt-4 border-t text-xs">
                <div><p className="text-slate-500">Forecast Revenue</p><p className="font-semibold text-emerald-600">${briefing.data?.forecastRevenue}</p></div>
                <div><p className="text-slate-500">Bookings Today</p><p className="font-semibold">{briefing.data?.bookingsToday} ({briefing.data?.vipCount} VIP)</p></div>
                <div><p className="text-slate-500">Rostered Staff</p><p className="font-semibold">{briefing.data?.rosteredStaff}</p></div>
                {/* Purple = NUA Agent approved-pending, per NUA_POS_DESIGN_TOKENS.md §6. */}
                <div><p className="text-slate-500">Pending Approvals</p><p className="font-semibold text-[#6d28d9]">{briefing.data?.pendingApprovals}</p></div>
              </div>
            </CardContent></Card>
          )}
        </TabsContent>

        <TabsContent value="tools">
          <Card><CardContent className="p-0" data-testid="tools-table">
            <p className="p-4 text-xs text-slate-500">
              <b>Auto</b> executes immediately. <b>Approval</b> enqueues to /approvals. <b>Disabled</b> blocks NUA from using it.
            </p>
            <table className="w-full text-sm">
              <thead className="bg-slate-50"><tr>
                <th className="p-2 pl-4 text-left text-xs text-slate-500">Tool</th>
                <th className="p-2 text-left text-xs text-slate-500">Module</th>
                <th className="p-2 text-left text-xs text-slate-500">Risk</th>
                <th className="p-2 text-left text-xs text-slate-500">Impact</th>
                <th className="p-2 pr-4 text-left text-xs text-slate-500">Permission</th>
              </tr></thead>
              <tbody>
                {tools.map(t => (
                  <tr key={t.name} className="border-t hover:bg-slate-50" data-testid={`tool-row-${t.name}`}>
                    <td className="p-2 pl-4 font-mono text-xs">{t.name}</td>
                    <td className="p-2">{t.module}</td>
                    <td className="p-2"><Badge className={
                      t.risk === 'high' ? 'bg-rose-500' :
                      t.risk === 'medium' ? 'bg-amber-500' :
                      t.risk === 'critical' ? 'bg-rose-700' : 'bg-emerald-500'
                    }>{t.risk}</Badge></td>
                    <td className="p-2 text-xs text-slate-500">{t.expectedImpact}</td>
                    <td className="p-2 pr-4">
                      <Select value={t.effectivePermission} onValueChange={v => setPermission(t.name, v)}>
                        <SelectTrigger className="w-32" data-testid={`perm-${t.name}`}><SelectValue /></SelectTrigger>
                        <SelectContent>
                          <SelectItem value="auto">Auto</SelectItem>
                          <SelectItem value="approval">Approval</SelectItem>
                          <SelectItem value="disabled">Disabled</SelectItem>
                        </SelectContent>
                      </Select>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent></Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
