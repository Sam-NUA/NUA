import React, { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import { Card, CardContent } from '../components/ui/card';
import { Input } from '../components/ui/input';
import { Badge } from '../components/ui/badge';
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from '../components/ui/select';
import { Button } from '../components/ui/button';
import { History, Search, User, Shield, Clock, RotateCcw, Download, FileCheck } from 'lucide-react';
import { toast } from 'sonner';
import { useAuth } from '../contexts/AuthContext';
import { DialogService } from '../platform';

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const H = () => ({ Authorization: `Bearer ${localStorage.getItem('nua_token')}` });

const ACTION_COLORS = { created: 'bg-emerald-100 text-emerald-700', updated: 'bg-blue-100 text-blue-700', deleted: 'bg-rose-100 text-rose-700', restored: 'bg-purple-100 text-purple-700' };

const IGNORED_DIFF_KEYS = new Set(['_id', 'updatedAt', 'version']);

// Most fields on a real document don't change between before/after — the
// two full JSON panels made you scan the whole document to spot the one
// field that actually moved. This reduces it to just the changed fields.
function diffFields(before, after) {
  const b = before || {};
  const a = after || {};
  const keys = new Set([...Object.keys(b), ...Object.keys(a)]);
  const rows = [];
  keys.forEach(k => {
    if (IGNORED_DIFF_KEYS.has(k)) return;
    const bv = b[k];
    const av = a[k];
    if (JSON.stringify(bv) === JSON.stringify(av)) return;
    rows.push({ key: k, before: bv, after: av });
  });
  return rows.sort((x, y) => x.key.localeCompare(y.key));
}

function formatDiffValue(v) {
  if (v === undefined) return '—';
  if (v === null) return 'null';
  if (typeof v === 'object') return JSON.stringify(v);
  return String(v);
}

export default function AuditLog() {
  const { user } = useAuth();
  const isOwner = user?.role === 'owner';
  const [events, setEvents] = useState([]);
  const [summary, setSummary] = useState(null);
  const [entityType, setEntityType] = useState('');
  const [action, setAction] = useState('');
  const [actor, setActor] = useState('');
  const [expanded, setExpanded] = useState(null);
  const [restoring, setRestoring] = useState(null);
  const [showRaw, setShowRaw] = useState(false);
  const [complianceStart, setComplianceStart] = useState('');
  const [complianceEnd, setComplianceEnd] = useState('');
  const [complianceExporting, setComplianceExporting] = useState(false);

  const load = useCallback(async () => {
    try {
      const params = {};
      if (entityType) params.entity_type = entityType;
      if (action) params.action = action;
      if (actor) params.actor = actor;
      params.limit = 200;
      const [e, s] = await Promise.all([
        axios.get(`${API}/audit/events`, { headers: H(), params }),
        axios.get(`${API}/audit/summary`, { headers: H() }),
      ]);
      setEvents(e.data); setSummary(s.data);
    } catch { toast.error('Failed to load audit log'); }
  }, [entityType, action, actor]);
  useEffect(() => { load(); }, [load]);

  const restoreTo = async (e) => {
    const version = e.before?.version;
    if (!version) return;
    if (!await DialogService.confirm(`Restore ${e.entityType} ${(e.entityId || '').slice(0, 8)} to its state before this change (version ${version})?`)) return;
    setRestoring(e.id);
    try {
      await axios.post(`${API}/audit/restore/${e.entityType}/${e.entityId}/${version}`, {}, { headers: H() });
      toast.success('Restored');
      load();
    } catch (err) { toast.error(err.response?.data?.detail || 'Restore failed'); }
    finally { setRestoring(null); }
  };

  const downloadComplianceExport = async () => {
    setComplianceExporting(true);
    try {
      const params = {};
      if (complianceStart) params.start = complianceStart;
      if (complianceEnd) params.end = complianceEnd;
      const r = await axios.get(`${API}/audit/compliance-export.csv`, { headers: H(), params, responseType: 'blob' });
      const url = URL.createObjectURL(r.data);
      const a = document.createElement('a');
      const label = `${complianceStart || 'all-time'}_to_${complianceEnd || 'now'}`;
      a.href = url; a.download = `compliance-${label}.csv`; a.click();
      URL.revokeObjectURL(url);
      toast.success('Compliance export downloaded');
    } catch (err) { toast.error(err.response?.data?.detail || 'Export failed'); }
    finally { setComplianceExporting(false); }
  };

  return (
    <div className="space-y-6" data-testid="audit-log-page">
      <div>
        <h1 className="text-3xl font-bold flex items-center gap-2"><History className="text-slate-600" /> Universal Audit Log</h1>
        <p className="text-sm text-slate-500 mt-1">Every mutation, everywhere. Filter and drill into the full before/after diff.</p>
      </div>

      {isOwner && (
        <Card className="border-indigo-200 bg-indigo-50/60" data-testid="compliance-export-card">
          <CardContent className="p-4 space-y-3">
            <div className="flex items-center gap-2">
              <FileCheck size={16} className="text-indigo-600" />
              <p className="font-semibold text-sm text-indigo-800">Compliance export</p>
            </div>
            <p className="text-xs text-indigo-700/80">
              Every approval, rule firing, and Ash trust change in one chronological CSV — evidence of exactly
              what an autonomous action did, who requested it, and who (or what) decided it.
            </p>
            <div className="flex flex-wrap items-end gap-2">
              <div>
                <label className="text-[10px] uppercase tracking-wider text-indigo-600 block mb-1">From</label>
                <Input type="date" value={complianceStart} onChange={e => setComplianceStart(e.target.value)}
                  className="w-40" data-testid="compliance-start-date" />
              </div>
              <div>
                <label className="text-[10px] uppercase tracking-wider text-indigo-600 block mb-1">To</label>
                <Input type="date" value={complianceEnd} onChange={e => setComplianceEnd(e.target.value)}
                  className="w-40" data-testid="compliance-end-date" />
              </div>
              <Button size="sm" onClick={downloadComplianceExport} disabled={complianceExporting}
                data-testid="compliance-export-btn">
                <Download size={12} className="mr-1" /> {complianceExporting ? 'Exporting…' : 'Download CSV'}
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {summary && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <SmallStat label="Total Events" value={summary.total} icon={History} testid="kpi-total-events" />
          <SmallStat label="Entity Types" value={summary.byEntity.length} icon={Shield} testid="kpi-entity-types" />
          <SmallStat label="Actors" value={summary.byActor.length} icon={User} testid="kpi-actors" />
          <SmallStat label="Most active" value={summary.byActor[0]?._id || '—'} icon={Clock} small testid="kpi-most-active" />
        </div>
      )}

      <Card><CardContent className="p-4 grid grid-cols-1 md:grid-cols-4 gap-2">
        <Input placeholder="Entity type (customer, product, transaction…)" value={entityType} onChange={e => setEntityType(e.target.value)} data-testid="filter-entity" />
        <Select value={action} onValueChange={setAction}>
          <SelectTrigger data-testid="filter-action"><SelectValue placeholder="Any action" /></SelectTrigger>
          <SelectContent>
            <SelectItem value=" ">Any action</SelectItem>
            <SelectItem value="created">Created</SelectItem>
            <SelectItem value="updated">Updated</SelectItem>
            <SelectItem value="deleted">Deleted</SelectItem>
            <SelectItem value="restored">Restored</SelectItem>
            {/* Coursing actions. "Who voided what tonight" is the question
                this page exists to answer, and it had no way to ask it. */}
            <SelectItem value="course_void">Course voided</SelectItem>
            <SelectItem value="course_fired">Course fired</SelectItem>
          </SelectContent>
        </Select>
        <Input placeholder="Actor email…" value={actor} onChange={e => setActor(e.target.value)} data-testid="filter-actor" />
        <Button onClick={load} data-testid="filter-apply"><Search size={14} className="mr-1" /> Filter</Button>
      </CardContent></Card>

      {/* One tap for the shrinkage question, rather than remembering that
          voids live under entity type "kitchen_order". */}
      <div className="flex gap-2 flex-wrap">
        <Button size="sm" variant="outline" className="text-xs"
          onClick={() => { setEntityType('kitchen_order'); setAction('course_void'); setActor(''); }}
          data-testid="preset-voids">
          Voids tonight
        </Button>
        <Button size="sm" variant="outline" className="text-xs"
          onClick={() => { setEntityType('kitchen_order'); setAction(''); setActor(''); }}
          data-testid="preset-coursing">
          All coursing activity
        </Button>
        <Button size="sm" variant="ghost" className="text-xs"
          onClick={() => { setEntityType(''); setAction(''); setActor(''); }}
          data-testid="preset-clear">
          Clear filters
        </Button>
      </div>

      <Card><CardContent className="p-0">
        <table className="w-full text-sm">
          <thead className="bg-slate-50"><tr>
            <th className="p-2 pl-4 text-left text-xs text-slate-500">Time</th>
            <th className="p-2 text-left text-xs text-slate-500">Actor</th>
            <th className="p-2 text-left text-xs text-slate-500">Action</th>
            <th className="p-2 text-left text-xs text-slate-500">Entity</th>
            <th className="p-2 text-left text-xs text-slate-500">Memo</th>
            <th className="p-2 pr-4 text-left text-xs text-slate-500">Device / IP</th>
          </tr></thead>
          <tbody>
            {events.map(e => (
              <React.Fragment key={e.id}>
                <tr className="border-t hover:bg-slate-50 cursor-pointer" onClick={() => { setExpanded(expanded === e.id ? null : e.id); setShowRaw(false); }}>
                  <td className="p-2 pl-4 text-xs">{new Date(e.ts).toLocaleString()}</td>
                  <td className="p-2 text-xs font-mono">{e.actor}</td>
                  <td className="p-2"><Badge className={`text-[10px] ${ACTION_COLORS[e.action] || 'bg-slate-100'}`}>{e.action}</Badge></td>
                  <td className="p-2 text-xs"><span className="font-mono">{e.entityType}</span> · {(e.entityId || '').slice(0, 8)}</td>
                  <td className="p-2 text-xs text-slate-500 truncate max-w-xs">{e.memo}</td>
                  <td className="p-2 pr-4 text-[10px] text-slate-400">{(e.device || '?').slice(0, 40)} · {e.ip}</td>
                </tr>
                {expanded === e.id && (
                  <tr className="border-t bg-slate-50/70">
                    <td colSpan="6" className="p-4">
                      {(() => {
                        const rows = diffFields(e.before, e.after);
                        if (rows.length === 0) {
                          return <p className="text-xs text-slate-400">No field-level differences (only ignored fields like version/updatedAt changed).</p>;
                        }
                        return (
                          <table className="w-full text-[11px]" data-testid={`diff-table-${e.id}`}>
                            <thead><tr className="text-slate-500">
                              <th className="text-left font-medium pb-1 pr-3">Field</th>
                              <th className="text-left font-medium pb-1 pr-3">Before</th>
                              <th className="text-left font-medium pb-1">After</th>
                            </tr></thead>
                            <tbody>
                              {rows.map(r => (
                                <tr key={r.key} className="border-t border-slate-200">
                                  <td className="py-1 pr-3 font-mono text-slate-600">{r.key}</td>
                                  <td className="py-1 pr-3 text-rose-600 bg-rose-50/50 max-w-xs truncate">{formatDiffValue(r.before)}</td>
                                  <td className="py-1 text-emerald-700 bg-emerald-50/50 max-w-xs truncate">{formatDiffValue(r.after)}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        );
                      })()}
                      <button className="text-[11px] text-blue-600 hover:underline mt-2"
                        onClick={() => setShowRaw(s => !s)} data-testid={`toggle-raw-${e.id}`}>
                        {showRaw ? 'Hide raw JSON' : 'Show raw JSON'}
                      </button>
                      {showRaw && (
                        <div className="grid md:grid-cols-2 gap-3 text-[11px] mt-2">
                          <div>
                            <p className="font-medium mb-1">Before</p>
                            <pre className="bg-white border rounded p-2 overflow-auto max-h-64">{JSON.stringify(e.before, null, 2)}</pre>
                          </div>
                          <div>
                            <p className="font-medium mb-1">After</p>
                            <pre className="bg-white border rounded p-2 overflow-auto max-h-64">{JSON.stringify(e.after, null, 2)}</pre>
                          </div>
                        </div>
                      )}
                      {e.before?.version && (
                        <Button size="sm" variant="outline" className="mt-3 text-xs" disabled={restoring === e.id}
                          onClick={() => restoreTo(e)} data-testid={`restore-${e.id}`}>
                          <RotateCcw size={12} className="mr-1" />
                          {restoring === e.id ? 'Restoring...' : `Restore to before this change (v${e.before.version})`}
                        </Button>
                      )}
                    </td>
                  </tr>
                )}
              </React.Fragment>
            ))}
          </tbody>
        </table>
        {events.length === 0 && <p className="text-center text-slate-400 py-8">No events match your filters.</p>}
      </CardContent></Card>
    </div>
  );
}

const SmallStat = ({ label, value, icon: Icon, small, testid }) => (
  <Card><CardContent className="p-4 flex justify-between items-center" data-testid={testid}>
    <div>
      <p className="text-xs uppercase tracking-wider text-slate-500">{label}</p>
      <p className={`font-bold mt-1 ${small ? 'text-sm' : 'text-2xl'}`}>{value}</p>
    </div>
    <Icon size={28} className="opacity-30 text-slate-500" />
  </CardContent></Card>
);
