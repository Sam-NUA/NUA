import React, { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import { Card, CardContent } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '../components/ui/tabs';
import { toast } from 'sonner';
import { Brain, Sparkles, AlertTriangle, TrendingDown, DollarSign, Users, ChefHat, Package, CloudRain, CalendarCheck, ShoppingCart, Clock, Heart, UserX, LineChart, FileText, Play, X as XIcon } from 'lucide-react';
import { SecureStorageService } from '../platform';

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const H = async () => ({ Authorization: `Bearer ${await SecureStorageService.getToken()}` });

const CAT_META = {
  staffing:         { label: 'Staffing',           icon: Users,        color: '#3b82f6' },
  theft:            { label: 'Theft',              icon: AlertTriangle, color: '#dc2626' },
  fraud:            { label: 'Fraud',              icon: AlertTriangle, color: '#ef4444' },
  pricing:          { label: 'Pricing',            icon: DollarSign,   color: '#0ea5e9' },
  promotion:        { label: 'Promotions',         icon: Sparkles,     color: '#a855f7' },
  waste:            { label: 'Food Waste',         icon: TrendingDown, color: '#f59e0b' },
  labour:           { label: 'Labour Costs',       icon: Clock,        color: '#eab308' },
  menu:             { label: 'Menu Performance',   icon: ChefHat,      color: '#f97316' },
  weather:          { label: 'Weather',            icon: CloudRain,    color: '#38bdf8' },
  demand:           { label: 'Demand Forecast',    icon: CalendarCheck, color: '#22c55e' },
  purchasing:       { label: 'Purchasing',         icon: ShoppingCart, color: '#8b5cf6' },
  roster:           { label: 'Roster',             icon: Users,        color: '#ec4899' },
  burnout:          { label: 'Staff Burnout',      icon: Heart,        color: '#f43f5e' },
  churn:            { label: 'Customer Churn',     icon: UserX,        color: '#64748b' },
  menu_engineering: { label: 'Menu Engineering',   icon: LineChart,    color: '#0d9488' },
  summary:          { label: 'Weekly Summary',     icon: FileText,     color: '#6366f1' },
};

const SEV_COLORS = { info: 'bg-slate-100 text-slate-700', notice: 'bg-blue-100 text-blue-700', warning: 'bg-amber-100 text-amber-700', high: 'bg-rose-100 text-rose-700' };

export default function AshDashboard() {
  const [insights, setInsights] = useState([]);
  const [summary, setSummary] = useState(null);
  const [caps, setCaps] = useState([]);
  const [tab, setTab] = useState('all');
  const [busy, setBusy] = useState(false);
  const [running, setRunning] = useState(false);
  const [digest, setDigest] = useState(null);

  const load = useCallback(async () => {
    try {
      const [i, s, c] = await Promise.all([
        axios.get(`${API}/nua/insights?limit=200`, { headers: await H() }),
        axios.get(`${API}/nua/insights/summary`, { headers: await H() }),
        axios.get(`${API}/nua/capabilities`, { headers: await H() }),
      ]);
      setInsights(i.data); setSummary(s.data); setCaps(c.data.capabilities || []);
    } catch { toast.error('Failed to load NUA insights'); }
  }, []);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    H().then(h => axios.get(`${API}/nua/scheduler/status`, { headers: h }).then(r => setDigest(r.data)).catch(() => {}));
  }, []);

  const run = async (includeSummary) => {
    setRunning(true);
    try {
      const r = await axios.post(`${API}/nua/run?include_summary=${includeSummary}`, {}, { headers: await H() });
      toast.success(`NUA generated ${r.data.generated} insight(s) across ${Object.keys(r.data.perCategory).length} categories`);
      load();
    } catch (e) { toast.error(e.response?.data?.detail || 'NUA run failed'); }
    finally { setRunning(false); }
  };

  const dismiss = async (id) => {
    setBusy(true);
    try { await axios.post(`${API}/nua/insights/${id}/dismiss`, {}, { headers: await H() }); load(); }
    catch { toast.error('Failed'); }
    finally { setBusy(false); }
  };

  const categories = Array.from(new Set(insights.map(i => i.category)));
  const filtered = tab === 'all' ? insights : insights.filter(i => i.category === tab);

  return (
    <div className="space-y-6" data-testid="ash-dashboard">
      <div className="flex justify-between items-start flex-wrap gap-3">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-2">
            <Brain className="text-indigo-500" /> NUA — Autonomous Operating Layer
          </h1>
          <p className="text-sm text-slate-500 mt-1">16 always-on jobs continuously scanning inventory, staff, customers, kitchen, weather &amp; finance.</p>
          {digest && (
            <p className="text-xs text-slate-400 mt-1" data-testid="digest-status">
              {digest.lastDigest
                ? `Last digest sent ${new Date(digest.lastDigest.sentAt).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}`
                : 'No digest sent yet'}
              {digest.enabled ? ` · hourly scan every ${Math.round(digest.hourlyIntervalSeconds / 60)}m` : ' · scheduler disabled'}
            </p>
          )}
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => run(true)} disabled={running} data-testid="ash-summary-btn">
            <FileText size={14} className="mr-1.5" /> Weekly Summary
          </Button>
          <Button onClick={() => run(false)} disabled={running} data-testid="ash-run-btn">
            <Play size={14} className="mr-1.5" /> {running ? 'Scanning…' : 'Run NUA Now'}
          </Button>
        </div>
      </div>

      {summary && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <KPI label="Active Insights" value={summary.total} color="text-indigo-600" icon={Brain} />
          <KPI label="High Severity" value={summary.high} color="text-rose-600" icon={AlertTriangle} />
          <KPI label="Warnings" value={summary.warning} color="text-amber-600" icon={AlertTriangle} />
          <KPI label="Categories Watched" value={caps.length} sub="always on" color="text-emerald-600" icon={Sparkles} />
        </div>
      )}

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList className="flex-wrap">
          <TabsTrigger value="all" data-testid="ash-tab-all">All ({insights.length})</TabsTrigger>
          {categories.map(c => (
            <TabsTrigger key={c} value={c} data-testid={`ash-tab-${c}`}>
              {CAT_META[c]?.label || c} ({insights.filter(i => i.category === c).length})
            </TabsTrigger>
          ))}
        </TabsList>

        <TabsContent value={tab}>
          {filtered.length === 0 ? (
            <Card className="border-dashed"><CardContent className="p-10 text-center">
              <Brain size={40} className="mx-auto mb-3 text-slate-300" />
              <p className="text-slate-500 mb-4">No active insights. NUA is watching — click "Run NUA Now" to scan.</p>
              <Button onClick={() => run(false)} disabled={running} data-testid="empty-run-ash"><Play size={14} className="mr-1" /> Run NUA</Button>
            </CardContent></Card>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {filtered.map(ins => {
                const meta = CAT_META[ins.category] || { label: ins.category, icon: Brain, color: '#64748b' };
                const Icon = meta.icon;
                return (
                  <Card key={ins.id} className="border-0 shadow-sm" data-testid={`insight-${ins.id}`}>
                    <CardContent className="p-5 space-y-3">
                      <div className="flex items-start gap-3">
                        <div className="rounded-lg p-2 shrink-0" style={{ background: `${meta.color}18`, color: meta.color }}>
                          <Icon size={18} />
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center justify-between gap-2">
                            <h3 className="font-semibold text-sm">{ins.title}</h3>
                            <Badge className={`text-[10px] ${SEV_COLORS[ins.severity] || SEV_COLORS.info}`}>{ins.severity}</Badge>
                          </div>
                          <p className="text-xs text-slate-500 mt-1">{ins.body}</p>
                          {(ins.recommendedActions || []).length > 0 && (
                            <div className="mt-3 flex flex-wrap gap-1">
                              {ins.recommendedActions.map((a, i) => (
                                <Badge key={i} variant="outline" className="text-[10px] font-mono">{a.type}</Badge>
                              ))}
                            </div>
                          )}
                          <div className="mt-3 flex justify-between items-center">
                            <span className="text-[10px] text-slate-400">{new Date(ins.createdAt).toLocaleString()}</span>
                            <Button size="sm" variant="ghost" className="text-slate-400" onClick={() => dismiss(ins.id)} disabled={busy} data-testid={`dismiss-${ins.id}`}>
                              <XIcon size={12} /> Dismiss
                            </Button>
                          </div>
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                );
              })}
            </div>
          )}
        </TabsContent>
      </Tabs>

      <Card><CardContent className="p-5">
        <h3 className="text-sm font-semibold mb-3">What NUA watches for</h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
          {caps.map(c => {
            const meta = CAT_META[c.key] || { icon: Brain, color: '#64748b' };
            const Icon = meta.icon;
            return (
              <div key={c.key} className="flex items-center gap-2 p-2 rounded border bg-slate-50/70">
                <div className="p-1.5 rounded" style={{ background: `${meta.color}18`, color: meta.color }}>
                  <Icon size={12} />
                </div>
                <span className="text-xs">{c.label}</span>
              </div>
            );
          })}
        </div>
      </CardContent></Card>
    </div>
  );
}

const KPI = ({ label, value, sub, color, icon: Icon }) => (
  <Card><CardContent className="p-4">
    <div className="flex justify-between items-center">
      <div>
        <p className="text-xs uppercase tracking-wider text-slate-500">{label}</p>
        <p className={`text-2xl font-bold mt-1 ${color}`}>{value}</p>
        {sub && <p className="text-[10px] text-slate-500">{sub}</p>}
      </div>
      <Icon className={`opacity-30 ${color}`} size={30} />
    </div>
  </CardContent></Card>
);
