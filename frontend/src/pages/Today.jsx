import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { useTheme } from '../contexts/ThemeContext';
import { useAuth } from '../contexts/AuthContext';
import { analyticsAPI, preShiftAPI, finalizeAPI, reservationsAPI } from '../services/api';
import { toast } from 'sonner';
import SyncHistoryCard from '../components/today/SyncHistoryCard';
import {
  AlertTriangle, AlertOctagon, Info, RefreshCw, ShoppingCart, ChefHat,
  Utensils, CalendarClock, Users2, TrendingUp, CheckCircle2, ArrowRight,
  Sun, Clock, Users, CalendarDays, Star, Bell, ShieldAlert, Heart, ClipboardList,
} from 'lucide-react';

const SEVERITY_STYLE = {
  critical: { bg: 'bg-red-50', border: 'border-red-200', text: 'text-red-700', Icon: AlertOctagon },
  warning: { bg: 'bg-amber-50', border: 'border-amber-200', text: 'text-amber-700', Icon: AlertTriangle },
  info: { bg: 'bg-blue-50', border: 'border-blue-200', text: 'text-blue-700', Icon: Info },
};

// Role-aware quick actions: managers on the floor get service screens first,
// owners get the money screens. Cashier/kitchen skip this row entirely —
// their own quick-dock already covers the same ground, and money-screen
// shortcuts (Finance, Roster) aren't theirs to jump into.
const QUICK_ACTIONS = {
  owner: [
    { label: 'Finance', path: '/finance', Icon: TrendingUp },
    { label: 'End of Day', path: '/end-of-day', Icon: CalendarClock },
    { label: 'Roster', path: '/staff-roster', Icon: Users2 },
    { label: 'POS', path: '/pos', Icon: ShoppingCart },
  ],
  manager: [
    { label: 'Floor Plan', path: '/floor-plan', Icon: Utensils },
    { label: 'Roster', path: '/staff-roster', Icon: Users2 },
    { label: 'Kitchen', path: '/kitchen', Icon: ChefHat },
    { label: 'POS', path: '/pos', Icon: ShoppingCart },
  ],
};

function formatClockTime(iso) {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleTimeString('en-AU', { hour: '2-digit', minute: '2-digit' });
}

const Today = () => {
  const { theme } = useTheme();
  const { user } = useAuth();
  const navigate = useNavigate();
  const isOwnerOrManager = user?.role === 'owner' || user?.role === 'manager';
  const isOwner = user?.role === 'owner';

  // Money & ops pulse — owner/manager only, same data Today.jsx always used.
  const [pulse, setPulse] = useState(null);
  const [loading, setLoading] = useState(true);
  // Service/hospitality briefing — everyone on shift sees this half.
  const [service, setService] = useState(null);
  const [briefing, setBriefing] = useState(null);

  const load = async () => {
    setLoading(true);
    const jobs = [preShiftAPI.getToday().then(r => setService(r.data)).catch(() => setService(null))];
    if (isOwnerOrManager) {
      jobs.push(analyticsAPI.getTodayPulse().then(r => setPulse(r.data)).catch(() => setPulse(null)));
      jobs.push(finalizeAPI.preShiftBriefing().then(r => setBriefing(r.data)).catch(() => setBriefing(null)));
    } else {
      // Owners see clock-in/out + lateness in the roster card, which needs
      // the briefing endpoint too — but a cashier/kitchen viewer never does,
      // so skip the extra round trip for them.
      jobs.push(finalizeAPI.preShiftBriefing().then(r => setBriefing(r.data)).catch(() => setBriefing(null)));
    }
    await Promise.all(jobs);
    setLoading(false);
  };

  useEffect(() => {
    load();
    const id = setInterval(load, 60000); // refresh every minute — live pulse, not a report
    return () => clearInterval(id);
  }, []);

  const approveBooking = async (id) => {
    try { await reservationsAPI.approve(id); toast.success('Booking approved'); load(); }
    catch (e) { toast.error(e?.response?.data?.detail || 'Could not approve'); }
  };
  const rejectBooking = async (id) => {
    const reason = window.prompt('Reason for rejecting this large booking (guest will need to be re-booked):');
    if (reason === null) return;
    try { await reservationsAPI.reject(id, reason); toast.success('Booking rejected and cancelled'); load(); }
    catch (e) { toast.error(e?.response?.data?.detail || 'Could not reject'); }
  };

  const role = user?.role === 'owner' ? 'owner' : 'manager';
  const actions = QUICK_ACTIONS[role];
  const sales = pulse?.sales || {};
  const labor = pulse?.labor || {};
  const alerts = pulse?.alerts || [];
  const laborOver = labor.pct !== null && labor.pct !== undefined && labor.pct > (labor.threshold || 32);

  const greeting = (() => {
    const h = new Date().getHours();
    if (h < 12) return 'Good Morning';
    if (h < 17) return 'Good Afternoon';
    return 'Good Evening';
  })();

  if (loading && !service && !pulse) {
    return <div className="flex items-center justify-center h-64 text-gray-400">Loading today&apos;s briefing...</div>;
  }

  return (
    <div className="space-y-5" data-testid="today-page">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="w-12 h-12 rounded-xl flex items-center justify-center" style={{ background: `linear-gradient(135deg, ${theme.primary}, ${theme.accent || '#F59E0B'})` }}>
            <Sun size={24} className="text-white" />
          </div>
          <div>
            <h1 className="text-2xl font-bold" style={{ color: theme.text }}>{greeting}{user?.name ? `, ${user.name}` : ', Team'}!</h1>
            <p className="text-sm text-gray-500">
              {new Date().toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })}
            </p>
          </div>
        </div>
        <Button variant="outline" size="sm" onClick={load} data-testid="today-refresh">
          <RefreshCw size={14} className={`mr-1.5 ${loading ? 'animate-spin' : ''}`} /> Refresh
        </Button>
      </div>

      {/* Money & ops — owner/manager only, same numbers Today.jsx always showed */}
      {isOwnerOrManager && (
        <>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <Card data-testid="today-sales">
              <CardContent className="p-4">
                <p className="text-xs text-gray-500 uppercase tracking-wide">Sales today</p>
                <p className="text-2xl font-bold mt-1" style={{ color: theme.primary }}>
                  ${(sales.today || 0).toLocaleString(undefined, { minimumFractionDigits: 2 })}
                </p>
                {sales.target > 0 ? (
                  <div className="mt-2">
                    <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden">
                      <div className="h-full rounded-full transition-all"
                        style={{ width: `${Math.min(sales.pctOfTarget || 0, 100)}%`,
                                 background: (sales.pctOfTarget || 0) >= 100 ? '#059669' : theme.primary }} />
                    </div>
                    <p className="text-[11px] text-gray-500 mt-1">{sales.pctOfTarget || 0}% of ${sales.target.toLocaleString()} target</p>
                  </div>
                ) : (
                  <p className="text-[11px] text-gray-400 mt-2">{sales.txnCount || 0} sales · set a daily target in Settings</p>
                )}
              </CardContent>
            </Card>

            <Card data-testid="today-labor">
              <CardContent className="p-4">
                <p className="text-xs text-gray-500 uppercase tracking-wide">Labor</p>
                <p className={`text-2xl font-bold mt-1 ${laborOver ? 'text-red-600' : 'text-gray-800'}`}>
                  {labor.pct !== null && labor.pct !== undefined ? `${labor.pct}%` : '—'}
                </p>
                <p className="text-[11px] text-gray-500 mt-2">
                  ${(labor.costToday || 0).toFixed(0)} rostered · {labor.shiftsToday || 0} shifts
                  {laborOver ? ` · over ${labor.threshold}% line` : ''}
                </p>
              </CardContent>
            </Card>

            <Card data-testid="today-avg-ticket">
              <CardContent className="p-4">
                <p className="text-xs text-gray-500 uppercase tracking-wide">Avg ticket</p>
                <p className="text-2xl font-bold mt-1 text-gray-800">${(sales.avgTicket || 0).toFixed(2)}</p>
                <p className="text-[11px] text-gray-500 mt-2">{sales.txnCount || 0} transactions</p>
              </CardContent>
            </Card>
          </div>

          {/* Exceptions — problems tap you on the shoulder */}
          <Card data-testid="today-alerts">
            <CardContent className="p-4">
              <div className="flex items-center justify-between mb-3">
                <h2 className="font-semibold text-sm" style={{ color: theme.text }}>Needs attention</h2>
                {alerts.length > 0 && (
                  <span className="text-[11px] font-bold px-2 py-0.5 rounded-full bg-red-100 text-red-700">{alerts.length}</span>
                )}
              </div>
              {loading && !pulse ? (
                <p className="text-sm text-gray-400 py-4 text-center">Checking…</p>
              ) : alerts.length === 0 ? (
                <div className="flex items-center gap-2 py-4 justify-center text-emerald-700">
                  <CheckCircle2 size={18} />
                  <p className="text-sm font-medium">All clear — nothing needs your attention right now.</p>
                </div>
              ) : (
                <div className="space-y-2">
                  {alerts.map((a, i) => {
                    const st = SEVERITY_STYLE[a.severity] || SEVERITY_STYLE.info;
                    const AlertIcon = st.Icon;
                    return (
                      <button key={i} onClick={() => a.link && navigate(a.link)}
                        className={`w-full flex items-center gap-3 p-3 rounded-lg border text-left transition-all hover:shadow-sm ${st.bg} ${st.border}`}
                        data-testid={`today-alert-${a.kind}`}>
                        <AlertIcon size={18} className={st.text} />
                        <span className={`flex-1 text-sm font-medium ${st.text}`}>{a.message}</span>
                        <ArrowRight size={14} className={st.text} />
                      </button>
                    );
                  })}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Role-aware quick actions */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            {actions.map(({ label, path, Icon }) => (
              <button key={path} onClick={() => navigate(path)}
                className="flex items-center gap-3 p-4 bg-white rounded-xl border hover:shadow-md transition-all"
                data-testid={`today-quick-${path.replace('/', '')}`}>
                <span className="w-9 h-9 rounded-lg flex items-center justify-center"
                  style={{ background: `${theme.primary}15`, color: theme.primary }}>
                  <Icon size={18} />
                </span>
                <span className="font-semibold text-sm text-gray-800">{label}</span>
              </button>
            ))}
          </div>
        </>
      )}

      {/* Service briefing — everyone on shift sees this half */}
      {service && (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
            {[
              { label: 'Reservations', val: service.totalReservations, icon: CalendarDays, color: '#3B82F6' },
              { label: 'Total Covers', val: service.totalCovers, icon: Users, color: theme.primary },
              { label: 'Confirmed', val: service.confirmed, icon: Bell, color: '#10B981' },
              { label: 'Kitchen Queue', val: service.kitchenPending, icon: ChefHat, color: '#F59E0B' },
              { label: 'Waitlist', val: service.waitlistCount, icon: ClipboardList, color: '#8B5CF6' },
            ].map((s, i) => (
              <Card key={i} className="border-0 shadow-sm">
                <CardContent className="p-4 flex items-center gap-3">
                  <div className="w-10 h-10 rounded-lg flex items-center justify-center" style={{ background: `${s.color}15` }}>
                    <s.icon size={20} style={{ color: s.color }} />
                  </div>
                  <div>
                    <p className="text-2xl font-bold" style={{ color: theme.text }}>{s.val}</p>
                    <p className="text-[10px] text-gray-500">{s.label}</p>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <Card className="border-0 shadow-sm col-span-1">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm flex items-center gap-2">
                  <Star size={16} className="text-amber-500" /> VIP Arrivals
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                {(service.vipGuests || []).length === 0 ? (
                  <p className="text-xs text-gray-400 py-4 text-center">No VIP guests today</p>
                ) : service.vipGuests.map((g, i) => (
                  <div key={i} className="flex items-center gap-3 p-2 rounded-lg bg-amber-50/50">
                    <div className="w-8 h-8 rounded-full bg-amber-100 flex items-center justify-center text-amber-700 font-bold text-xs">
                      {g.guestName?.split(' ').map(n => n[0]).join('').slice(0, 2)}
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium truncate">{g.guestName}</p>
                      <div className="flex items-center gap-2 text-[10px] text-gray-500">
                        <span><Clock size={10} className="inline" /> {g.time}</span>
                        <span><Users size={10} className="inline" /> {g.partySize}</span>
                      </div>
                    </div>
                    <Badge className="bg-amber-100 text-amber-700 text-[10px]">VIP</Badge>
                  </div>
                ))}
              </CardContent>
            </Card>

            <Card className="border-0 shadow-sm col-span-1">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm flex items-center gap-2">
                  <ShieldAlert size={16} className="text-red-500" /> Dietary &amp; Allergy Alerts
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                {(service.dietaryAlerts || []).length === 0 ? (
                  <p className="text-xs text-gray-400 py-4 text-center">No dietary alerts today</p>
                ) : service.dietaryAlerts.map((a, i) => (
                  <div key={i} className="p-2 rounded-lg bg-red-50/50">
                    <div className="flex items-center justify-between mb-1">
                      <p className="text-sm font-medium">{a.guest}</p>
                      <span className="text-[10px] text-gray-500">{a.time}</span>
                    </div>
                    <div className="flex flex-wrap gap-1">
                      {a.alerts.map((alert, j) => (
                        <Badge key={j} className={`text-[10px] ${alert.startsWith('ALLERGY') ? 'bg-red-100 text-red-700' : 'bg-orange-100 text-orange-700'}`}>
                          {alert}
                        </Badge>
                      ))}
                    </div>
                  </div>
                ))}
              </CardContent>
            </Card>

            <Card className="border-0 shadow-sm col-span-1">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm flex items-center gap-2">
                  <Heart size={16} className="text-pink-500" /> Special Requests
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                {(service.specialRequests || []).length === 0 ? (
                  <p className="text-xs text-gray-400 py-4 text-center">No special requests today</p>
                ) : service.specialRequests.map((sr, i) => (
                  <div key={i} className="p-2 rounded-lg bg-pink-50/50">
                    <div className="flex items-center justify-between mb-1">
                      <p className="text-sm font-medium">{sr.guest}</p>
                      <div className="flex items-center gap-2 text-[10px] text-gray-500">
                        <span><Clock size={10} className="inline" /> {sr.time}</span>
                        <span><Users size={10} className="inline" /> {sr.partySize}</span>
                      </div>
                    </div>
                    <p className="text-xs text-gray-600">{sr.request}</p>
                  </div>
                ))}
              </CardContent>
            </Card>
          </div>

          {(service.largeBookings || []).length > 0 && (
            <Card className="border-0 shadow-sm" data-testid="today-large-bookings">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm flex items-center gap-2">
                  <Users2 size={16} className="text-purple-600" /> Large Bookings Today
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b bg-gray-50/80">
                        <th className="text-left px-3 py-2 font-medium text-gray-500">Time</th>
                        <th className="text-left px-3 py-2 font-medium text-gray-500">Guest</th>
                        <th className="text-left px-3 py-2 font-medium text-gray-500">Party</th>
                        <th className="text-left px-3 py-2 font-medium text-gray-500">Tier / Experience</th>
                        <th className="text-left px-3 py-2 font-medium text-gray-500">Deposit</th>
                        <th className="text-left px-3 py-2 font-medium text-gray-500">Pre-Order</th>
                        <th className="text-left px-3 py-2 font-medium text-gray-500">Approval</th>
                        <th className="text-left px-3 py-2 font-medium text-gray-500">Notes</th>
                      </tr>
                    </thead>
                    <tbody>
                      {service.largeBookings.map(b => (
                        <tr key={b.reservationId} className="border-b hover:bg-gray-50/50">
                          <td className="px-3 py-2 font-mono font-medium">{b.time}</td>
                          <td className="px-3 py-2 font-medium">{b.guest}</td>
                          <td className="px-3 py-2"><Users size={10} className="inline mb-0.5" /> {b.partySize}</td>
                          <td className="px-3 py-2 text-xs">{b.experienceName || b.tierLabel || '—'}</td>
                          <td className="px-3 py-2">
                            {b.depositRequired > 0 ? (
                              <Badge className={`text-[10px] ${b.depositPaid ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-700'}`}>
                                {b.depositPaid ? 'Paid' : `$${b.depositRequired} due`}
                              </Badge>
                            ) : <span className="text-gray-300 text-xs">—</span>}
                          </td>
                          <td className="px-3 py-2">
                            {b.preOrderRequired ? (
                              <Badge className={`text-[10px] ${b.preOrderCompleted ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-700'}`}>
                                {b.preOrderCompleted ? 'Done' : 'Pending'}
                              </Badge>
                            ) : <span className="text-gray-300 text-xs">—</span>}
                          </td>
                          <td className="px-3 py-2">
                            {b.approvalRequired ? (
                              <div className="flex items-center gap-1.5">
                                <Badge className={`text-[10px] ${
                                  b.approvalStatus === 'approved' ? 'bg-emerald-100 text-emerald-700'
                                  : b.approvalStatus === 'rejected' ? 'bg-red-100 text-red-700'
                                  : 'bg-amber-100 text-amber-700'
                                }`}>
                                  {b.approvalStatus === 'approved' ? <CheckCircle2 size={10} className="inline mr-0.5" /> : <AlertTriangle size={10} className="inline mr-0.5" />}
                                  {b.approvalStatus}
                                </Badge>
                                {b.approvalStatus === 'pending' && isOwnerOrManager && (
                                  <>
                                    <button onClick={() => approveBooking(b.reservationId)} data-testid={`approve-${b.reservationId}`}
                                      className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-600 text-white hover:bg-emerald-700">
                                      Approve
                                    </button>
                                    <button onClick={() => rejectBooking(b.reservationId)} data-testid={`reject-${b.reservationId}`}
                                      className="text-[10px] px-1.5 py-0.5 rounded bg-red-600 text-white hover:bg-red-700">
                                      Reject
                                    </button>
                                  </>
                                )}
                              </div>
                            ) : <span className="text-gray-300 text-xs">—</span>}
                          </td>
                          <td className="px-3 py-2 text-xs text-gray-500 max-w-[160px] truncate">{b.specialRequests || '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </CardContent>
            </Card>
          )}

          <Card className="border-0 shadow-sm">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm flex items-center gap-2">
                <Utensils size={16} style={{ color: theme.primary }} /> Today&apos;s Service Timeline
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="overflow-x-auto">
                <table className="w-full text-sm" data-testid="today-timeline">
                  <thead>
                    <tr className="border-b bg-gray-50/80">
                      <th className="text-left px-3 py-2 font-medium text-gray-500">Time</th>
                      <th className="text-left px-3 py-2 font-medium text-gray-500">Guest</th>
                      <th className="text-left px-3 py-2 font-medium text-gray-500">Party</th>
                      <th className="text-left px-3 py-2 font-medium text-gray-500">Table</th>
                      <th className="text-left px-3 py-2 font-medium text-gray-500">Status</th>
                      <th className="text-left px-3 py-2 font-medium text-gray-500">Tags</th>
                      <th className="text-left px-3 py-2 font-medium text-gray-500">Notes</th>
                    </tr>
                  </thead>
                  <tbody>
                    {!(service.reservations || []).length && <tr><td colSpan={7} className="py-8 text-center text-muted-foreground">No reservations scheduled for today.</td></tr>}
                    {(service.reservations || []).map(r => (
                      <tr key={r.id} className="border-b hover:bg-gray-50/50">
                        <td className="px-3 py-2 font-mono font-medium">{r.time}</td>
                        <td className="px-3 py-2 font-medium">{r.guestName}</td>
                        <td className="px-3 py-2">{r.partySize}</td>
                        <td className="px-3 py-2">{r.tableNumber ? `T${r.tableNumber}` : '—'}</td>
                        <td className="px-3 py-2">
                          <Badge variant="outline" className="text-[10px] capitalize">{r.status?.replace('_', ' ')}</Badge>
                        </td>
                        <td className="px-3 py-2">
                          <div className="flex gap-1">
                            {(r.tags || []).map((t, i) => <Badge key={i} className="text-[10px]" style={{ background: `${theme.primary}15`, color: theme.primary }}>{t}</Badge>)}
                          </div>
                        </td>
                        <td className="px-3 py-2 text-xs text-gray-500 max-w-[200px] truncate">{r.specialRequests || '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        </>
      )}

      {/* Out of stock / specials / on-shift / upsells */}
      {briefing && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3" data-testid="today-briefing">
          <Card data-testid="briefing-oos">
            <CardHeader className="pb-2"><CardTitle className="text-sm flex items-center gap-2 text-rose-600">
              <AlertTriangle size={14} /> Out of stock ({briefing.outOfStock?.length || 0})
            </CardTitle></CardHeader>
            <CardContent className="text-xs space-y-1 max-h-48 overflow-y-auto">
              {(briefing.outOfStock || []).length === 0 ? <div className="text-gray-400 italic">Nothing 86&apos;d — kitchen is happy.</div> :
                (briefing.outOfStock || []).map(p => (
                  <div key={p.id} className="flex justify-between border-b pb-1">
                    <span>{p.name}</span>
                    <span className="text-gray-500">{p.category}</span>
                  </div>
                ))}
            </CardContent>
          </Card>

          <Card data-testid="briefing-specials">
            <CardHeader className="pb-2"><CardTitle className="text-sm flex items-center gap-2 text-amber-600">
              <Star size={14} /> Today&apos;s specials ({(briefing.specials?.length || 0) + (briefing.activePromotions?.length || 0)})
            </CardTitle></CardHeader>
            <CardContent className="text-xs space-y-1 max-h-48 overflow-y-auto">
              {(briefing.specials || []).map(s => (
                <div key={s.id} className="border-b pb-1"><strong>{s.name}</strong> <span className="text-gray-500">${(s.price || 0).toFixed(2)}</span></div>
              ))}
              {(briefing.activePromotions || []).map(p => (
                <div key={p.id} className="border-b pb-1 text-emerald-700">🎉 {p.name} · {p.discount}% off</div>
              ))}
              {briefing.specials?.length === 0 && briefing.activePromotions?.length === 0 && <div className="text-gray-400 italic">No specials today.</div>}
            </CardContent>
          </Card>

          <Card data-testid="briefing-shift">
            <CardHeader className="pb-2"><CardTitle className="text-sm flex items-center gap-2 text-blue-600">
              <Users size={14} /> On shift ({briefing.onShiftCount || 0})
            </CardTitle></CardHeader>
            <CardContent className="text-xs space-y-1 max-h-48 overflow-y-auto">
              {(briefing.onShift || []).length === 0 ? <div className="text-gray-400 italic">No roster loaded for today.</div> :
                (briefing.onShift || []).map((s, i) => {
                  const startedAt = formatClockTime(s.clockIn);
                  const finishedAt = formatClockTime(s.clockOut);
                  return (
                    <div key={i} className="border-b pb-1">
                      <div className="flex justify-between">
                        <span>{s.staffName || s.name || s.staffId}</span>
                        <span className="text-gray-500">{s.role || s.shift || ''}</span>
                      </div>
                      {isOwner && (
                        <div className="flex items-center justify-between mt-0.5 text-[10px] text-gray-500">
                          <span>
                            {startedAt ? `In ${startedAt}` : 'Not clocked in'}
                            {finishedAt ? ` · Out ${finishedAt}` : ''}
                            {s.scheduledStart ? ` (sched. ${s.scheduledStart}${s.scheduledEnd ? `-${s.scheduledEnd}` : ''})` : ''}
                          </span>
                          {s.onTime === true && <Badge className="bg-emerald-100 text-emerald-700 text-[9px]">On time</Badge>}
                          {s.onTime === false && (
                            <Badge className="bg-red-100 text-red-700 text-[9px]">
                              {s.lateMinutes > 0 ? `${s.lateMinutes}m late` : 'Late'}
                            </Badge>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
            </CardContent>
          </Card>

          <Card data-testid="briefing-upsells">
            <CardHeader className="pb-2"><CardTitle className="text-sm flex items-center gap-2 text-emerald-600">
              <TrendingUp size={14} /> Push these tonight
            </CardTitle></CardHeader>
            <CardContent className="text-xs space-y-1 max-h-48 overflow-y-auto">
              {(briefing.upsells || []).slice(0, 8).map(p => (
                <div key={p.id} className="flex justify-between border-b pb-1">
                  <span>{p.name}</span>
                  <span className="text-emerald-700">{p.marginPct}% · ${(p.price || 0).toFixed(0)}</span>
                </div>
              ))}
            </CardContent>
          </Card>

          {isOwner && <SyncHistoryCard />}
        </div>
      )}
    </div>
  );
};

export default Today;
