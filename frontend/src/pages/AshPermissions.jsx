import React, { useEffect, useState, useCallback, useMemo } from 'react';
import axios from 'axios';
import { Card, CardContent } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Input } from '../components/ui/input';
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from '../components/ui/select';
import { toast } from 'sonner';
import { useAuth } from '../contexts/AuthContext';
import { ShieldCheck, RefreshCw, Search, Lock, Zap, Eye, Sparkles, TrendingUp, Flag, Undo2, History } from 'lucide-react';
import { DialogService, SecureStorageService } from '../platform';

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const H = async () => ({ Authorization: `Bearer ${await SecureStorageService.getToken()}` });

const RISK_BG = { low: 'bg-emerald-500', medium: 'bg-amber-500', high: 'bg-rose-500', critical: 'bg-rose-700' };
const RISK_ORDER = { low: 0, medium: 1, high: 2, critical: 3 };

const PERMISSION_DESCRIPTION = {
  auto: 'NUA runs this tool immediately without asking.',
  approval: 'NUA queues this tool in /approvals for you to confirm.',
  disabled: 'NUA cannot use this tool at all.',
};

const PERMISSION_ICON = { auto: Zap, approval: Eye, disabled: Lock };
const PERMISSION_TONE = {
  auto: 'text-emerald-600 bg-emerald-50 border-emerald-200',
  approval: 'text-amber-600 bg-amber-50 border-amber-200',
  disabled: 'text-rose-600 bg-rose-50 border-rose-200',
};

export default function AshPermissions() {
  const { user } = useAuth();
  const isOwner = user?.role === 'owner';
  const [tools, setTools] = useState([]);
  const [refreshing, setRefreshing] = useState(false);
  const [query, setQuery] = useState('');
  const [moduleFilter, setModuleFilter] = useState('all');
  const [riskFilter, setRiskFilter] = useState('all');
  // Graduated trust: tools that have earned their way to a promotion suggestion.
  const [suggestions, setSuggestions] = useState([]);
  const [dismissed, setDismissed] = useState(() => new Set());
  const [promoting, setPromoting] = useState(() => new Set());
  // Shadow-audit review feed: recent auto-tier executions an owner can
  // spot-check and, if one was wrong, flag for instant demotion.
  const [executions, setExecutions] = useState([]);
  const [flagging, setFlagging] = useState(() => new Set());
  const [showAllExecutions, setShowAllExecutions] = useState(false);

  const load = useCallback(async () => {
    setRefreshing(true);
    try {
      const [toolsRes, suggRes, execRes] = await Promise.allSettled([
        axios.get(`${API}/nua/tools`, { headers: await H() }),
        axios.get(`${API}/nua/trust/suggestions`, { headers: await H() }),
        axios.get(`${API}/nua/tools/auto-executions`, { headers: await H(), params: { limit: 30 } }),
      ]);
      if (toolsRes.status === 'fulfilled') setTools(toolsRes.value.data);
      else toast.error('Failed to load tools');
      if (suggRes.status === 'fulfilled') setSuggestions(suggRes.value.data);
      if (execRes.status === 'fulfilled') setExecutions(execRes.value.data);
    } finally { setRefreshing(false); }
  }, []);

  const flagExecution = async (auditId, toolName, undo) => {
    setFlagging(s => new Set(s).add(auditId));
    try {
      const { data } = await axios.post(`${API}/nua/tools/executions/${auditId}/flag`,
        { reason: 'Flagged from the auto-execution review feed', undo },
        { headers: await H() });
      toast.success(`${data.label || toolName} demoted back to Approval${data.undo?.undone ? ' — action undone' : ''}`);
      setExecutions(rows => rows.map(r => r.auditId === auditId ? { ...r, flagged: true } : r));
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Failed to flag this action');
    } finally {
      setFlagging(s => { const n = new Set(s); n.delete(auditId); return n; });
    }
  };

  useEffect(() => { load(); }, [load]);

  const setPermission = async (toolName, permission) => {
    try {
      await axios.put(`${API}/nua/tools/${toolName}/permission`, { permission }, { headers: await H() });
      setTools(ts => ts.map(t => t.name === toolName ? { ...t, effectivePermission: permission } : t));
      toast.success(`${toolName} \u2192 ${permission}`);
    } catch { toast.error('Failed'); }
  };

  const promoteTool = async (toolName) => {
    setPromoting(s => new Set(s).add(toolName));
    try {
      await axios.post(`${API}/nua/tools/${toolName}/promote`, {}, { headers: await H() });
      toast.success(`${toolName} promoted to Auto \u2014 earned it with a clean streak`);
      setSuggestions(s => s.filter(x => x.toolName !== toolName));
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Promotion failed \u2014 the streak may have reset');
      load();
    } finally {
      setPromoting(s => { const n = new Set(s); n.delete(toolName); return n; });
    }
  };

  const modules = useMemo(() => Array.from(new Set(tools.map(t => t.module))).sort(), [tools]);

  const filtered = tools.filter(t =>
    (moduleFilter === 'all' || t.module === moduleFilter) &&
    (riskFilter === 'all' || t.risk === riskFilter) &&
    (query.trim() === '' || t.name.toLowerCase().includes(query.toLowerCase()) || t.label.toLowerCase().includes(query.toLowerCase()))
  );

  const grouped = useMemo(() => {
    const map = {};
    filtered.forEach(t => {
      map[t.module] = map[t.module] || [];
      map[t.module].push(t);
    });
    Object.values(map).forEach(arr => arr.sort((a, b) => (RISK_ORDER[b.risk] || 0) - (RISK_ORDER[a.risk] || 0)));
    return map;
  }, [filtered]);

  const batchSet = async (moduleName, permission) => {
    const targets = tools.filter(t => t.module === moduleName);
    if (!targets.length) return;
    if (!await DialogService.confirm(`Set all ${targets.length} ${moduleName} tools to "${permission}"?`)) return;
    for (const t of targets) {
      try {
        await axios.put(`${API}/nua/tools/${t.name}/permission`, { permission }, { headers: await H() });
      } catch { /* skip */ }
    }
    toast.success(`${moduleName} \u2192 ${permission}`);
    load();
  };

  const stats = useMemo(() => {
    const s = { auto: 0, approval: 0, disabled: 0 };
    tools.forEach(t => { s[t.effectivePermission] = (s[t.effectivePermission] || 0) + 1; });
    return s;
  }, [tools]);

  return (
    <div className="space-y-6" data-testid="ash-permissions-page">
      <div className="flex justify-between items-center flex-wrap gap-3">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-2">
            <ShieldCheck className="text-indigo-600" /> NUA Permissions
          </h1>
          <p className="text-sm text-slate-500 mt-1">Owner controls for every capability NUA can invoke. Approval gates route to the Approval Queue.</p>
        </div>
        <Button variant="outline" onClick={load} disabled={refreshing} data-testid="perms-refresh-btn">
          <RefreshCw size={14} className={`mr-1.5 ${refreshing ? 'animate-spin' : ''}`} /> Refresh
        </Button>
      </div>

      {/* Graduated trust: tools with a clean-enough streak to suggest promoting */}
      {suggestions.filter(s => !dismissed.has(s.toolName)).length > 0 && (
        <Card className="border-emerald-200 bg-emerald-50/60" data-testid="trust-suggestions-banner">
          <CardContent className="p-4 space-y-3">
            <div className="flex items-center gap-2">
              <Sparkles size={16} className="text-emerald-600" />
              <p className="font-semibold text-sm text-emerald-800">
                NUA earned trust on {suggestions.filter(s => !dismissed.has(s.toolName)).length} tool
                {suggestions.filter(s => !dismissed.has(s.toolName)).length === 1 ? '' : 's'} this week
              </p>
            </div>
            {suggestions.filter(s => !dismissed.has(s.toolName)).map(s => (
              <div key={s.toolName} className="flex items-center justify-between gap-3 bg-white rounded-lg border border-emerald-200 px-3 py-2"
                data-testid={`suggestion-${s.toolName}`}>
                <div className="min-w-0">
                  <p className="text-sm font-medium truncate">{s.label}</p>
                  <p className="text-xs text-slate-500">
                    {s.consecutiveApproved}/{s.minStreak} approved with no rejections
                    {s.streakStartedAt ? ` since ${new Date(s.streakStartedAt).toLocaleDateString()}` : ''}
                  </p>
                </div>
                <div className="flex gap-2 flex-shrink-0">
                  <Button size="sm" variant="ghost" onClick={() => setDismissed(d => new Set(d).add(s.toolName))}
                    data-testid={`dismiss-suggestion-${s.toolName}`}>Not yet</Button>
                  {/* POST /nua/tools/{tool}/promote is intentionally gated
                      tighter than the rest of this page (owner-only) — a
                      manager could see the suggestion but got a confusing
                      403 on click. */}
                  {isOwner ? (
                    <Button size="sm" className="bg-emerald-600 hover:bg-emerald-700 text-white"
                      disabled={promoting.has(s.toolName)} onClick={() => promoteTool(s.toolName)}
                      data-testid={`promote-${s.toolName}`}>
                      <TrendingUp size={14} className="mr-1" /> {promoting.has(s.toolName) ? 'Promoting…' : 'Promote to Auto'}
                    </Button>
                  ) : (
                    <span className="text-[11px] text-slate-400 italic">Owner only</span>
                  )}
                </div>
              </div>
            ))}
            <p className="text-[11px] text-emerald-700/70">
              A single rejection resets the streak to zero — losing trust is instant, earning it back takes a fresh clean run.
            </p>
          </CardContent>
        </Card>
      )}

      {/* Stat summary */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {['auto', 'approval', 'disabled'].map(k => {
          const Icon = PERMISSION_ICON[k];
          return (
            <Card key={k} className={`border ${PERMISSION_TONE[k]}`} data-testid={`stat-${k}`}>
              <CardContent className="p-5 flex items-center gap-4">
                <div className={`h-10 w-10 rounded-full flex items-center justify-center ${PERMISSION_TONE[k]}`}>
                  <Icon size={20} />
                </div>
                <div>
                  <p className="text-3xl font-bold">{stats[k] || 0}</p>
                  <p className="text-xs uppercase tracking-wider text-slate-500">{k}</p>
                  <p className="text-[10px] text-slate-500 mt-0.5">{PERMISSION_DESCRIPTION[k]}</p>
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>

      {/* Shadow-audit review feed: what auto-tier tools actually did */}
      {executions.length > 0 && (
        <Card data-testid="auto-executions-feed">
          <CardContent className="p-4 space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <History size={16} className="text-slate-500" />
                <p className="font-semibold text-sm">Recent auto actions</p>
                <span className="text-xs text-slate-400">
                  {executions.filter(e => !e.flagged).length} unreviewed of {executions.length}
                </span>
              </div>
              {executions.length > 5 && (
                <Button size="sm" variant="ghost" onClick={() => setShowAllExecutions(v => !v)}
                  data-testid="toggle-executions">
                  {showAllExecutions ? 'Show less' : `Show all ${executions.length}`}
                </Button>
              )}
            </div>
            <p className="text-[11px] text-slate-500">
              Every capability that ran on Auto is logged here as it happens — nothing here needs your
              approval, but flagging one as wrong instantly demotes that tool back to Approval and resets
              its trust streak.
            </p>
            <div className="space-y-2">
              {(showAllExecutions ? executions : executions.slice(0, 5)).map(e => (
                <div key={e.auditId}
                  className={`flex items-start justify-between gap-3 rounded-lg border px-3 py-2 ${e.flagged ? 'bg-rose-50 border-rose-200' : 'bg-white border-slate-200'}`}
                  data-testid={`execution-${e.auditId}`}>
                  <div className="min-w-0">
                    <p className="text-sm font-medium truncate">
                      {e.label} <span className="text-slate-400 font-normal">· {e.actor || 'system'}</span>
                    </p>
                    <p className="text-xs text-slate-500 truncate">
                      {e.outcome && typeof e.outcome === 'object' && e.outcome.error
                        ? <span className="text-rose-600">Failed: {e.outcome.error}</span>
                        : JSON.stringify(e.outcome || {})}
                    </p>
                    <p className="text-[10px] text-slate-400 mt-0.5">
                      {e.ts ? new Date(e.ts).toLocaleString() : ''}
                      {e.flagged && <span className="text-rose-600 font-medium"> · flagged, demoted to Approval</span>}
                    </p>
                  </div>
                  {!e.flagged && isOwner && (
                    <div className="flex gap-1.5 flex-shrink-0">
                      {e.rollbackAvailable && (
                        <Button size="sm" variant="outline" className="text-xs"
                          disabled={flagging.has(e.auditId)}
                          onClick={() => flagExecution(e.auditId, e.toolName, true)}
                          data-testid={`undo-${e.auditId}`}>
                          <Undo2 size={12} className="mr-1" /> Undo & flag
                        </Button>
                      )}
                      <Button size="sm" variant="outline" className="text-xs text-rose-600 border-rose-200 hover:bg-rose-50"
                        disabled={flagging.has(e.auditId)}
                        onClick={() => flagExecution(e.auditId, e.toolName, false)}
                        data-testid={`flag-${e.auditId}`}>
                        <Flag size={12} className="mr-1" /> Flag as wrong
                      </Button>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Filters */}
      <Card>
        <CardContent className="p-4 flex flex-wrap gap-3">
          <div className="relative flex-1 min-w-[200px]">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <Input placeholder="Search tools\u2026" value={query} onChange={e => setQuery(e.target.value)}
              className="pl-9" data-testid="perms-search" />
          </div>
          <Select value={moduleFilter} onValueChange={setModuleFilter}>
            <SelectTrigger className="w-40" data-testid="module-filter"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All modules</SelectItem>
              {modules.map(m => <SelectItem key={m} value={m}>{m}</SelectItem>)}
            </SelectContent>
          </Select>
          <Select value={riskFilter} onValueChange={setRiskFilter}>
            <SelectTrigger className="w-32" data-testid="risk-filter"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All risks</SelectItem>
              <SelectItem value="low">Low</SelectItem>
              <SelectItem value="medium">Medium</SelectItem>
              <SelectItem value="high">High</SelectItem>
              <SelectItem value="critical">Critical</SelectItem>
            </SelectContent>
          </Select>
        </CardContent>
      </Card>

      {/* Tool tables grouped by module */}
      {Object.entries(grouped).map(([modName, mods]) => (
        <Card key={modName} data-testid={`module-card-${modName}`}>
          <CardContent className="p-0">
            <div className="flex justify-between items-center p-4 border-b">
              <div>
                <h3 className="font-semibold">{modName}</h3>
                <p className="text-xs text-slate-500">{mods.length} tools</p>
              </div>
              <div className="flex gap-1">
                <Button size="sm" variant="outline" onClick={() => batchSet(modName, 'auto')} data-testid={`batch-auto-${modName}`}>All auto</Button>
                <Button size="sm" variant="outline" onClick={() => batchSet(modName, 'approval')} data-testid={`batch-approval-${modName}`}>All approval</Button>
                <Button size="sm" variant="outline" onClick={() => batchSet(modName, 'disabled')} data-testid={`batch-disabled-${modName}`}>All disabled</Button>
              </div>
            </div>
            <table className="w-full text-sm">
              <thead className="bg-slate-50">
                <tr className="text-xs text-slate-500 uppercase tracking-wider">
                  <th className="p-2 pl-4 text-left">Capability</th>
                  <th className="p-2 text-left">Risk</th>
                  <th className="p-2 text-left">Impact</th>
                  <th className="p-2 text-left">Default</th>
                  <th className="p-2 text-left">Trust</th>
                  <th className="p-2 pr-4 text-left">Owner override</th>
                </tr>
              </thead>
              <tbody>
                {mods.map(t => (
                  <tr key={t.name} className="border-t hover:bg-slate-50" data-testid={`perm-row-${t.name}`}>
                    <td className="p-2 pl-4">
                      <p className="font-medium text-sm">{t.label}</p>
                      <p className="font-mono text-[10px] text-slate-500">{t.name}</p>
                    </td>
                    <td className="p-2"><Badge className={RISK_BG[t.risk] || 'bg-slate-500'}>{t.risk}</Badge></td>
                    <td className="p-2 text-xs text-slate-500">{t.expectedImpact}</td>
                    <td className="p-2 text-xs text-slate-500">{t.defaultPermission}</td>
                    <td className="p-2 text-xs" data-testid={`trust-${t.name}`}>
                      {!t.trust ? (
                        <span className="text-slate-300">—</span>
                      ) : t.promotedBy === 'trust' ? (
                        <span className="text-emerald-600 font-medium flex items-center gap-1"><Sparkles size={11} /> Earned</span>
                      ) : t.trust.consecutiveApproved > 0 ? (
                        <span className={t.trust.eligibleSince ? 'text-emerald-600 font-medium' : 'text-slate-500'}>
                          {t.trust.consecutiveApproved}/{t.trust.minStreak} clean
                        </span>
                      ) : (
                        <span className="text-slate-300">—</span>
                      )}
                    </td>
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
          </CardContent>
        </Card>
      ))}
      {filtered.length === 0 && (
        <Card><CardContent className="p-12 text-center text-sm text-slate-500">
          No tools match those filters.
        </CardContent></Card>
      )}
    </div>
  );
}
