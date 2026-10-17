import React, { useEffect, useRef, useState } from 'react';
import { Card, CardContent } from '../ui/card';
import { Button } from '../ui/button';
import { Input } from '../ui/input';
import { Badge } from '../ui/badge';
import { X, Send, Clock, Users, Utensils, ChevronRight, Settings2, BellRing, Crown, Loader2 } from 'lucide-react';
import { tableCoursesAPI, reservationsAPI } from '../../services/api';
import { useTheme } from '../../contexts/ThemeContext';
import { toast } from 'sonner';
import { DialogService } from '../../platform';

const VIP_COLOR = '#db2777'; // NUA_POS_DESIGN_TOKENS.md §6 — VIP is pink, Reserved is purple

/**
 * Slide-in drawer for a table on the floor plan.
 *
 * Shows the live state — current course, dwell timer, party info — with
 * shortcuts to advance the course, seat/clear, and "Send" a nudge to the
 * assigned server. Owners/managers can also open the course-thresholds
 * settings pane from here.
 */
export const TableInfoDrawer = ({ open, onClose, table, states, courses, overdueColour, onRefresh, onOpenCourseSettings }) => {
  const { darkMode } = useTheme();
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');
  const [priority, setPriority] = useState('normal');
  const [tick, setTick] = useState(0);

  // Optional guest attach when seating — lets a table pick up the VIP
  // purple ring automatically (via the guest's own isVip flag) instead of
  // needing a separate manual toggle.
  const [guestQuery, setGuestQuery] = useState('');
  const [guestMatches, setGuestMatches] = useState([]);
  const [guestSearching, setGuestSearching] = useState(false);
  const [guestSearchOpen, setGuestSearchOpen] = useState(false);
  const [pickedGuest, setPickedGuest] = useState(null);
  const guestSearchTimer = useRef(null);

  // Refresh the dwell timer every 15s so the on-screen minutes stay accurate.
  useEffect(() => {
    if (!open) return;
    const id = setInterval(() => setTick(t => t + 1), 15_000);
    return () => clearInterval(id);
  }, [open]);

  // Fresh guest picker each time the drawer opens on a (possibly different) table.
  useEffect(() => {
    if (!open) return;
    setGuestQuery(''); setGuestMatches([]); setGuestSearchOpen(false); setPickedGuest(null);
  }, [open, table?.id]);

  if (!open || !table) return null;

  const state = (states || []).find(s => s.tableId === table.id);
  const currentCourseKey = state?.course || null;
  const currentCourseObj = (courses || []).find(c => c.key === currentCourseKey);

  const dwell = state?.dwellMinutes ?? 0;
  const courseMin = state?.courseMinutes ?? 0;
  const overdue = state?.overdue;
  const isVip = !!state?.isVip;

  const advanceCourse = async (nextKey) => {
    setBusy(true);
    try {
      await tableCoursesAPI.upsertState({ tableId: table.id, course: nextKey });
      toast.success(`Course → ${nextKey}`);
      onRefresh && onRefresh();
    } catch (e) {
      toast.error('Failed to advance course');
    } finally { setBusy(false); }
  };

  const searchGuests = (query) => {
    if (guestSearchTimer.current) clearTimeout(guestSearchTimer.current);
    const q = query.trim();
    if (q.length < 2) { setGuestMatches([]); setGuestSearchOpen(false); return; }
    guestSearchTimer.current = setTimeout(async () => {
      setGuestSearching(true);
      try {
        const r = await reservationsAPI.guestLookup({ q, limit: 6 });
        setGuestMatches(r.data?.matches || []);
        setGuestSearchOpen(true);
      } catch { setGuestMatches([]); }
      setGuestSearching(false);
    }, 300);
  };
  const onGuestQueryChange = (v) => {
    setGuestQuery(v); setPickedGuest(null); searchGuests(v);
  };
  const selectGuest = (g) => {
    setPickedGuest(g);
    setGuestQuery(g.name);
    setGuestMatches([]); setGuestSearchOpen(false);
  };

  const seatTable = async () => {
    setBusy(true);
    try {
      await tableCoursesAPI.upsertState({
        tableId: table.id, course: 'seated', partySize: table.capacity || 2,
        customerId: pickedGuest?.customerId || null,
        guestName: pickedGuest?.name || guestQuery.trim() || null,
      });
      toast.success('Table seated');
      onRefresh && onRefresh();
    } finally { setBusy(false); }
  };

  const clearTable = async () => {
    if (!await DialogService.confirm('Clear this table state?')) return;
    setBusy(true);
    try {
      await tableCoursesAPI.upsertState({ tableId: table.id, clearState: true });
      toast.success('Table cleared');
      onRefresh && onRefresh();
    } finally { setBusy(false); }
  };

  const send = async () => {
    setBusy(true);
    try {
      await tableCoursesAPI.send({
        tableId: table.id,
        message: msg || 'Please check on this table',
        priority,
      });
      toast.success('Nudge sent to server');
      setMsg('');
    } catch {
      toast.error('Failed to send');
    } finally { setBusy(false); }
  };

  const dwellLabel = dwell < 60 ? `${dwell}m` : `${Math.floor(dwell / 60)}h ${dwell % 60}m`;

  return (
    <div
      className={`fixed inset-y-0 right-0 z-50 w-full sm:w-96 shadow-2xl border-l flex flex-col ${darkMode ? 'text-[#eaeaea]' : ''}`}
      style={{ borderLeft: `4px solid ${state?.colour || '#e5e7eb'}`, background: darkMode ? 'var(--nua-surface)' : 'white' }}
      data-testid="table-drawer"
    >
      <div className="p-4 border-b flex items-center justify-between" style={{ background: state?.colour || '#f9fafb' }}>
        <div className="text-white">
          <div className="text-xs uppercase tracking-widest opacity-80 flex items-center gap-1">
            Table {isVip && <span className="inline-flex items-center gap-0.5 bg-white/25 rounded px-1"><Crown size={10} /> VIP</span>}
          </div>
          <div className="text-2xl font-bold">#{table.number}</div>
          <div className="text-xs opacity-80">
            {table.section || '—'} · seats {table.capacity || table.maxCovers}
          </div>
        </div>
        <button onClick={onClose} className="text-white p-1 rounded hover:bg-white/20" data-testid="close-drawer">
          <X size={18} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {/* Live state */}
        {state ? (
          <>
            <Card data-testid="table-live-state">
              <CardContent className="p-3 space-y-2">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-1">
                    <Badge className="capitalize" style={{ background: state.colour, color: 'white' }}>
                      {currentCourseObj?.label || state.course}
                    </Badge>
                    {isVip && (
                      <Badge style={{ background: VIP_COLOR, color: 'white' }} className="flex items-center gap-0.5" data-testid="vip-badge">
                        <Crown size={10} /> VIP
                      </Badge>
                    )}
                  </div>
                  <div className="text-xs text-gray-500 flex items-center gap-1">
                    <Clock size={11} /> in course {courseMin}m {overdue && <span className="font-semibold" style={{ color: overdueColour || '#f58c14' }}>· OVERDUE</span>}
                  </div>
                </div>
                <div className="text-xs text-gray-600 flex items-center gap-2">
                  <Users size={11} /> Party of {state.partySize ?? '—'} · seated {dwellLabel}
                </div>
                {state.guestName && <div className="text-xs">Guest: <strong>{state.guestName}</strong></div>}
                {state.serverId && <div className="text-[10px] text-gray-500">Server: {state.serverId}</div>}
                {state.note && <div className="text-[10px] text-gray-500">Note: {state.note}</div>}
              </CardContent>
            </Card>

            {/* Course advance */}
            <div>
              <div className="text-[10px] uppercase tracking-widest text-gray-500 font-semibold mb-1 flex items-center justify-between">
                <span>Advance course</span>
                {onOpenCourseSettings && (
                  <button onClick={onOpenCourseSettings} className="text-blue-600 hover:underline flex items-center gap-0.5" data-testid="open-course-settings">
                    <Settings2 size={10} /> Configure
                  </button>
                )}
              </div>
              <div className="flex flex-wrap gap-1">
                {(courses || []).map(c => (
                  <button
                    key={c.key}
                    onClick={() => advanceCourse(c.key)}
                    disabled={busy || c.key === currentCourseKey}
                    data-testid={`course-btn-${c.key}`}
                    className={`px-2 py-1 rounded-full text-xs font-medium border transition
                      ${c.key === currentCourseKey ? 'opacity-40 cursor-not-allowed' : 'hover:scale-105'}
                    `}
                    style={{
                      background: c.key === currentCourseKey ? c.colour : 'white',
                      color: c.key === currentCourseKey ? 'white' : c.colour,
                      borderColor: c.colour,
                    }}
                  >
                    {c.label}
                  </button>
                ))}
              </div>
              {currentCourseObj?.next && (
                <div className="mt-1 text-[10px] text-gray-500">
                  Next: <button className="underline" onClick={() => advanceCourse(currentCourseObj.next)} data-testid="next-course-quick">
                    {(courses || []).find(x => x.key === currentCourseObj.next)?.label || currentCourseObj.next} <ChevronRight size={9} className="inline" />
                  </button>
                </div>
              )}
            </div>
          </>
        ) : (
          <Card data-testid="table-empty">
            <CardContent className="p-3 text-sm text-gray-500 space-y-2">
              <p className="text-center">No live state — table isn&apos;t seated.</p>
              <div className="relative">
                <Input
                  value={guestQuery}
                  onChange={e => onGuestQueryChange(e.target.value)}
                  onFocus={() => guestMatches.length > 0 && setGuestSearchOpen(true)}
                  onBlur={() => setTimeout(() => setGuestSearchOpen(false), 150)}
                  placeholder="Guest name (optional — links VIP status)"
                  data-testid="seat-guest-search"
                />
                {guestSearching && <Loader2 size={14} className="animate-spin absolute right-2 top-1/2 -translate-y-1/2 text-gray-400" />}
                {guestSearchOpen && guestMatches.length > 0 && (
                  <div className="absolute z-10 mt-1 w-full bg-white border rounded-md shadow-lg max-h-48 overflow-y-auto" data-testid="seat-guest-matches">
                    {guestMatches.map(g => (
                      <button key={g.customerId || g.id} type="button"
                        onMouseDown={() => selectGuest(g)}
                        className="w-full text-left px-3 py-2 text-xs hover:bg-gray-50 flex items-center justify-between border-b last:border-b-0"
                        data-testid={`seat-guest-match-${g.customerId || g.id}`}>
                        <span>{g.name} {g.phone && <span className="text-gray-400">· {g.phone}</span>}</span>
                        {g.isVip && <Badge style={{ background: VIP_COLOR, color: 'white' }} className="text-[9px]">VIP</Badge>}
                      </button>
                    ))}
                  </div>
                )}
              </div>
              {pickedGuest?.isVip && (
                <div className="text-[10px] flex items-center gap-1" style={{ color: VIP_COLOR }}>
                  <Crown size={10} /> VIP guest — table will show the VIP ring once seated
                </div>
              )}
              <Button onClick={seatTable} disabled={busy} size="sm" className="w-full" data-testid="seat-table">
                <Utensils size={12} className="mr-1" /> Seat this table
              </Button>
            </CardContent>
          </Card>
        )}

        {/* Send nudge */}
        <Card data-testid="send-nudge-card">
          <CardContent className="p-3 space-y-2">
            <div className="text-xs font-semibold flex items-center gap-1"><BellRing size={12} /> Send to server</div>
            <Input value={msg} onChange={e => setMsg(e.target.value)}
              placeholder="Optional message (e.g. 'Party ready to order')"
              data-testid="nudge-message" />
            <div className="flex items-center gap-2 text-xs">
              <label className="flex items-center gap-1"><input type="radio" checked={priority === 'normal'} onChange={() => setPriority('normal')} data-testid="priority-normal" /> Normal</label>
              <label className="flex items-center gap-1"><input type="radio" checked={priority === 'urgent'} onChange={() => setPriority('urgent')} data-testid="priority-urgent" /> Urgent</label>
              <Button onClick={send} disabled={busy} size="sm" className="ml-auto" data-testid="send-nudge">
                <Send size={12} className="mr-1" /> Send
              </Button>
            </div>
          </CardContent>
        </Card>

        {state && (
          <Button variant="outline" size="sm" onClick={clearTable} disabled={busy} className="w-full" data-testid="clear-table-state">
            Clear table state
          </Button>
        )}
      </div>
    </div>
  );
};
