import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  BarChart3, Users, AlertTriangle, TrendingUp, DollarSign,
  Armchair, Download, FileText, ChevronDown, ChevronUp, Info, Ban,
} from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import { useTheme } from '../contexts/ThemeContext';
import { bookingAnalyticsAPI } from '../services/api';
import MiniChart from '../components/charts/MiniChart';
import { toast } from 'sonner';
import { FileService } from '../platform';

const money = (v) => v === null || v === undefined ? '—' : `$${Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

// Quick date-range presets — Item 9's required filter set. Computed against
// local "today" each render rather than memoised once, so a page left open
// past midnight still offers the right "Today"/"Yesterday" range.
function presetRange(key) {
  const today = new Date();
  const iso = (d) => d.toISOString().slice(0, 10);
  const startOfWeek = (d) => { const x = new Date(d); const day = (x.getDay() + 6) % 7; x.setDate(x.getDate() - day); return x; };
  switch (key) {
    case 'today': return { start: iso(today), end: iso(today) };
    case 'yesterday': { const y = new Date(today); y.setDate(y.getDate() - 1); return { start: iso(y), end: iso(y) }; }
    case 'this_week': return { start: iso(startOfWeek(today)), end: iso(today) };
    case 'last_week': { const s = startOfWeek(today); s.setDate(s.getDate() - 7); const e = new Date(s); e.setDate(e.getDate() + 6); return { start: iso(s), end: iso(e) }; }
    case 'this_month': return { start: iso(new Date(today.getFullYear(), today.getMonth(), 1)), end: iso(today) };
    case 'last_month': { const s = new Date(today.getFullYear(), today.getMonth() - 1, 1); const e = new Date(today.getFullYear(), today.getMonth(), 0); return { start: iso(s), end: iso(e) }; }
    case 'quarter': { const q = Math.floor(today.getMonth() / 3); return { start: iso(new Date(today.getFullYear(), q * 3, 1)), end: iso(today) }; }
    case 'year': return { start: iso(new Date(today.getFullYear(), 0, 1)), end: iso(today) };
    default: { const s = new Date(today); s.setDate(s.getDate() - 30); return { start: iso(s), end: iso(today) }; }
  }
}

const PRESETS = [
  ['today', 'Today'], ['yesterday', 'Yesterday'], ['this_week', 'This Week'], ['last_week', 'Last Week'],
  ['this_month', 'This Month'], ['last_month', 'Last Month'], ['quarter', 'Quarter'], ['year', 'Year'], ['custom', 'Custom'],
];

function KpiCard({ icon: Icon, label, value, sub, color }) {
  return (
    <Card><CardContent className="p-4 text-center">
      <Icon size={18} className="mx-auto mb-1.5" style={{ color }} />
      <p className="text-xl font-bold" style={{ color }}>{value}</p>
      <p className="text-[11px] text-gray-500">{label}</p>
      {sub && <p className="text-[10px] text-gray-400 mt-0.5">{sub}</p>}
    </CardContent></Card>
  );
}

export default function BookingAnalytics() {
  const { theme } = useTheme();
  const [preset, setPreset] = useState('this_month');
  const [range, setRange] = useState(() => presetRange('this_month'));
  const [filters, setFilters] = useState({ status: '', source: '', minPartySize: '', maxPartySize: '' });
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(true);
  const [showDetailed, setShowDetailed] = useState(false);
  const [detailSearch, setDetailSearch] = useState('');
  const [exporting, setExporting] = useState(null);

  const params = useMemo(() => {
    const p = { start: range.start, end: range.end };
    if (filters.status) p.status = filters.status;
    if (filters.source) p.source = filters.source;
    if (filters.minPartySize) p.minPartySize = filters.minPartySize;
    if (filters.maxPartySize) p.maxPartySize = filters.maxPartySize;
    return p;
  }, [range, filters]);

  const fetchReport = useCallback(async () => {
    setLoading(true);
    try {
      const r = await bookingAnalyticsAPI.getReport(params);
      setReport(r.data);
    } catch {
      toast.error('Could not load booking analytics');
    } finally {
      setLoading(false);
    }
  }, [params]);

  useEffect(() => { fetchReport(); }, [fetchReport]);

  const applyPreset = (key) => {
    setPreset(key);
    if (key !== 'custom') setRange(presetRange(key));
  };

  const download = async (kind) => {
    setExporting(kind);
    try {
      const fn = kind === 'csv' ? bookingAnalyticsAPI.downloadCsv : bookingAnalyticsAPI.downloadPdf;
      const r = await fn(params);
      await FileService.downloadFile(r.data, `booking-report-${range.start}_to_${range.end}.${kind}`);
      toast.success(`${kind.toUpperCase()} downloaded`);
    } catch {
      toast.error(`${kind.toUpperCase()} export failed`);
    } finally {
      setExporting(null);
    }
  };

  const detailedFiltered = useMemo(() => {
    if (!report) return [];
    const q = detailSearch.trim().toLowerCase();
    if (!q) return report.detailed;
    return report.detailed.filter(d =>
      (d.guestName || '').toLowerCase().includes(q) ||
      (d.source || '').toLowerCase().includes(q) ||
      (d.tableNumber || '').toString().toLowerCase().includes(q) ||
      (d.status || '').toLowerCase().includes(q)
    );
  }, [report, detailSearch]);

  if (loading && !report) {
    return <div className="flex justify-center py-12"><div className="animate-pulse text-gray-400">Loading analytics...</div></div>;
  }
  if (!report) return null;

  const { kpis, channels, dayOfWeek, hourOfDay, peakHours, quietHours, partySizeBuckets, tables, customers, dataNotes } = report;
  const revenueBest = kpis.revenueEstimated > 0 ? kpis.revenueEstimated : kpis.revenueActual;

  return (
    <div className="space-y-6" data-testid="booking-analytics-page">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold" style={{ color: theme.text }}>Booking Analytics</h1>
          <p className="text-sm text-gray-500">Reporting layer for bookings — channels, timing, tables and revenue</p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => download('csv')} disabled={exporting === 'csv'} data-testid="export-csv-btn">
            <Download size={14} className="mr-1" /> CSV
          </Button>
          <Button size="sm" style={{ background: theme.primary }} onClick={() => download('pdf')} disabled={exporting === 'pdf'} data-testid="export-pdf-btn">
            <FileText size={14} className="mr-1" /> PDF Report
          </Button>
        </div>
      </div>

      {/* Report Builder: date range + filters */}
      <Card className="border-0 shadow-sm">
        <CardContent className="p-4 space-y-3">
          <div className="flex flex-wrap gap-1.5" data-testid="date-presets">
            {PRESETS.map(([key, label]) => (
              <button key={key} onClick={() => applyPreset(key)}
                className="px-3 py-1.5 text-xs font-medium rounded-full border transition-colors"
                style={preset === key ? { background: theme.primary, color: '#fff', borderColor: theme.primary } : { borderColor: '#e5e7eb', color: '#6b7280' }}
                data-testid={`preset-${key}`}>
                {label}
              </button>
            ))}
          </div>
          <div className="flex flex-wrap items-end gap-3">
            <div>
              <label className="text-[10px] font-medium text-gray-500 block mb-1">Start</label>
              <Input type="date" value={range.start} className="h-8 text-sm w-36"
                onChange={e => { setPreset('custom'); setRange(r => ({ ...r, start: e.target.value })); }} data-testid="range-start" />
            </div>
            <div>
              <label className="text-[10px] font-medium text-gray-500 block mb-1">End</label>
              <Input type="date" value={range.end} className="h-8 text-sm w-36"
                onChange={e => { setPreset('custom'); setRange(r => ({ ...r, end: e.target.value })); }} data-testid="range-end" />
            </div>
            <div>
              <label className="text-[10px] font-medium text-gray-500 block mb-1">Status</label>
              <Select value={filters.status || 'all'} onValueChange={v => setFilters(f => ({ ...f, status: v === 'all' ? '' : v }))}>
                <SelectTrigger className="h-8 text-sm w-36" data-testid="filter-status"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All statuses</SelectItem>
                  <SelectItem value="confirmed">Confirmed</SelectItem>
                  <SelectItem value="seated">Seated</SelectItem>
                  <SelectItem value="completed">Completed</SelectItem>
                  <SelectItem value="cancelled">Cancelled</SelectItem>
                  <SelectItem value="no_show">No-show</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <label className="text-[10px] font-medium text-gray-500 block mb-1">Channel</label>
              <Select value={filters.source || 'all'} onValueChange={v => setFilters(f => ({ ...f, source: v === 'all' ? '' : v }))}>
                <SelectTrigger className="h-8 text-sm w-36" data-testid="filter-source"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All channels</SelectItem>
                  {channels.map(c => <SelectItem key={c.source} value={c.source}>{c.source}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div>
              <label className="text-[10px] font-medium text-gray-500 block mb-1">Party size</label>
              <div className="flex items-center gap-1">
                <Input type="number" min={1} placeholder="Min" className="h-8 text-sm w-16"
                  value={filters.minPartySize} onChange={e => setFilters(f => ({ ...f, minPartySize: e.target.value }))} data-testid="filter-min-party" />
                <span className="text-gray-400 text-xs">–</span>
                <Input type="number" min={1} placeholder="Max" className="h-8 text-sm w-16"
                  value={filters.maxPartySize} onChange={e => setFilters(f => ({ ...f, maxPartySize: e.target.value }))} data-testid="filter-max-party" />
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Executive Summary KPIs */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3" data-testid="kpi-grid">
        <KpiCard icon={BarChart3} label="Bookings" value={kpis.bookings} color="#3b82f6" />
        <KpiCard icon={Users} label="Covers" value={kpis.covers} color="#10b981" />
        <KpiCard icon={DollarSign} label="Revenue" value={money(revenueBest)}
          sub={kpis.revenueEstimated > 0 ? 'estimated' : (kpis.revenueActual > 0 ? 'actual (deposits)' : undefined)} color={theme.primary} />
        <KpiCard icon={TrendingUp} label="Avg Spend" value={kpis.avgSpend != null ? money(kpis.avgSpend) : '—'} color="#8b5cf6" />
        <KpiCard icon={Users} label="Spend / Guest" value={kpis.spendPerGuest != null ? money(kpis.spendPerGuest) : '—'} color="#06b6d4" />
        <KpiCard icon={AlertTriangle} label="No-Show %" value={`${kpis.noShowRate}%`} color="#ef4444" />
        <KpiCard icon={Ban} label="Cancellation %" value={`${kpis.cancellationRate}%`} color="#f97316" />
        <KpiCard icon={Armchair} label="Table Utilisation" value={`${kpis.tableUtilisationPct}%`} color="#14b8a6" />
      </div>

      {/* Revenue breakdown — actual vs estimated vs unknown, per Item 14 */}
      <Card className="border-0 shadow-sm bg-blue-50/50">
        <CardContent className="p-3 flex items-start gap-2">
          <Info size={14} className="text-blue-500 mt-0.5 shrink-0" />
          <div className="text-xs text-gray-600 flex flex-wrap gap-x-4 gap-y-1">
            <span><b>Actual</b> (deposits collected): {money(kpis.revenueActual)}</span>
            <span><b>Estimated</b> (matched transactions): {money(kpis.revenueEstimated)}</span>
            <span><b>Unknown</b> (ambiguous table/day): {money(kpis.revenueUnknown)}</span>
          </div>
        </CardContent>
      </Card>

      {/* Channel Performance */}
      <Card className="border-0 shadow-sm">
        <CardHeader><CardTitle className="text-sm">Channel Performance</CardTitle></CardHeader>
        <CardContent className="overflow-x-auto">
          <table className="w-full text-sm" data-testid="channel-table">
            <thead><tr className="text-left text-xs text-gray-400 border-b">
              <th className="pb-2 font-medium">Channel</th><th className="pb-2 font-medium">Bookings</th>
              <th className="pb-2 font-medium">Guests</th><th className="pb-2 font-medium">Revenue</th>
              <th className="pb-2 font-medium">Avg Spend</th><th className="pb-2 font-medium">Avg Party</th>
              <th className="pb-2 font-medium">No-show %</th><th className="pb-2 font-medium">Cancel %</th>
            </tr></thead>
            <tbody>
              {channels.map(c => (
                <tr key={c.source} className="border-b last:border-0" data-testid={`channel-row-${c.source}`}>
                  <td className="py-2 font-medium capitalize">{c.source.replace(/_/g, ' ')}</td>
                  <td className="py-2">{c.bookings}</td><td className="py-2">{c.guests}</td>
                  <td className="py-2">{money(c.revenueEstimate)}</td><td className="py-2">{money(c.avgSpend)}</td>
                  <td className="py-2">{c.avgPartySize}</td>
                  <td className="py-2">{c.noShowRate}%</td><td className="py-2">{c.cancellationRate}%</td>
                </tr>
              ))}
              {channels.length === 0 && <tr><td colSpan={8} className="text-center text-gray-400 py-4">No bookings in range</td></tr>}
            </tbody>
          </table>
        </CardContent>
      </Card>

      {/* Time Analysis */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Card className="border-0 shadow-sm">
          <CardHeader><CardTitle className="text-sm">Bookings by Day of Week</CardTitle></CardHeader>
          <CardContent>
            <MiniChart data={dayOfWeek.map(d => ({ label: d.day.slice(0, 3), value: d.bookings }))} color={theme.primary} height={150} />
          </CardContent>
        </Card>
        <Card className="border-0 shadow-sm">
          <CardHeader><CardTitle className="text-sm">Bookings by Hour</CardTitle></CardHeader>
          <CardContent>
            <MiniChart data={hourOfDay.filter((h, i) => i % 2 === 0).map(h => ({ label: `${h.hour}h`, value: h.bookings }))} color="#8b5cf6" height={150} />
            <div className="flex justify-between text-[11px] text-gray-500 mt-2">
              <span>Peak: {peakHours.map(h => `${String(h.hour).padStart(2, '0')}:00`).join(', ') || '—'}</span>
              <span>Quiet: {quietHours.map(h => `${String(h.hour).padStart(2, '0')}:00`).join(', ') || '—'}</span>
            </div>
          </CardContent>
        </Card>
      </div>

      <Card className="border-0 shadow-sm">
        <CardHeader><CardTitle className="text-sm">Party Size Breakdown</CardTitle></CardHeader>
        <CardContent>
          <MiniChart data={partySizeBuckets.map(b => ({ label: b.bucket, value: b.bookings }))} color="#10b981" height={140} />
        </CardContent>
      </Card>

      {/* Table Performance */}
      <Card className="border-0 shadow-sm">
        <CardHeader><CardTitle className="text-sm">Table Performance</CardTitle></CardHeader>
        <CardContent className="overflow-x-auto">
          <table className="w-full text-sm" data-testid="table-performance">
            <thead><tr className="text-left text-xs text-gray-400 border-b">
              <th className="pb-2 font-medium">Table</th><th className="pb-2 font-medium">Floor</th>
              <th className="pb-2 font-medium">Bookings</th><th className="pb-2 font-medium">Covers</th>
              <th className="pb-2 font-medium">Revenue</th><th className="pb-2 font-medium">Avg Duration</th>
              <th className="pb-2 font-medium">Utilisation</th>
            </tr></thead>
            <tbody>
              {tables.map(t => (
                <tr key={t.table} className="border-b last:border-0">
                  <td className="py-2 font-medium">{t.table}</td><td className="py-2">{t.floor || '—'}</td>
                  <td className="py-2">{t.bookings}</td><td className="py-2">{t.covers}</td>
                  <td className="py-2">{money(t.revenueEstimate)}</td>
                  <td className="py-2">{t.avgDurationMinutes ? `${t.avgDurationMinutes}m` : '—'}</td>
                  <td className="py-2">{t.utilisationPct}%</td>
                </tr>
              ))}
              {tables.length === 0 && <tr><td colSpan={7} className="text-center text-gray-400 py-4">No table data in range</td></tr>}
            </tbody>
          </table>
        </CardContent>
      </Card>

      {/* Guest Behaviour */}
      <Card className="border-0 shadow-sm">
        <CardHeader><CardTitle className="text-sm">Guest Behaviour</CardTitle></CardHeader>
        <CardContent className="flex items-center gap-6 flex-wrap">
          <div><p className="text-lg font-bold" style={{ color: theme.primary }}>{customers.new}</p><p className="text-xs text-gray-500">New customers</p></div>
          <div><p className="text-lg font-bold text-emerald-600">{customers.returning}</p><p className="text-xs text-gray-500">Returning customers</p></div>
          {customers.unattributedBookings > 0 && (
            <Badge variant="outline" className="text-xs">{customers.unattributedBookings} booking(s) without a linked profile</Badge>
          )}
        </CardContent>
      </Card>

      {/* Detailed Bookings — on-screen interactive report */}
      <Card className="border-0 shadow-sm">
        <CardHeader className="cursor-pointer" onClick={() => setShowDetailed(s => !s)}>
          <CardTitle className="text-sm flex items-center justify-between">
            <span>Detailed Bookings ({report.detailed.length})</span>
            {showDetailed ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
          </CardTitle>
        </CardHeader>
        {showDetailed && (
          <CardContent>
            <Input placeholder="Search guest, channel, table, status..." className="h-8 text-sm mb-3 max-w-sm"
              value={detailSearch} onChange={e => setDetailSearch(e.target.value)} data-testid="detail-search" />
            <div className="overflow-x-auto max-h-96 overflow-y-auto">
              <table className="w-full text-sm" data-testid="detailed-table">
                <thead className="sticky top-0 bg-white"><tr className="text-left text-xs text-gray-400 border-b">
                  <th className="pb-2 font-medium">Guest</th><th className="pb-2 font-medium">Date</th>
                  <th className="pb-2 font-medium">Time</th><th className="pb-2 font-medium">Status</th>
                  <th className="pb-2 font-medium">Channel</th><th className="pb-2 font-medium">Party</th>
                  <th className="pb-2 font-medium">Table</th><th className="pb-2 font-medium">Revenue</th>
                </tr></thead>
                <tbody>
                  {detailedFiltered.map(d => (
                    <tr key={d.id} className="border-b last:border-0">
                      <td className="py-1.5">{d.guestName || '—'}</td><td className="py-1.5">{d.date}</td>
                      <td className="py-1.5">{d.time}</td>
                      <td className="py-1.5"><Badge variant="outline" className="text-[10px] capitalize">{(d.status || '').replace('_', ' ')}</Badge></td>
                      <td className="py-1.5 capitalize">{(d.source || '—').replace(/_/g, ' ')}</td>
                      <td className="py-1.5">{d.partySize}</td><td className="py-1.5">{d.tableNumber || '—'}</td>
                      <td className="py-1.5">{d.revenueConfidence === 'estimated' ? money(d.revenueEstimate) : (d.revenueConfidence === 'unknown' ? 'unknown' : '—')}</td>
                    </tr>
                  ))}
                  {detailedFiltered.length === 0 && <tr><td colSpan={8} className="text-center text-gray-400 py-4">No matching bookings</td></tr>}
                </tbody>
              </table>
            </div>
          </CardContent>
        )}
      </Card>

      {/* Methodology / data notes */}
      <Card className="border-0 shadow-sm">
        <CardContent className="p-4 space-y-1.5">
          <p className="text-xs font-medium text-gray-500 flex items-center gap-1"><Info size={12} /> Methodology & Data Notes</p>
          {dataNotes.map((n, i) => <p key={i} className="text-[11px] text-gray-400 leading-relaxed">{n}</p>)}
        </CardContent>
      </Card>
    </div>
  );
}
