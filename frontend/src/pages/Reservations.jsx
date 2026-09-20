import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  CalendarDays, Clock, Users, Plus, Search, Filter, ChevronLeft, ChevronRight,
  Phone, Mail, Edit2, Trash2, Check, X, UserCheck, AlertTriangle, MapPin, Ban, RotateCcw, CreditCard
} from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Badge } from '../components/ui/badge';
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter
} from '../components/ui/dialog';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue
} from '../components/ui/select';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs';
import { useTheme } from '../contexts/ThemeContext';
import { reservationsAPI, floorPlansAPI, aiWave2API, reservationsAIAPI, reservationFeaturesAPI } from '../services/api';
import { matchTier } from '../lib/bookingTiers';
import { useAuth } from '../contexts/AuthContext';
import { toast } from 'sonner';
import BookingsInbox from './BookingsInbox';
import BookingHeatmap from './BookingHeatmap';
import BookingSourceStrip from '../components/reservations/BookingSourceStrip';
import BookingMonthCalendar from '../components/reservations/BookingMonthCalendar';
import WalkInAISeatDialog from '../components/reservations/WalkInAISeatDialog';
import LiveCallBanner from '../components/bookings/LiveCallBanner';

const TIME_SLOTS = [];
for (let h = 9; h <= 22; h++) {
  for (let m = 0; m < 60; m += 30) {
    TIME_SLOTS.push(`${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`);
  }
}

const STATUS_CONFIG = {
  confirmed: { label: 'Confirmed', color: '#3B82F6', bg: '#EFF6FF' },
  seated: { label: 'Seated', color: '#10B981', bg: '#ECFDF5' },
  completed: { label: 'Completed', color: '#6B7280', bg: '#F3F4F6' },
  cancelled: { label: 'Cancelled', color: '#EF4444', bg: '#FEF2F2' },
  no_show: { label: 'No Show', color: '#F59E0B', bg: '#FFFBEB' },
};

const emptyForm = {
  guestName: '', guestPhone: '', guestEmail: '', customerId: '', partySize: 2,
  date: new Date().toISOString().split('T')[0], time: '19:00', duration: 90,
  tableId: '', section: '', specialRequests: '', notes: '', tags: [],
  depositRequired: 0, source: 'phone', experienceId: null,
};

export default function Reservations() {
  const { theme } = useTheme();
  const { user } = useAuth();
  const [reservations, setReservations] = useState([]);
  const [floorPlans, setFloorPlans] = useState([]);
  const [selectedDate, setSelectedDate] = useState(new Date().toISOString().split('T')[0]);
  const [statusFilter, setStatusFilter] = useState('all');
  const [search, setSearch] = useState('');
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editId, setEditId] = useState(null);
  const [form, setForm] = useState({ ...emptyForm });
  const [bookingRules, setBookingRules] = useState(null);
  const [experiences, setExperiences] = useState([]);
  // A deliberate rule override — only ever set after the server has
  // already rejected a save with a rule violation, and only usable by an
  // owner/manager. Distinct from "no rule was checked" (accidental bypass);
  // this is "a manager typed a reason and chose to proceed anyway."
  const [ruleViolation, setRuleViolation] = useState(null);
  const [overrideReason, setOverrideReason] = useState('');
  const canOverride = user?.role === 'owner' || user?.role === 'manager';
  // CRM guest lookup — matches on name, phone, or email so staff can pull up
  // a returning guest's details instead of retyping them from scratch.
  const [guestMatches, setGuestMatches] = useState([]);
  const [guestIntel, setGuestIntel] = useState(null);
  const [guestSearchOpen, setGuestSearchOpen] = useState(false);
  const [guestSearching, setGuestSearching] = useState(false);
  const guestSearchTimer = useRef(null);
  const [view, setView] = useState('list'); // list | calendar | month
  const [mainTab, setMainTab] = useState('bookings'); // bookings | inbox | heatmap
  const [showWalkinDialog, setShowWalkinDialog] = useState(false);

  const fetchData = useCallback(async () => {
    try {
      const params = { date: selectedDate };
      if (statusFilter !== 'all') params.status = statusFilter;
      const [resRes, fpRes] = await Promise.all([
        reservationsAPI.getAll(params),
        floorPlansAPI.getAll(),
      ]);
      setReservations(resRes.data);
      setFloorPlans(fpRes.data);
    } catch (e) { console.error(e); toast.error('Could not load bookings'); }
  }, [selectedDate, statusFilter]);

  useEffect(() => {
    reservationFeaturesAPI.getBookingRules().then(r => setBookingRules(r.data)).catch(() => {});
    reservationFeaturesAPI.getExperiences().then(r => setExperiences(r.data || [])).catch(() => {});
  }, []);

  const matchedTier = matchTier(bookingRules?.sizeTiers, form.partySize);
  const requiresExperience = !!matchedTier?.requiresExperience;
  const tierExperiences = requiresExperience
    ? (matchedTier.allowedExperienceIds?.length
        ? experiences.filter(e => matchedTier.allowedExperienceIds.includes(e.id))
        : experiences.filter(e => e.active !== false))
    : [];

  useEffect(() => { fetchData(); }, [fetchData]);

  const filtered = reservations.filter(r =>
    !search || r.guestName.toLowerCase().includes(search.toLowerCase()) ||
    (r.guestPhone && r.guestPhone.includes(search))
  );

  const openNew = () => {
    setEditId(null); setForm({ ...emptyForm, date: selectedDate });
    setRuleViolation(null); setOverrideReason('');
    setGuestMatches([]); setGuestIntel(null); setGuestSearchOpen(false); setDialogOpen(true);
  };
  const openEdit = (r) => {
    setEditId(r.id);
    setForm({
      guestName: r.guestName, guestPhone: r.guestPhone || '', guestEmail: r.guestEmail || '',
      customerId: r.customerId || '',
      partySize: r.partySize, date: r.date, time: r.time, duration: r.duration,
      tableId: r.tableId || '', section: r.section || '', specialRequests: r.specialRequests || '',
      notes: r.notes || '', tags: r.tags || [], depositRequired: r.depositRequired || 0,
      source: r.source || 'phone', experienceId: r.experienceId || null,
    });
    setRuleViolation(null); setOverrideReason('');
    setGuestMatches([]); setGuestSearchOpen(false);
    // Editing a booking that's already linked to a guest — pull their history
    // straight up so the same context is there as when it was first taken.
    setGuestIntel(null);
    if (r.customerId) {
      reservationsAPI.guestIntel(r.customerId)
        .then(res => setGuestIntel(res.data))
        .catch(() => {});
    }
    setDialogOpen(true);
  };

  // Debounced CRM lookup — fires off whichever of name/phone/email the staff
  // is currently typing into; guest-lookup matches across all three in one
  // query (phone digit-normalized, so any format matches).
  const searchGuests = (query, field) => {
    if (guestSearchTimer.current) clearTimeout(guestSearchTimer.current);
    const q = query.trim();
    if (q.length < 2) { setGuestMatches([]); setGuestSearchOpen(false); return; }
    guestSearchTimer.current = setTimeout(async () => {
      setGuestSearching(true);
      try {
        const params = { limit: 6 };
        if (field === 'guestPhone') params.phone = q;
        else if (field === 'guestEmail') params.email = q;
        else params.q = q;
        const r = await reservationsAPI.guestLookup(params);
        setGuestMatches(r.data?.matches || []);
        setGuestSearchOpen(true);
      } catch { setGuestMatches([]); }
      setGuestSearching(false);
    }, 300);
  };
  const updateGuestField = (field, value) => {
    // Any manual edit after a guest was picked means it may no longer match
    // that CRM record, so drop the link (and its intel) rather than keep it stale.
    setForm(f => ({ ...f, [field]: value, customerId: '' }));
    setGuestIntel(null);
    searchGuests(value, field);
  };
  const selectGuestMatch = (g) => {
    setForm(f => ({
      ...f,
      guestName: g.name, guestPhone: g.phone || '', guestEmail: g.email || '',
      customerId: g.customerId,
    }));
    // guest-lookup already returns the full summary, so the panel fills in
    // with no extra round-trip.
    setGuestIntel(g);
    setGuestMatches([]); setGuestSearchOpen(false);
  };
  const unlinkGuest = () => { setForm(f => ({ ...f, customerId: '' })); setGuestIntel(null); };

  const handleSave = async () => {
    if (!form.guestName || !form.date || !form.time) {
      toast.error('Guest name, date, and time are required'); return;
    }
    // Client-side mirror of the same large-booking gate the server
    // enforces (see BookingPortal.jsx) — UX only. The actual restriction is
    // POST /reservations re-checking via services.booking_rules_engine, so
    // staff can't accidentally create a large booking that skipped its
    // required experience just because this predicted wrong.
    if (requiresExperience && !form.experienceId && !overrideReason) {
      toast.error(
        `For parties of ${matchedTier.minGuests} or more, bookings require our `
        + `${matchedTier.label || 'Set Menu / Dining Experience'}. Choose one below, or an `
        + `owner/manager can override with a reason.`
      );
      return;
    }
    try {
      // Wave 2 — Overbooking guardrail (only on create)
      if (!editId) {
        try {
          const chk = await aiWave2API.overbookingCheck(form.date, form.time, form.partySize || 2);
          if (chk.data && chk.data.allow === false) {
            const proceed = window.confirm(`⚠️ ${chk.data.reason}\n\nProceed anyway?`);
            if (!proceed) return;
          }
        } catch { /* fail-open: don't block legitimate bookings */ }
      }
      const payload = overrideReason ? { ...form, overrideReason } : form;
      if (editId) {
        await reservationsAPI.update(editId, payload);
        toast.success('Reservation updated');
      } else {
        await reservationsAPI.create(payload);
        toast.success('Reservation created');
      }
      setRuleViolation(null); setOverrideReason('');
      setDialogOpen(false);
      fetchData();
    } catch (e) {
      const detail = e?.response?.data?.detail;
      if (e?.response?.status === 409 && detail) {
        // A genuine booking-rule rejection from the server — not the
        // fail-open advisory check above, which never throws. Surface it
        // inline with an override option instead of a dead-end toast, since
        // "accidentally blocked" and "deliberately need to override" look
        // the same from here and only an owner/manager can do the latter.
        setRuleViolation(detail);
      } else {
        toast.error('Failed to save reservation');
      }
    }
  };

  const handleDelete = async (id) => {
    if (!window.confirm('Permanently delete this reservation? This cannot be undone — use Cancel instead if you just want to mark it cancelled and keep the record.')) return;
    try { await reservationsAPI.delete(id); toast.success('Deleted'); fetchData(); }
    catch (e) { toast.error('Failed to delete'); }
  };

  const handleSeat = async (id) => {
    try { await reservationsAPI.seat(id); toast.success('Guest seated'); fetchData(); }
    catch (e) { toast.error('Failed to seat guest'); }
  };

  const handleComplete = async (id) => {
    try { await reservationsAPI.complete(id); toast.success('Reservation completed'); fetchData(); }
    catch (e) { toast.error('Failed'); }
  };

  const handleNoShow = async (id) => {
    try {
      const { data } = await reservationsAPI.noShow(id, 0);
      toast.warning(data.depositForfeited
        ? `Marked as no-show — $${data.forfeitedAmount.toFixed(2)} deposit forfeited`
        : 'Marked as no-show');
      fetchData();
    } catch (e) { toast.error('Failed'); }
  };

  const handleRequestDeposit = async (id) => {
    try {
      const { data } = await reservationsAPI.requestDeposit(id, window.location.origin);
      if (!data.configured) {
        toast.error('Stripe is not configured for this venue — collect the deposit another way');
        return;
      }
      await navigator.clipboard.writeText(data.url).catch(() => {});
      toast.success('Deposit payment link copied — send it to the guest');
      fetchData();
    } catch (e) { toast.error(e?.response?.data?.detail || 'Failed to create deposit link'); }
  };

  const handleCancel = async (id) => {
    const reason = window.prompt('Reason for cancelling? (optional)') || undefined;
    try { await reservationsAPI.cancel(id, reason); toast.success('Booking cancelled — it can be restored later'); fetchData(); }
    catch (e) { toast.error(e?.response?.data?.detail || 'Failed to cancel'); }
  };

  const handleRestore = async (id) => {
    try { await reservationsAPI.restore(id); toast.success('Booking restored to confirmed'); fetchData(); }
    catch (e) { toast.error(e?.response?.data?.detail || 'Failed to restore'); }
  };

  const handleAutoAssign = async (id) => {
    try {
      // Prefer the AI-aware endpoint (handles time conflicts + section pref);
      // fall back to the legacy auto-assign if it fails for any reason.
      let res;
      try {
        res = await reservationsAIAPI.aiAssignTable(id);
        if (res.data.assigned) {
          toast.success(`AI assigned ${res.data.tableName}${res.data.section ? ` · ${res.data.section}` : ''}`);
        } else {
          toast.warning(res.data.reason || 'No suitable table');
        }
      } catch {
        res = await reservationsAPI.autoAssign(id);
        if (res.data.assigned) toast.success(`Auto-assigned to Table ${res.data.table?.number}`);
        else toast.warning(res.data.message);
      }
      fetchData();
    } catch { toast.error('Auto-assign failed'); }
  };

  const shiftDate = (days) => {
    const d = new Date(selectedDate);
    d.setDate(d.getDate() + days);
    setSelectedDate(d.toISOString().split('T')[0]);
  };

  // Stats
  const todayStats = {
    total: reservations.length,
    confirmed: reservations.filter(r => r.status === 'confirmed').length,
    seated: reservations.filter(r => r.status === 'seated').length,
    covers: reservations.reduce((s, r) => s + r.partySize, 0),
  };

  // Calendar view helpers
  const calendarSlots = TIME_SLOTS.map(slot => ({
    time: slot,
    reservations: filtered.filter(r => r.time === slot),
  }));

  const allTables = floorPlans.flatMap(fp => fp.tables || []);

  return (
    <div className="space-y-6" data-testid="reservations-page">
      <LiveCallBanner />
      {/* Master Tabs: Bookings vs AI Inbox */}
      <Tabs value={mainTab} onValueChange={setMainTab}>
        <TabsList data-testid="reservations-main-tabs">
          <TabsTrigger value="bookings" data-testid="tab-bookings">Bookings</TabsTrigger>
          <TabsTrigger value="inbox" data-testid="tab-inbox">AI Inbox</TabsTrigger>
          <TabsTrigger value="heatmap" data-testid="tab-heatmap">Busy-Time Heatmap</TabsTrigger>
        </TabsList>
        <TabsContent value="inbox" className="mt-6">
          <BookingsInbox />
        </TabsContent>
        <TabsContent value="heatmap" className="mt-6">
          <BookingHeatmap />
        </TabsContent>
        <TabsContent value="bookings" className="mt-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold" style={{ color: theme.text }}>Reservations</h1>
          <p className="text-sm text-gray-500 mt-1">Manage bookings, tables & guest seating</p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            onClick={() => setShowWalkinDialog(true)}
            data-testid="walkin-ai-assign"
          >
            <Users size={16} className="mr-1.5" /> Walk-in → AI Seat
          </Button>
          <Button data-testid="new-reservation-btn" onClick={openNew} style={{ background: theme.primary }}>
            <Plus size={16} className="mr-2" /> New Reservation
          </Button>
        </div>
      </div>

      {/* Stats Row */}
      <div className="grid grid-cols-4 gap-4">
        {[
          { label: 'Total Bookings', val: todayStats.total, icon: CalendarDays, color: theme.primary },
          { label: 'Confirmed', val: todayStats.confirmed, icon: Check, color: '#3B82F6' },
          { label: 'Currently Seated', val: todayStats.seated, icon: UserCheck, color: '#10B981' },
          { label: 'Total Covers', val: todayStats.covers, icon: Users, color: theme.accent },
        ].map((s, i) => (
          <Card key={i} className="border-0 shadow-sm">
            <CardContent className="p-4 flex items-center gap-4">
              <div className="w-10 h-10 rounded-lg flex items-center justify-center" style={{ background: `${s.color}15` }}>
                <s.icon size={20} style={{ color: s.color }} />
              </div>
              <div>
                <p className="text-2xl font-bold" style={{ color: theme.text }}>{s.val}</p>
                <p className="text-xs text-gray-500">{s.label}</p>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Source attribution — 30d rollup from marketing scans + bookings */}
      <BookingSourceStrip theme={theme} />

      {/* Controls */}
      <div className="flex items-center gap-3 flex-wrap">
        <div className="flex items-center gap-1 bg-white rounded-lg border px-1 py-1">
          <Button variant="ghost" size="sm" onClick={() => shiftDate(-1)} data-testid="prev-date-btn"><ChevronLeft size={16} /></Button>
          <Input type="date" value={selectedDate} onChange={e => setSelectedDate(e.target.value)}
            className="border-0 w-40 text-center font-medium" data-testid="date-picker" />
          <Button variant="ghost" size="sm" onClick={() => shiftDate(1)} data-testid="next-date-btn"><ChevronRight size={16} /></Button>
        </div>
        <div className="relative flex-1 max-w-xs">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
          <Input placeholder="Search guest name or phone..." value={search} onChange={e => setSearch(e.target.value)}
            className="pl-9" data-testid="search-reservations" />
        </div>
        <Select value={statusFilter} onValueChange={setStatusFilter}>
          <SelectTrigger className="w-40" data-testid="status-filter">
            <Filter size={14} className="mr-2" /><SelectValue placeholder="All Status" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Status</SelectItem>
            <SelectItem value="confirmed">Confirmed</SelectItem>
            <SelectItem value="seated">Seated</SelectItem>
            <SelectItem value="completed">Completed</SelectItem>
            <SelectItem value="cancelled">Cancelled</SelectItem>
            <SelectItem value="no_show">No Show</SelectItem>
          </SelectContent>
        </Select>
        <Tabs value={view} onValueChange={setView} className="ml-auto">
          <TabsList>
            <TabsTrigger value="list" data-testid="list-view-btn">List</TabsTrigger>
            <TabsTrigger value="calendar" data-testid="calendar-view-btn">Timeline</TabsTrigger>
            <TabsTrigger value="month" data-testid="month-view-btn">Month</TabsTrigger>
          </TabsList>
        </Tabs>
      </div>

      {/* List View */}
      {view === 'list' && (
        <Card className="border-0 shadow-sm">
          <CardContent className="p-0">
            <div className="overflow-x-auto">
              <table className="w-full text-sm" data-testid="reservations-table">
                <thead>
                  <tr className="border-b bg-gray-50/80">
                    <th className="text-left px-4 py-3 font-medium text-gray-500">Time</th>
                    <th className="text-left px-4 py-3 font-medium text-gray-500">Guest</th>
                    <th className="text-left px-4 py-3 font-medium text-gray-500">Party</th>
                    <th className="text-left px-4 py-3 font-medium text-gray-500">Table</th>
                    <th className="text-left px-4 py-3 font-medium text-gray-500">Status</th>
                    <th className="text-left px-4 py-3 font-medium text-gray-500">Source</th>
                    <th className="text-left px-4 py-3 font-medium text-gray-500">Notes</th>
                    <th className="text-right px-4 py-3 font-medium text-gray-500">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.length === 0 ? (
                    <tr><td colSpan={8} className="text-center py-12 text-gray-400">No reservations for this date</td></tr>
                  ) : filtered.map(r => {
                    const st = STATUS_CONFIG[r.status] || STATUS_CONFIG.confirmed;
                    return (
                      <tr key={r.id} className="border-b hover:bg-gray-50/50 transition-colors" data-testid={`reservation-row-${r.id}`}>
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-2">
                            <Clock size={14} className="text-gray-400" />
                            <span className="font-medium">{r.time}</span>
                            <span className="text-xs text-gray-400">{r.duration}m</span>
                          </div>
                        </td>
                        <td className="px-4 py-3">
                          <div>
                            <p className="font-medium" style={{ color: theme.text }}>{r.guestName}</p>
                            <div className="flex items-center gap-2 text-xs text-gray-400">
                              {r.guestPhone && <span className="flex items-center gap-1"><Phone size={10} />{r.guestPhone}</span>}
                              {r.guestEmail && <span className="flex items-center gap-1"><Mail size={10} />{r.guestEmail}</span>}
                            </div>
                          </div>
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-1">
                            <Users size={14} className="text-gray-400" />
                            <span className="font-medium">{r.partySize}</span>
                          </div>
                        </td>
                        <td className="px-4 py-3">
                          {r.tableNumber ? (
                            <Badge variant="outline" className="font-mono">T{r.tableNumber}</Badge>
                          ) : (
                            <span className="text-xs text-gray-400 italic">Unassigned</span>
                          )}
                        </td>
                        <td className="px-4 py-3">
                          <Badge style={{ background: st.bg, color: st.color, border: `1px solid ${st.color}30` }}>
                            {st.label}
                          </Badge>
                        </td>
                        <td className="px-4 py-3">
                          {(() => {
                            const src = (r.source || 'walk_in').toLowerCase();
                            const meta = {
                              walk_in: { label: 'Walk-in', color: '#64748b' },
                              walkin: { label: 'Walk-in', color: '#64748b' },
                              web: { label: 'Web', color: '#0ea5e9' },
                              website: { label: 'Web', color: '#0ea5e9' },
                              phone: { label: 'Phone', color: '#f59e0b' },
                              email: { label: 'Email', color: '#6366f1' },
                              instagram: { label: 'Instagram', color: '#ec4899' },
                              instagram_dm: { label: 'Instagram', color: '#ec4899' },
                              facebook: { label: 'Facebook', color: '#3b82f6' },
                              facebook_dm: { label: 'Facebook', color: '#3b82f6' },
                              whatsapp: { label: 'WhatsApp', color: '#22c55e' },
                              sms: { label: 'SMS', color: '#8b5cf6' },
                              opentable: { label: 'OpenTable', color: '#ef4444' },
                              dine_in: { label: 'Walk-in', color: '#64748b' },
                            };
                            const m = Object.entries(meta).find(([k]) => src.includes(k))?.[1] || { label: src.replace('_', ' '), color: '#64748b' };
                            return (
                              <Badge style={{ background: `${m.color}15`, color: m.color, border: `1px solid ${m.color}40` }} data-testid={`src-${r.id}`}>
                                {m.label}
                              </Badge>
                            );
                          })()}
                        </td>
                        <td className="px-4 py-3 text-xs text-gray-500 max-w-[150px] truncate">{r.specialRequests || r.notes || '—'}</td>
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-1 justify-end">
                            {r.status === 'confirmed' && (
                              <>
                                {r.depositRequired > 0 && !r.depositPaid && (
                                  <Button variant="ghost" size="sm" onClick={() => handleRequestDeposit(r.id)}
                                    className="text-amber-600 hover:bg-amber-50 h-8 px-2" data-testid={`request-deposit-btn-${r.id}`}
                                    title={`Request $${r.depositRequired} deposit`}>
                                    <CreditCard size={14} />
                                  </Button>
                                )}
                                <Button variant="ghost" size="sm" onClick={() => handleSeat(r.id)} data-testid={`seat-btn-${r.id}`}
                                  className="text-green-600 hover:text-green-700 hover:bg-green-50 h-8 px-2">
                                  <UserCheck size={14} className="mr-1" /> Seat
                                </Button>
                                <Button variant="ghost" size="sm" onClick={() => handleAutoAssign(r.id)}
                                  className="text-blue-600 hover:bg-blue-50 h-8 px-2" data-testid={`auto-assign-btn-${r.id}`}>
                                  <MapPin size={14} />
                                </Button>
                                <Button variant="ghost" size="sm" onClick={() => handleNoShow(r.id)}
                                  className="text-yellow-600 hover:bg-yellow-50 h-8 px-2" data-testid={`no-show-btn-${r.id}`}>
                                  <AlertTriangle size={14} />
                                </Button>
                                <Button variant="ghost" size="sm" onClick={() => handleCancel(r.id)}
                                  className="text-red-500 hover:bg-red-50 h-8 px-2" data-testid={`cancel-btn-${r.id}`} title="Cancel booking">
                                  <Ban size={14} />
                                </Button>
                              </>
                            )}
                            {r.status === 'seated' && (
                              <Button variant="ghost" size="sm" onClick={() => handleComplete(r.id)}
                                className="text-gray-600 hover:bg-gray-100 h-8 px-2" data-testid={`complete-btn-${r.id}`}>
                                <Check size={14} className="mr-1" /> Done
                              </Button>
                            )}
                            {(r.status === 'cancelled' || r.status === 'no_show') && (
                              <Button variant="ghost" size="sm" onClick={() => handleRestore(r.id)}
                                className="text-emerald-600 hover:text-emerald-700 hover:bg-emerald-50 h-8 px-2" data-testid={`restore-btn-${r.id}`}>
                                <RotateCcw size={14} className="mr-1" /> Restore
                              </Button>
                            )}
                            <Button variant="ghost" size="sm" onClick={() => openEdit(r)} className="h-8 px-2" data-testid={`edit-btn-${r.id}`}>
                              <Edit2 size={14} />
                            </Button>
                            <Button variant="ghost" size="sm" onClick={() => handleDelete(r.id)}
                              className="text-red-500 hover:bg-red-50 h-8 px-2" data-testid={`delete-btn-${r.id}`} title="Permanently delete (use Cancel to keep a record)">
                              <Trash2 size={14} />
                            </Button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Timeline / Calendar View */}
      {view === 'month' && (
        <BookingMonthCalendar onSelectDate={(d) => { setSelectedDate(d); setView('list'); }} />
      )}
      {view === 'calendar' && (
        <Card className="border-0 shadow-sm">
          <CardContent className="p-4">
            <div className="space-y-1" data-testid="timeline-view">
              {calendarSlots.filter(s => s.time >= '09:00' && s.time <= '22:00').map(slot => (
                <div key={slot.time} className="flex items-start gap-4 py-2 border-b border-gray-100 last:border-0">
                  <div className="w-16 text-sm font-mono text-gray-400 pt-1 shrink-0">{slot.time}</div>
                  <div className="flex-1 flex flex-wrap gap-2 min-h-[32px]">
                    {slot.reservations.length === 0 ? (
                      <div className="text-xs text-gray-300 pt-1">—</div>
                    ) : slot.reservations.map(r => {
                      const st = STATUS_CONFIG[r.status] || STATUS_CONFIG.confirmed;
                      return (
                        <div key={r.id} className="px-3 py-1.5 rounded-lg text-xs font-medium cursor-pointer hover:shadow-md transition-shadow"
                          style={{ background: st.bg, color: st.color, border: `1px solid ${st.color}30` }}
                          onClick={() => openEdit(r)} data-testid={`timeline-res-${r.id}`}>
                          <span className="font-semibold">{r.guestName}</span>
                          <span className="mx-1.5 opacity-50">|</span>
                          <Users size={10} className="inline mb-0.5" /> {r.partySize}
                          {r.tableNumber && <><span className="mx-1.5 opacity-50">|</span>T{r.tableNumber}</>}
                        </div>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Create / Edit Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-w-lg max-h-[90vh] overflow-y-auto" data-testid="reservation-dialog">
          <DialogHeader>
            <DialogTitle>{editId ? 'Edit Reservation' : 'New Reservation'}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3">
              <div className="col-span-2 relative">
                <label className="text-xs font-medium text-gray-500 mb-1 block">Guest Name *</label>
                <div className="relative">
                  <Input
                    data-testid="guest-name-input" value={form.guestName}
                    onChange={e => updateGuestField('guestName', e.target.value)}
                    onFocus={() => { if (guestMatches.length > 0) setGuestSearchOpen(true); }}
                    onBlur={() => setTimeout(() => setGuestSearchOpen(false), 150)}
                    placeholder="John Smith" autoComplete="off"
                  />
                  {guestSearching && (
                    <Search size={13} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-300 animate-pulse" />
                  )}
                </div>
                {guestSearchOpen && guestMatches.length > 0 && (
                  <div className="absolute z-20 left-0 right-0 mt-1 bg-white border rounded-lg shadow-lg max-h-56 overflow-y-auto" data-testid="guest-crm-matches">
                    <p className="text-[10px] uppercase tracking-wide text-gray-400 px-3 pt-2 pb-1">From your customer list</p>
                    {guestMatches.map(c => (
                      <button
                        key={c.customerId} type="button"
                        onMouseDown={() => selectGuestMatch(c)}
                        className="w-full text-left px-3 py-2 hover:bg-gray-50 flex items-center justify-between gap-2 border-t first:border-t-0"
                        data-testid={`guest-match-${c.customerId}`}
                      >
                        <span className="min-w-0">
                          <span className="block text-sm font-medium truncate" style={{ color: theme.text }}>{c.name}</span>
                          <span className="block text-xs text-gray-400 truncate">{[c.phone, c.email].filter(Boolean).join(' · ')}</span>
                          {c.lastVisit?.date && (
                            <span className="block text-[10px] text-gray-400">Last in {c.lastVisit.date}{c.stats?.completedVisits ? ` · ${c.stats.completedVisits} visits` : ''}</span>
                          )}
                        </span>
                        {c.isVip && <Badge className="bg-amber-100 text-amber-700 text-[10px] flex-shrink-0">VIP</Badge>}
                      </button>
                    ))}
                  </div>
                )}
                {form.customerId && (
                  <p className="text-[11px] text-emerald-600 mt-1 flex items-center gap-1" data-testid="guest-linked-badge">
                    <UserCheck size={12} /> Linked to guest profile
                    <button type="button" onClick={unlinkGuest} className="text-gray-400 hover:text-red-500 underline ml-1" data-testid="unlink-guest-btn">unlink</button>
                  </p>
                )}
              </div>

              {/* Guest history — what whoever is taking the booking needs to
                  know before they finish the call. */}
              {guestIntel && form.customerId && (
                <div className="col-span-2 rounded-lg border bg-gray-50/70 p-3 space-y-2" data-testid="guest-intel-panel">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-xs font-semibold" style={{ color: theme.text }}>{guestIntel.name}</span>
                    {guestIntel.isVip && <Badge className="bg-amber-100 text-amber-700 text-[10px]">VIP</Badge>}
                    {guestIntel.membershipTier && <Badge variant="outline" className="text-[10px]">{guestIntel.membershipTier}</Badge>}
                    {(guestIntel.stats?.noShows > 0) && (
                      <Badge className="bg-red-100 text-red-700 text-[10px]" data-testid="guest-noshow-badge">
                        {guestIntel.stats.noShows} no-show{guestIntel.stats.noShows > 1 ? 's' : ''}
                      </Badge>
                    )}
                  </div>

                  <div className="grid grid-cols-2 gap-2 text-[11px]">
                    <div>
                      <span className="text-gray-400 block">Last booked</span>
                      <span style={{ color: theme.text }} data-testid="intel-last-booked">
                        {guestIntel.lastBooking?.date
                          ? `${guestIntel.lastBooking.date} · ${guestIntel.lastBooking.partySize}p`
                          : 'First booking'}
                      </span>
                    </div>
                    <div>
                      <span className="text-gray-400 block">Last came in</span>
                      <span style={{ color: theme.text }} data-testid="intel-last-visit">
                        {guestIntel.lastVisit?.date || '—'}
                      </span>
                    </div>
                  </div>

                  {guestIntel.lastOrderItems?.length > 0 && (
                    <div className="text-[11px]" data-testid="intel-last-order">
                      <span className="text-gray-400 block">Had last time</span>
                      <span style={{ color: theme.text }}>
                        {guestIntel.lastOrderItems.map(i => `${i.quantity}× ${i.name}`).join(', ')}
                      </span>
                    </div>
                  )}

                  {guestIntel.topItems?.length > 0 && (
                    <div className="text-[11px]" data-testid="intel-top-items">
                      <span className="text-gray-400 block">Orders most</span>
                      <span className="flex flex-wrap gap-1 mt-0.5">
                        {guestIntel.topItems.map((i, n) => (
                          <Badge key={n} variant="outline" className="text-[10px] font-normal">
                            {i.name} ×{i.timesOrdered}
                          </Badge>
                        ))}
                      </span>
                    </div>
                  )}

                  {(guestIntel.frequentRequests?.length > 0 || guestIntel.standingPreferences?.length > 0) && (
                    <div className="text-[11px]" data-testid="intel-requests">
                      <span className="text-gray-400 block">Usually asks for</span>
                      <span className="flex flex-wrap gap-1 mt-0.5">
                        {guestIntel.standingPreferences?.map((p, n) => (
                          <Badge key={`p${n}`}
                            className={`text-[10px] font-normal ${p.type === 'allergy' ? 'bg-red-100 text-red-700' : 'bg-blue-50 text-blue-700'}`}>
                            {p.type === 'allergy' ? '⚠ ' : ''}{p.value}
                          </Badge>
                        ))}
                        {guestIntel.frequentRequests?.map((f, n) => (
                          <Badge key={`f${n}`} variant="outline" className="text-[10px] font-normal">
                            {f.request} ({f.times}×)
                          </Badge>
                        ))}
                      </span>
                    </div>
                  )}

                  {guestIntel.frequentRequests?.length > 0 && (
                    <button type="button"
                      onClick={() => setForm(f => ({ ...f, specialRequests: guestIntel.frequentRequests[0].request }))}
                      className="text-[11px] underline text-gray-500 hover:text-gray-800"
                      data-testid="apply-usual-request-btn">
                      Use their usual request
                    </button>
                  )}
                </div>
              )}
              <div>
                <label className="text-xs font-medium text-gray-500 mb-1 block">Phone</label>
                <Input
                  data-testid="guest-phone-input" value={form.guestPhone}
                  onChange={e => updateGuestField('guestPhone', e.target.value)}
                  onFocus={() => { if (guestMatches.length > 0) setGuestSearchOpen(true); }}
                  onBlur={() => setTimeout(() => setGuestSearchOpen(false), 150)}
                  placeholder="+61 400 000 000" autoComplete="off"
                />
              </div>
              <div>
                <label className="text-xs font-medium text-gray-500 mb-1 block">Email</label>
                <Input
                  data-testid="guest-email-input" value={form.guestEmail}
                  onChange={e => updateGuestField('guestEmail', e.target.value)}
                  onFocus={() => { if (guestMatches.length > 0) setGuestSearchOpen(true); }}
                  onBlur={() => setTimeout(() => setGuestSearchOpen(false), 150)}
                  placeholder="guest@email.com" autoComplete="off"
                />
              </div>
              <div>
                <label className="text-xs font-medium text-gray-500 mb-1 block">Date *</label>
                <Input type="date" data-testid="res-date-input" value={form.date} onChange={e => setForm(f => ({ ...f, date: e.target.value }))} />
              </div>
              <div>
                <label className="text-xs font-medium text-gray-500 mb-1 block">Time *</label>
                <Select value={form.time} onValueChange={v => setForm(f => ({ ...f, time: v }))}>
                  <SelectTrigger data-testid="res-time-select"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {TIME_SLOTS.map(t => <SelectItem key={t} value={t}>{t}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <label className="text-xs font-medium text-gray-500 mb-1 block">Party Size</label>
                <Input type="number" data-testid="party-size-input" min={1} max={50} value={form.partySize}
                  onChange={e => {
                    const partySize = parseInt(e.target.value) || 1;
                    setForm(f => ({ ...f, partySize, experienceId: null }));
                    setRuleViolation(null); setOverrideReason('');
                  }} />
              </div>
              <div>
                <label className="text-xs font-medium text-gray-500 mb-1 block">Duration (min)</label>
                <Select value={String(form.duration)} onValueChange={v => setForm(f => ({ ...f, duration: parseInt(v) }))}>
                  <SelectTrigger data-testid="duration-select"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {[30, 60, 90, 120, 150, 180].map(d => <SelectItem key={d} value={String(d)}>{d} min</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <label className="text-xs font-medium text-gray-500 mb-1 block">Table</label>
                <Select value={form.tableId || 'none'} onValueChange={v => setForm(f => ({ ...f, tableId: v === 'none' ? '' : v }))}>
                  <SelectTrigger data-testid="table-select"><SelectValue placeholder="Auto-assign" /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="none">Auto-assign</SelectItem>
                    {allTables.map(t => (
                      <SelectItem key={t.id} value={t.id}>Table {t.number} (seats {t.maxCovers})</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <label className="text-xs font-medium text-gray-500 mb-1 block">Source</label>
                <Select value={form.source} onValueChange={v => setForm(f => ({ ...f, source: v }))}>
                  <SelectTrigger data-testid="source-select"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="phone">Phone</SelectItem>
                    <SelectItem value="online">Online</SelectItem>
                    <SelectItem value="walk_in">Walk-in</SelectItem>
                    <SelectItem value="app">App</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div>
                <label className="text-xs font-medium text-gray-500 mb-1 block">Deposit ($)</label>
                <Input type="number" data-testid="deposit-input" min={0} value={form.depositRequired}
                  onChange={e => setForm(f => ({ ...f, depositRequired: parseFloat(e.target.value) || 0 }))} />
              </div>
              <div className="col-span-2">
                <label className="text-xs font-medium text-gray-500 mb-1 block">Special Requests</label>
                <Input data-testid="special-requests-input" value={form.specialRequests}
                  onChange={e => setForm(f => ({ ...f, specialRequests: e.target.value }))} placeholder="Window seat, high chair, birthday..." />
              </div>
              <div className="col-span-2">
                <label className="text-xs font-medium text-gray-500 mb-1 block">Internal Notes</label>
                <Input data-testid="notes-input" value={form.notes}
                  onChange={e => setForm(f => ({ ...f, notes: e.target.value }))} placeholder="Staff notes..." />
              </div>
            </div>

            {requiresExperience && (
              <div className="mt-4 p-3 rounded-lg bg-amber-50 border border-amber-200" data-testid="res-large-booking-notice">
                <p className="text-sm font-semibold text-amber-900 mb-1">
                  Large Booking — {matchedTier.label || 'requires an experience'}
                </p>
                <p className="text-xs text-amber-800 mb-2">
                  Parties of {matchedTier.minGuests}{matchedTier.maxGuests ? `–${matchedTier.maxGuests}` : '+'} require
                  {matchedTier.requireDeposit ? ' a deposit,' : ''}{matchedTier.requirePreOrder ? ' a pre-order,' : ''}
                  {matchedTier.requireApproval ? ' owner/manager approval,' : ''} an experience selection below.
                </p>
                {tierExperiences.length === 0 ? (
                  <p className="text-xs text-red-600">No experiences configured for this tier — add one under Marketing &gt; Experiences, or an owner/manager can override below.</p>
                ) : (
                  <div className="flex flex-wrap gap-1.5">
                    {tierExperiences.map(exp => (
                      <button key={exp.id} type="button" onClick={() => setForm(f => ({ ...f, experienceId: exp.id }))}
                        data-testid={`res-experience-${exp.id}`}
                        className={`px-2.5 py-1 text-xs rounded-full font-medium ${form.experienceId === exp.id ? 'bg-gray-900 text-white' : 'bg-white border border-gray-300 text-gray-600'}`}>
                        {exp.name}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}

            {ruleViolation && (
              <div className="mt-4 p-3 rounded-lg bg-red-50 border border-red-200" data-testid="res-rule-violation">
                <p className="text-sm font-semibold text-red-800 mb-1">Booking rule blocked this reservation</p>
                <p className="text-xs text-red-700 mb-2">{ruleViolation}</p>
                {canOverride ? (
                  <div className="flex gap-2">
                    <Input placeholder="Reason for override (required, audit-logged)" value={overrideReason}
                      onChange={e => setOverrideReason(e.target.value)} className="text-xs h-8" data-testid="override-reason-input" />
                    <Button size="sm" variant="outline" disabled={!overrideReason.trim()}
                      onClick={handleSave} data-testid="override-save-btn">
                      Override &amp; Save
                    </Button>
                  </div>
                ) : (
                  <p className="text-xs text-red-600">Ask an owner or manager to override this rule if this booking is intentional.</p>
                )}
              </div>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)} data-testid="cancel-reservation-btn">Cancel</Button>
            <Button onClick={handleSave} style={{ background: theme.primary }} data-testid="save-reservation-btn">
              {editId ? 'Update' : 'Create'} Reservation
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <WalkInAISeatDialog
        open={showWalkinDialog}
        onClose={() => setShowWalkinDialog(false)}
        onSeated={fetchData}
      />
        </TabsContent>
      </Tabs>
    </div>
  );
}
