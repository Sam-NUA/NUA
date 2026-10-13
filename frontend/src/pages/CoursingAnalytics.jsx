import React, { useEffect, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Timer, Flame, BellRing, AlertTriangle, DoorClosed, Loader2 } from 'lucide-react';
import { useTheme } from '../contexts/ThemeContext';
import { coursingAPI } from '../services/api';
import { toast } from 'sonner';
import { DialogService } from '../platform';

const WINDOWS = [
  { days: 1, label: 'Today' },
  { days: 7, label: '7 days' },
  { days: 30, label: '30 days' },
];

/** Minutes -> "4m 30s", or a dash when there's no sample. */
function fmt(mins) {
  if (mins === null || mins === undefined) return '—';
  const m = Math.floor(mins);
  const s = Math.round((mins - m) * 60);
  return s ? `${m}m ${s}s` : `${m}m`;
}

/**
 * Amber/red thresholds for time at the pass. Food waiting under a lamp is the
 * expensive failure, so this is the only metric carrying a judgement — held
 * and cook times are venue-specific and shown neutrally.
 */
function passTone(mins) {
  if (mins === null || mins === undefined) return 'text-gray-400';
  if (mins >= 5) return 'text-red-600';
  if (mins >= 2) return 'text-amber-600';
  return 'text-emerald-600';
}

/**
 * What's still open right now, before the overnight sweep silently cancels
 * it with no report. Lets a manager close the night deliberately — on the
 * record, with tables released — instead of tomorrow's staff finding a
 * floor plan full of last night's tables.
 */
function EndOfServicePanel() {
  const { theme } = useTheme();
  const [eos, setEos] = useState(null);
  const [closing, setClosing] = useState(false);

  const load = () => {
    coursingAPI.endOfService().then(r => setEos(r.data)).catch(() => {});
  };
  useEffect(() => { load(); }, []);

  const handleClose = async () => {
    if (!await DialogService.confirm(`Close out ${eos.openCount} open ticket${eos.openCount === 1 ? '' : 's'} and release their tables?`)) return;
    setClosing(true);
    try {
      const r = await coursingAPI.closeService('closed at end of service');
      toast.success(`Closed ${r.data.closed.length} ticket${r.data.closed.length === 1 ? '' : 's'}, released ${r.data.tablesFreed.length} table${r.data.tablesFreed.length === 1 ? '' : 's'}`);
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Could not close out service');
    } finally {
      setClosing(false);
    }
  };

  if (!eos || eos.openCount === 0) return null;

  return (
    <Card className="border-amber-200" data-testid="end-of-service-panel">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm flex items-center justify-between">
          <span className="flex items-center gap-1.5"><DoorClosed size={14} className="text-amber-600" /> End of service — {eos.openCount} still open</span>
          <Button size="sm" variant="outline" onClick={handleClose} disabled={closing} data-testid="close-service-btn">
            {closing ? <Loader2 size={13} className="mr-1 animate-spin" /> : null} Close out
          </Button>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <p className="text-xs text-gray-500 mb-2">
          Cancelled at close instead of silently swept overnight — the reason and tables released are kept on the record.
        </p>
        <div className="space-y-1">
          {eos.openTickets.slice(0, 8).map(t => (
            <div key={t.orderId} className="flex items-center gap-2 text-xs p-1.5 rounded border" data-testid={`eos-ticket-${t.orderId}`}>
              <span className="font-mono text-[10px] text-gray-500 w-24 truncate">{t.orderId}</span>
              <span className="text-gray-600">{t.tableNumber ? `Table ${t.tableNumber}` : t.orderType}</span>
              <Badge variant="outline" className="text-[10px]">{t.status}</Badge>
              <span className="ml-auto font-bold tabular-nums text-amber-600">{t.ageMinutes != null ? `${Math.round(t.ageMinutes)}m` : '—'}</span>
            </div>
          ))}
          {eos.openCount > 8 && <p className="text-[11px] text-gray-400">+{eos.openCount - 8} more</p>}
        </div>
        {eos.tablesOccupiedWithNoTicket.length > 0 && (
          <p className="text-[11px] text-amber-700 mt-2">
            Tables occupied with no open ticket: {eos.tablesOccupiedWithNoTicket.join(', ')}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function Stat({ icon: Icon, label, value, hint, tone }) {
  return (
    <div className="rounded-lg border p-3">
      <p className="text-[10px] uppercase tracking-wider text-gray-500 flex items-center gap-1">
        <Icon size={11} /> {label}
      </p>
      <p className={`text-xl font-bold tabular-nums ${tone || ''}`}>{value}</p>
      {hint && <p className="text-[10px] text-gray-400">{hint}</p>}
    </div>
  );
}

export default function CoursingAnalytics() {
  const { theme } = useTheme();
  const [days, setDays] = useState(7);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    coursingAPI.analytics(days)
      .then(r => { if (!cancelled) setData(r.data); })
      .catch(e => { if (!cancelled) setError(e.response?.data?.detail || 'Could not load analytics'); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [days]);

  const courses = Object.entries(data?.courses || {});

  return (
    <div className="space-y-6" data-testid="coursing-analytics-page">
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold" style={{ color: theme.text }}>Coursing Analytics</h1>
          <p className="text-sm text-gray-500">Where the time goes between the kitchen and the table.</p>
        </div>
        <div className="flex gap-1">
          {WINDOWS.map(w => (
            <button key={w.days} onClick={() => setDays(w.days)}
              className={`px-3 py-1.5 text-xs rounded-full font-medium transition-colors ${
                days === w.days ? 'text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'}`}
              style={days === w.days ? { background: theme.primary } : {}}
              data-testid={`window-${w.days}`}>
              {w.label}
            </button>
          ))}
        </div>
      </div>

      <EndOfServicePanel />

      {loading && <div className="text-center py-12 text-gray-400 animate-pulse">Loading…</div>}
      {error && <div className="text-center py-12 text-red-600 text-sm" data-testid="analytics-error">{error}</div>}

      {!loading && !error && data && data.sampled === 0 && (
        <Card><CardContent className="py-12 text-center text-gray-400 text-sm" data-testid="analytics-empty">
          No coursed tickets in this window yet. Numbers appear once courses are fired
          and served with coursing switched on.
        </CardContent></Card>
      )}

      {!loading && !error && data && data.sampled > 0 && (
        <>
          <p className="text-xs text-gray-500" data-testid="analytics-sampled">
            {data.sampled} ticket{data.sampled === 1 ? '' : 's'} over {data.days} day{data.days === 1 ? '' : 's'}
          </p>

          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {courses.map(([key, c]) => (
              <Card key={key} data-testid={`course-card-${key}`}>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm flex items-center justify-between">
                    <span>{c.label}</span>
                    <Badge variant="outline" className="text-[10px]">
                      {c.atPass.count || c.cook.count || 0} sampled
                    </Badge>
                  </CardTitle>
                </CardHeader>
                <CardContent className="grid grid-cols-3 gap-2">
                  <Stat icon={Timer} label="Held" value={fmt(c.held.avg)}
                    hint={c.held.worst != null ? `worst ${fmt(c.held.worst)}` : null} />
                  <Stat icon={Flame} label="Cook" value={fmt(c.cook.avg)}
                    hint={c.cook.worst != null ? `worst ${fmt(c.cook.worst)}` : null} />
                  <Stat icon={BellRing} label="At pass" value={fmt(c.atPass.avg)}
                    tone={passTone(c.atPass.avg)}
                    hint={c.atPass.worst != null ? `worst ${fmt(c.atPass.worst)}` : null} />
                </CardContent>
              </Card>
            ))}
          </div>

          {(data.slowestAtPass || []).length > 0 && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm flex items-center gap-1.5">
                  <AlertTriangle size={14} className="text-amber-600" /> Longest at the pass
                </CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-xs text-gray-500 mb-2">
                  Individual courses that sat longest between the kitchen calling them and
                  someone running them — the tickets worth actually looking at.
                </p>
                <div className="space-y-1">
                  {data.slowestAtPass.map((r, i) => (
                    <div key={`${r.orderId}-${r.course}`}
                      className="flex items-center gap-2 text-xs p-1.5 rounded border"
                      data-testid={`slowest-${i}`}>
                      <span className="font-mono text-[10px] text-gray-500 w-24 truncate">{r.orderId}</span>
                      <Badge variant="outline" className="text-[10px]">{r.label}</Badge>
                      <span className={`ml-auto font-bold tabular-nums ${passTone(r.atPassMinutes)}`}>
                        {fmt(r.atPassMinutes)}
                      </span>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}

          {Object.keys(data.byDay || {}).length > 1 && (
            <Card>
              <CardHeader className="pb-2"><CardTitle className="text-sm">By day</CardTitle></CardHeader>
              <CardContent>
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead><tr className="text-gray-500 text-left">
                      <th className="py-1">Day</th>
                      <th className="py-1 text-right">Avg cook</th>
                      <th className="py-1 text-right">Avg at pass</th>
                      <th className="py-1 text-right">Worst at pass</th>
                    </tr></thead>
                    <tbody>
                      {Object.entries(data.byDay).map(([day, v]) => (
                        <tr key={day} className="border-t" data-testid={`day-${day}`}>
                          <td className="py-1 font-mono">{day}</td>
                          <td className="py-1 text-right tabular-nums">{fmt(v.cook.avg)}</td>
                          <td className={`py-1 text-right tabular-nums font-medium ${passTone(v.atPass.avg)}`}>{fmt(v.atPass.avg)}</td>
                          <td className={`py-1 text-right tabular-nums ${passTone(v.atPass.worst)}`}>{fmt(v.atPass.worst)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </CardContent>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
