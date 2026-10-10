import React, { useState, useEffect } from 'react';
import {
  Clock, LogIn, LogOut, Calendar, DollarSign, Users, FileText,
  Plus, Trash2, BarChart3, Printer, GripVertical, Move, Brain,
  CalendarOff, Check, X, Pencil, Settings2
} from 'lucide-react';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Card, CardContent } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '../components/ui/dialog';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs';
import { useTheme } from '../contexts/ThemeContext';
import { useAuth } from '../contexts/AuthContext';
import { staffMgmtAPI } from '../services/api';
import { toast } from 'sonner';
import axios from 'axios';
import { effectiveHourlyRate, salaryTypeSuffix } from '../lib/staffPay';
import { DndContext, useDraggable, useDroppable, DragOverlay, PointerSensor, KeyboardSensor, useSensor, useSensors } from '@dnd-kit/core';

const API = process.env.REACT_APP_BACKEND_URL;
const authHeader = () => ({ Authorization: `Bearer ${localStorage.getItem('nua_token')}` });

// ===== Draggable Shift Card (used inside week roster grid) =====
function DraggableShift({ shift, hours, canManage, onDelete, theme }) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({ id: shift.id, data: shift });
  return (
    <div
      ref={setNodeRef}
      draggable={canManage}
      data-shift-id={shift.id}
      className={`p-2 rounded-lg text-xs border bg-white hover:shadow-md group transition-all ${isDragging ? 'opacity-30' : ''} ${canManage ? 'cursor-grab active:cursor-grabbing' : ''}`}
      data-testid={`roster-shift-${shift.id}`}
    >
      <div className="flex items-center justify-between gap-1">
        {canManage && <GripVertical size={11} className="text-gray-300 flex-shrink-0" {...listeners} {...attributes} />}
        <p className="font-semibold truncate flex-1">{shift.staffName}</p>
        {canManage && <button className="opacity-0 group-hover:opacity-100 text-red-400 hover:text-red-600 transition-opacity" onClick={onDelete}><Trash2 size={11} /></button>}
      </div>
      <Badge variant="outline" className="text-[9px] mt-0.5">{shift.notes || shift.role || '-'}</Badge>
      <p className="text-gray-500 mt-0.5">{shift.startTime} - {shift.endTime}</p>
      <p className="text-gray-400 text-[10px]">{hours.toFixed(1)}h</p>
    </div>
  );
}

// ===== Droppable Day Column =====
function DroppableDay({ day, children, dayCost, theme }) {
  const { isOver, setNodeRef } = useDroppable({ id: `day-${day}` });
  return (
    <td
      ref={setNodeRef}
      className={`p-2 border-r last:border-r-0 min-w-[140px] align-top transition-colors ${isOver ? 'bg-blue-50 ring-2 ring-blue-300 ring-inset' : ''}`}
      data-testid={`roster-day-${day.toLowerCase()}`}
    >
      <div className="space-y-1.5 min-h-[80px]">{children}</div>
      {dayCost > 0 && (
        <div className="mt-2 pt-2 border-t border-dashed text-[10px] text-gray-500 text-center" data-testid={`day-cost-${day.toLowerCase()}`}>
          <span className="font-semibold" style={{ color: theme.primary }}>${dayCost.toFixed(0)}</span>
        </div>
      )}
    </td>
  );
}

const DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
const POSITIONS = ['Barista', 'Bar', 'Floor', 'Kitchen', 'Register', 'Manager', 'Host', 'Dishwasher'];

export default function StaffRoster() {
  const { theme } = useTheme();
  const { user } = useAuth();
  const isOwner = user?.role === 'owner';
  const isManager = user?.role === 'manager';
  const canManage = isOwner || isManager;
  const [tab, setTab] = useState('roster');
  const [clockStatus, setClockStatus] = useState(null);
  const [timecards, setTimecards] = useState([]);
  const [roster, setRoster] = useState([]);
  const [staff, setStaff] = useState([]);
  const [payrun, setPayrun] = useState(null);
  const [payHistory, setPayHistory] = useState([]);
  const [staffReports, setStaffReports] = useState(null);
  const [reportPeriod, setReportPeriod] = useState('week');
  const [payPeriod, setPayPeriod] = useState('week');
  const [breakMins, setBreakMins] = useState('0');
  const [activeDrag, setActiveDrag] = useState(null);
  // Week roster form
  const [showWeekRoster, setShowWeekRoster] = useState(false);
  const [weekForm, setWeekForm] = useState({ staffId: '', position: 'Floor', weekStart: '', shifts: {} });
  // Time off / leave requests
  const [timeOff, setTimeOff] = useState([]);
  const [showTimeOffDialog, setShowTimeOffDialog] = useState(false);
  const [timeOffForm, setTimeOffForm] = useState({ startDate: '', endDate: '', reason: '' });
  // Timecard edit (owner/manager fix-up)
  const [editingTimecard, setEditingTimecard] = useState(null);
  const [timecardEditForm, setTimecardEditForm] = useState({ clockOut: '', breakMinutes: '0' });
  // Smart Rostering settings — owner-only full control over the industry-
  // standard shift rules and cost/revenue targets auto-roster generates against.
  const [showRosterSettings, setShowRosterSettings] = useState(false);
  const [rosterSettings, setRosterSettings] = useState(null);
  // AI Auto-Roster draft — a proposal to review before anything touches the
  // real roster, not an instant commit.
  const [draftRoster, setDraftRoster] = useState(null);
  const [showDraftPreview, setShowDraftPreview] = useState(false);
  const [committingDraft, setCommittingDraft] = useState(false);
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor)
  );

  useEffect(() => { fetchAll(); }, []);
  useEffect(() => { fetchReports(); }, [reportPeriod]);

  const fetchAll = async () => {
    try {
      const [status, tc, ros, st] = await Promise.all([
        staffMgmtAPI.myStatus(), staffMgmtAPI.getTimecards(),
        staffMgmtAPI.getRoster(), axios.get(`${API}/api/auth/staff`, { headers: authHeader() }),
      ]);
      setClockStatus(status.data);
      setTimecards(tc.data);
      setRoster(ros.data);
      setStaff(st.data.filter(s => s.role !== 'owner'));
    } catch (e) { toast.error(e.response?.data?.detail || 'Failed to load roster data — check your connection and reload'); }
    const [payRes, timeOffRes] = await Promise.allSettled([
      isOwner ? staffMgmtAPI.getPayrunHistory() : Promise.resolve(null),
      staffMgmtAPI.listTimeOff(),
    ]);
    if (isOwner) {
      if (payRes.status === 'fulfilled') setPayHistory(payRes.value.data);
      else toast.error('Failed to load payrun history');
    }
    if (timeOffRes.status === 'fulfilled') setTimeOff(timeOffRes.value.data);
    else toast.error('Failed to load time-off requests');
  };

  const fetchReports = async () => {
    if (canManage) {
      try { const r = await staffMgmtAPI.getStaffReports({ period: reportPeriod }); setStaffReports(r.data); } catch { toast.error('Failed to load staff reports'); }
    }
  };

  const handleClockIn = async () => { try { await staffMgmtAPI.clockIn(); toast.success('Clocked in!'); fetchAll(); } catch (e) { toast.error(e.response?.data?.detail || 'Failed'); } };
  const handleClockOut = async () => { try { await staffMgmtAPI.clockOut({ breakMinutes: parseInt(breakMins) || 0 }); toast.success('Clocked out!'); fetchAll(); } catch (e) { toast.error(e.response?.data?.detail || 'Failed'); } };
  const handleDeleteShift = async (id) => { try { await staffMgmtAPI.deleteRosterShift(id); toast.success('Shift removed'); fetchAll(); } catch (e) { toast.error(e.response?.data?.detail || 'Failed to remove shift'); } };

  const handleCommitDraft = async () => {
    if (!draftRoster?.suggestions?.length) return;
    setCommittingDraft(true);
    try {
      const { v15API } = await import('../services/api');
      await v15API.commitAutoRoster(draftRoster.suggestions);
      toast.success(`Created ${draftRoster.suggestions.length} shifts`);
      setShowDraftPreview(false);
      setDraftRoster(null);
      fetchAll();
    } catch { toast.error('Failed to commit draft roster'); }
    setCommittingDraft(false);
  };

  // Blackout/approved-leave conflicts come back as a 409 with a human reason.
  // Offer an explicit override rather than silently failing or silently blocking.
  const createShiftWithOverride = async (payload) => {
    try {
      await staffMgmtAPI.createRosterShift(payload);
      return true;
    } catch (e) {
      if (e.response?.status === 409) {
        const reason = e.response.data?.detail || 'This staff member is unavailable on that day';
        if (window.confirm(`${reason}. Schedule them anyway?`)) {
          await staffMgmtAPI.createRosterShift({ ...payload, overrideBlackout: true });
          return true;
        }
        return false;
      }
      throw e;
    }
  };

  // ===== Time Off / Leave Requests =====
  const handleRequestTimeOff = async () => {
    if (!timeOffForm.startDate || !timeOffForm.endDate || !timeOffForm.reason) {
      toast.error('Fill in the dates and a reason'); return;
    }
    try {
      await staffMgmtAPI.requestTimeOff(timeOffForm);
      toast.success('Time off requested');
      setShowTimeOffDialog(false);
      setTimeOffForm({ startDate: '', endDate: '', reason: '' });
      fetchAll();
    } catch (e) { toast.error(e.response?.data?.detail || 'Failed to submit request'); }
  };
  const handleApproveTimeOff = async (id) => {
    try {
      const r = await staffMgmtAPI.approveTimeOff(id);
      const conflicts = r.data?.conflictingShifts || [];
      toast.success(conflicts.length ? `Approved — ${conflicts.length} scheduled shift(s) now conflict, check the roster` : 'Approved');
      fetchAll();
    } catch { toast.error('Failed to approve'); }
  };
  const handleRejectTimeOff = async (id) => {
    try { await staffMgmtAPI.rejectTimeOff(id); toast.success('Request declined'); fetchAll(); }
    catch { toast.error('Failed to decline'); }
  };
  const handleCancelTimeOff = async (id) => {
    try { await staffMgmtAPI.cancelTimeOff(id); toast.success('Request cancelled'); fetchAll(); }
    catch { toast.error('Failed to cancel'); }
  };

  // ===== Timecard edit (owner/manager fix-up) =====
  const openTimecardEdit = (tc) => {
    setEditingTimecard(tc);
    setTimecardEditForm({
      clockOut: tc.clockOut ? tc.clockOut.slice(0, 16) : '',
      breakMinutes: String(tc.breakMinutes || 0),
    });
  };
  const handleSaveTimecardEdit = async () => {
    if (!editingTimecard) return;
    try {
      await staffMgmtAPI.editTimecard(editingTimecard.id, {
        clockOut: timecardEditForm.clockOut ? new Date(timecardEditForm.clockOut).toISOString() : undefined,
        breakMinutes: parseInt(timecardEditForm.breakMinutes) || 0,
      });
      toast.success('Timecard updated');
      setEditingTimecard(null);
      fetchAll();
    } catch (e) { toast.error(e.response?.data?.detail || 'Failed to update timecard'); }
  };

  // ===== Smart Rostering settings (owner-only) =====
  const openRosterSettings = async () => {
    try {
      const { v15API } = await import('../services/api');
      const r = await v15API.getRosteringSettings();
      setRosterSettings(r.data);
      setShowRosterSettings(true);
    } catch { toast.error('Failed to load rostering settings'); }
  };
  const saveRosterSettings = async () => {
    try {
      const { v15API } = await import('../services/api');
      await v15API.updateRosteringSettings(rosterSettings);
      toast.success('Rostering settings saved');
      setShowRosterSettings(false);
    } catch (e) { toast.error(e.response?.data?.detail || 'Failed to save'); }
  };

  // ===== Drag-and-Drop Handlers =====
  const handleDragStart = (event) => { setActiveDrag(event.active.data.current); };
  const handleDragEnd = async (event) => {
    setActiveDrag(null);
    const { active, over } = event;
    if (!over) return;
    const newDay = String(over.id).replace('day-', '');
    const shift = active.data.current;
    if (!shift || shift.date === newDay) return;
    // Optimistic UI update
    setRoster(prev => prev.map(s => s.id === shift.id ? { ...s, date: newDay } : s));
    try {
      await staffMgmtAPI.updateRosterShift(shift.id, { date: newDay });
      toast.success(`${shift.staffName} moved to ${newDay}`);
    } catch (e) {
      if (e.response?.status === 409) {
        const reason = e.response.data?.detail || 'This staff member is unavailable on that day';
        if (window.confirm(`${reason}. Move them anyway?`)) {
          try {
            await staffMgmtAPI.updateRosterShift(shift.id, { date: newDay, overrideBlackout: true });
            toast.success(`${shift.staffName} moved to ${newDay} (override)`);
            return;
          } catch { /* fall through to rollback below */ }
        }
      } else {
        toast.error('Failed to move shift');
      }
      fetchAll(); // rollback
    }
  };

  const calcShiftHours = (s) => {
    const start = s.startTime?.split(':').map(Number) || [0, 0];
    const end = s.endTime?.split(':').map(Number) || [0, 0];
    return Math.max((end[0] + end[1] / 60) - (start[0] + start[1] / 60), 0);
  };

  // Week Roster — add shifts for entire week at once
  const handleAddWeekRoster = async () => {
    const staffMember = staff.find(s => s.id === weekForm.staffId);
    if (!staffMember) { toast.error('Select a staff member'); return; }
    const activeDays = Object.entries(weekForm.shifts).filter(([_, v]) => v.enabled);
    if (activeDays.length === 0) { toast.error('Select at least one day'); return; }

    let created = 0, skipped = 0;
    for (const [day, shift] of activeDays) {
      try {
        const ok = await createShiftWithOverride({
          staffId: weekForm.staffId, staffName: staffMember.name,
          date: day, weekStart: weekForm.weekStart,
          startTime: shift.startTime, endTime: shift.endTime,
          role: weekForm.position, notes: weekForm.position,
        });
        if (ok) created++; else skipped++;
      } catch { skipped++; }
    }
    toast.success(`${created} shift(s) added for ${staffMember.name}` + (skipped ? ` (${skipped} skipped)` : ''));
    setShowWeekRoster(false);
    setWeekForm({ staffId: '', position: 'Floor', weekStart: '', shifts: {} });
    fetchAll();
  };

  // Calculate weekly budget from roster
  const getWeeklyBudget = () => {
    let totalHours = 0;
    let totalCost = 0;
    const dayCosts = {};
    roster.forEach(s => {
      const staffMember = staff.find(st => st.id === s.staffId) || {};
      const start = s.startTime?.split(':').map(Number) || [0, 0];
      const end = s.endTime?.split(':').map(Number) || [0, 0];
      const hours = Math.max((end[0] + end[1] / 60) - (start[0] + start[1] / 60), 0);
      const cost = hours * effectiveHourlyRate(staffMember.payRate, staffMember.salaryType);
      totalHours += hours;
      totalCost += cost;
      const day = s.date || 'Unknown';
      dayCosts[day] = (dayCosts[day] || 0) + cost;
    });
    return { totalHours: totalHours.toFixed(1), totalCost: totalCost.toFixed(2), dayCosts };
  };

  // PRINT ROSTER — No wages, no tips
  const printRoster = () => {
    const w = window.open('', '_blank', 'width=800,height=600');
    const grouped = {};
    roster.forEach(s => {
      const day = s.date || 'Unassigned';
      if (!grouped[day]) grouped[day] = [];
      grouped[day].push(s);
    });
    w.document.write(`<html><head><title>Staff Roster</title><style>
      body{font-family:sans-serif;max-width:700px;margin:20px auto;font-size:13px}
      h1{text-align:center;font-size:20px;margin-bottom:5px}
      h2{font-size:14px;margin:15px 0 5px;padding:5px;background:#f3f4f6;border-radius:4px}
      table{width:100%;border-collapse:collapse;margin-bottom:15px}
      th,td{text-align:left;padding:6px 10px;border-bottom:1px solid #e5e7eb}
      th{background:#f9fafb;font-weight:600;font-size:11px;text-transform:uppercase;color:#6b7280}
      .pos{background:#e0f2fe;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:500}
      @media print{body{margin:0}}
    </style></head><body>
    <h1>NUA — Staff Roster</h1>
    <p style="text-align:center;color:#6b7280;font-size:11px">Printed: ${new Date().toLocaleDateString()}</p>`);

    Object.entries(grouped).sort().forEach(([day, shifts]) => {
      w.document.write(`<h2>${day}</h2><table><thead><tr><th>Staff</th><th>Position</th><th>Start</th><th>End</th></tr></thead><tbody>`);
      shifts.forEach(s => {
        w.document.write(`<tr><td><strong>${s.staffName}</strong></td><td><span class="pos">${s.notes || s.role || '-'}</span></td><td>${s.startTime}</td><td>${s.endTime}</td></tr>`);
      });
      w.document.write('</tbody></table>');
    });

    w.document.write('</body></html>');
    w.document.close();
    w.print();
  };

  const handleCalcPayrun = async () => { try { const r = await staffMgmtAPI.calculatePayrun({ period: payPeriod }); setPayrun(r.data); } catch { toast.error('Failed'); } };
  const handleProcessPayrun = async () => { if (!payrun) return; try { await staffMgmtAPI.processPayrun(payrun); toast.success('Payrun processed'); setPayrun(null); fetchAll(); } catch { toast.error('Failed'); } };

  const budget = getWeeklyBudget();

  return (
    <div className="space-y-6" data-testid="staff-roster-page">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div><h1 className="text-2xl font-bold" style={{ color: theme.text }}>Staff Management</h1><p className="text-sm text-gray-500">Timecards, weekly roster, payrun & reports</p></div>
        <div className="flex items-center gap-3">
          {clockStatus?.clockedIn ? (
            <div className="flex items-center gap-2">
              <Badge className="bg-green-100 text-green-700">Clocked In</Badge>
              <Input type="number" placeholder="Break mins" className="w-24 h-9" value={breakMins} onChange={e => setBreakMins(e.target.value)} data-testid="break-mins" />
              <Button onClick={handleClockOut} className="bg-red-600 hover:bg-red-700 text-white" data-testid="clock-out-btn"><LogOut size={16} className="mr-1" /> Clock Out</Button>
            </div>
          ) : (
            <Button onClick={handleClockIn} style={{ backgroundColor: theme.primary }} data-testid="clock-in-btn"><LogIn size={16} className="mr-1" /> Clock In</Button>
          )}
        </div>
      </div>

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="roster">Roster</TabsTrigger>
          <TabsTrigger value="timecards">Timecards</TabsTrigger>
          <TabsTrigger value="timeoff" data-testid="tab-timeoff">
            Time Off {canManage && timeOff.filter(t => t.status === 'pending').length > 0 && (
              <Badge className="ml-1.5 bg-amber-100 text-amber-700 text-[10px] px-1.5">{timeOff.filter(t => t.status === 'pending').length}</Badge>
            )}
          </TabsTrigger>
          {isOwner && <TabsTrigger value="payrun">Payrun</TabsTrigger>}
          {canManage && <TabsTrigger value="reports">Reports</TabsTrigger>}
        </TabsList>

        {/* ROSTER — Week View */}
        <TabsContent value="roster" className="mt-4 space-y-4">
          {canManage && roster.length > 0 && (
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <Card><CardContent className="p-4 text-center"><p className="text-sm text-gray-500">Total Shifts</p><p className="text-2xl font-bold" style={{ color: theme.primary }}>{roster.length}</p></CardContent></Card>
              <Card><CardContent className="p-4 text-center"><p className="text-sm text-gray-500">Total Hours</p><p className="text-2xl font-bold text-blue-600">{budget.totalHours}h</p></CardContent></Card>
              <Card><CardContent className="p-4 text-center"><p className="text-sm text-gray-500">Weekly Budget</p><p className="text-2xl font-bold text-emerald-600">${budget.totalCost}</p></CardContent></Card>
            </div>
          )}

          <div className="flex flex-wrap justify-between items-center gap-3">
            <h3 className="font-semibold">Weekly Roster</h3>
            <div className="flex flex-wrap gap-2">
              {roster.length > 0 && <Button size="sm" variant="outline" onClick={printRoster} data-testid="print-roster-btn"><Printer size={14} className="mr-1" /> Print Roster</Button>}
              {canManage && <Button size="sm" variant="outline" onClick={async () => {
                if (!window.confirm('Clear ALL shifts on the roster? This cannot be undone.')) return;
                try {
                  const { v26API } = await import('../services/api');
                  const r = await v26API.clearRoster();
                  toast.success(`Cleared ${r.data?.cleared || 0} shifts`);
                  fetchAll();
                } catch { toast.error('Clear failed'); }
              }} data-testid="clear-roster-btn"><Trash2 size={14} className="mr-1" /> Clear All</Button>}
              {canManage && <Button size="sm" variant="outline" onClick={async () => {
                try {
                  const { v26API } = await import('../services/api');
                  const r = await v26API.syncRoster();
                  toast.success(`Removed ${r.data?.orphansRemoved || 0} orphans, ${r.data?.duplicatesRemoved || 0} duplicates`);
                  fetchAll();
                } catch { toast.error('Sync failed'); }
              }} data-testid="sync-roster-btn">Sync Staff</Button>}
              {canManage && <Button size="sm" variant="outline" onClick={async () => {
                const { v15API } = await import('../services/api');
                try {
                  const r = await v15API.autoRoster(weekForm.weekStart || new Date().toISOString().split('T')[0]);
                  setDraftRoster(r.data);
                  setShowDraftPreview(true);
                } catch { toast.error('AI roster failed'); }
              }} data-testid="auto-roster-btn"><Brain size={14} className="mr-1" /> AI Auto-Roster</Button>}
              {isOwner && <Button size="sm" variant="outline" onClick={openRosterSettings} data-testid="roster-settings-btn">
                <Settings2 size={14} className="mr-1" /> Rostering Settings
              </Button>}
              {canManage && <Button size="sm" style={{ backgroundColor: theme.primary }} onClick={() => setShowWeekRoster(true)} data-testid="add-week-roster-btn"><Plus size={14} className="mr-1" /> Add Week Roster</Button>}
            </div>
          </div>

          {/* Week Grid View — Drag and Drop enabled */}
          <DndContext sensors={sensors} onDragStart={handleDragStart} onDragEnd={handleDragEnd}>
            <Card><CardContent className="p-0"><div className="overflow-x-auto">
              <table className="w-full min-w-[700px] text-sm" data-testid="roster-table">
                <thead className="bg-gray-50"><tr>
                  {DAYS.map(d => (
                    <th key={d} className="text-center p-3 font-medium text-gray-500 min-w-[140px]">{d.slice(0, 3)}</th>
                  ))}
                </tr></thead>
                <tbody><tr className="align-top">
                  {DAYS.map(day => {
                    const dayShifts = roster.filter(s => {
                      const d = s.date || '';
                      return d === day || d.includes(day);
                    });
                    const dayCost = dayShifts.reduce((sum, s) => {
                      const sm = staff.find(st => st.id === s.staffId) || {};
                      return sum + calcShiftHours(s) * effectiveHourlyRate(sm.payRate, sm.salaryType);
                    }, 0);
                    return (
                      <DroppableDay key={day} day={day} dayCost={dayCost} theme={theme}>
                        {dayShifts.map(s => (
                          <DraggableShift
                            key={s.id}
                            shift={s}
                            hours={calcShiftHours(s)}
                            canManage={canManage}
                            theme={theme}
                            onDelete={() => handleDeleteShift(s.id)}
                          />
                        ))}
                        {dayShifts.length === 0 && <p className="text-gray-300 text-center text-[10px] py-4">No shifts</p>}
                      </DroppableDay>
                    );
                  })}
                </tr></tbody>
              </table>
            </div></CardContent></Card>
            <DragOverlay>
              {activeDrag ? (
                <div className="p-2 rounded-lg text-xs border bg-white shadow-lg cursor-grabbing" style={{ borderColor: theme.primary }}>
                  <p className="font-semibold">{activeDrag.staffName}</p>
                  <Badge variant="outline" className="text-[9px] mt-0.5">{activeDrag.notes || activeDrag.role || '-'}</Badge>
                  <p className="text-gray-500 mt-0.5">{activeDrag.startTime} - {activeDrag.endTime}</p>
                </div>
              ) : null}
            </DragOverlay>
          </DndContext>
          {canManage && roster.length > 0 && (
            <p className="text-xs text-gray-400 flex items-center gap-1 mt-2"><Move size={12} /> Tip: Drag a shift card to move it to a different day. Daily totals update automatically.</p>
          )}
        </TabsContent>

        {/* TIMECARDS */}
        <TabsContent value="timecards" className="mt-4">
          <Card><CardContent className="p-0"><div className="overflow-x-auto">
            <table className="w-full text-sm" data-testid="timecards-table">
              <thead className="bg-gray-50"><tr>
                <th className="text-left p-3 font-medium text-gray-500">Staff</th>
                <th className="text-left p-3 font-medium text-gray-500">Role</th>
                <th className="text-left p-3 font-medium text-gray-500">Clock In</th>
                <th className="text-left p-3 font-medium text-gray-500">Clock Out</th>
                <th className="text-right p-3 font-medium text-gray-500">Break</th>
                <th className="text-right p-3 font-medium text-gray-500">Hours</th>
                {canManage && <th className="text-right p-3 font-medium text-gray-500">Cost</th>}
                {canManage && <th className="text-right p-3 font-medium text-gray-500">Edit</th>}
              </tr></thead>
              <tbody>
                {timecards.map(tc => (
                  <tr key={tc.id} className="border-t hover:bg-gray-50" data-testid={`timecard-row-${tc.id}`}>
                    <td className="p-3 font-medium">{tc.staffName}</td>
                    <td className="p-3"><Badge variant="outline" className="capitalize text-xs">{tc.role}</Badge></td>
                    <td className="p-3 text-xs">{new Date(tc.clockIn).toLocaleString()}</td>
                    <td className="p-3 text-xs">{tc.clockOut ? new Date(tc.clockOut).toLocaleString() : <Badge className="bg-green-100 text-green-700 text-xs">Active</Badge>}
                      {tc.editedBy && <span className="block text-[10px] text-gray-400 mt-0.5">edited by {tc.editedBy}</span>}
                    </td>
                    <td className="p-3 text-right">{tc.breakMinutes}m</td>
                    <td className="p-3 text-right font-bold">{tc.hoursWorked}h</td>
                    {canManage && <td className="p-3 text-right font-mono" style={{ color: theme.primary }}>${(tc.hoursWorked * effectiveHourlyRate(tc.payRate, tc.salaryType)).toFixed(2)}</td>}
                    {canManage && <td className="p-3 text-right">
                      <button onClick={() => openTimecardEdit(tc)} className="text-gray-400 hover:text-gray-700" data-testid={`edit-timecard-${tc.id}`}><Pencil size={14} /></button>
                    </td>}
                  </tr>
                ))}
              </tbody>
            </table>
            {timecards.length === 0 && <p className="text-center text-gray-400 py-8">No timecards yet. Clock in to start.</p>}
          </div></CardContent></Card>
        </TabsContent>

        {/* TIME OFF / LEAVE REQUESTS */}
        <TabsContent value="timeoff" className="mt-4 space-y-3">
          <div className="flex flex-wrap justify-between items-center gap-3">
            <h3 className="font-semibold">{canManage ? 'Time Off Requests' : 'My Time Off'}</h3>
            <Button size="sm" style={{ backgroundColor: theme.primary }} onClick={() => setShowTimeOffDialog(true)} data-testid="request-time-off-btn">
              <CalendarOff size={14} className="mr-1" /> Request Time Off
            </Button>
          </div>
          <div className="space-y-2">
            {timeOff.map(t => (
              <Card key={t.id} data-testid={`timeoff-row-${t.id}`}>
                <CardContent className="p-4 flex items-center justify-between gap-3">
                  <div>
                    {canManage && <p className="font-semibold text-sm">{t.userName}</p>}
                    <p className="text-sm text-gray-700">{t.startDate} → {t.endDate}</p>
                    <p className="text-xs text-gray-500">{t.reason}</p>
                    {t.notes && <p className="text-xs text-red-500 mt-0.5">Note: {t.notes}</p>}
                  </div>
                  <div className="flex items-center gap-2">
                    <Badge className={
                      t.status === 'approved' ? 'bg-green-100 text-green-700' :
                      t.status === 'denied' ? 'bg-red-100 text-red-700' : 'bg-amber-100 text-amber-700'
                    }>{t.status}</Badge>
                    {canManage && t.status === 'pending' && (
                      <>
                        <Button size="sm" variant="outline" className="h-8 text-emerald-700 border-emerald-300" onClick={() => handleApproveTimeOff(t.id)} data-testid={`approve-timeoff-${t.id}`}><Check size={14} /></Button>
                        <Button size="sm" variant="outline" className="h-8 text-red-600 border-red-300" onClick={() => handleRejectTimeOff(t.id)} data-testid={`reject-timeoff-${t.id}`}><X size={14} /></Button>
                      </>
                    )}
                    {t.status === 'pending' && (!canManage || t.userId === user?.id) && (
                      <button onClick={() => handleCancelTimeOff(t.id)} className="text-gray-400 hover:text-red-600" data-testid={`cancel-timeoff-${t.id}`}><Trash2 size={14} /></button>
                    )}
                  </div>
                </CardContent>
              </Card>
            ))}
            {timeOff.length === 0 && (
              <Card className="border-dashed"><CardContent className="p-8 text-center text-gray-400">
                No time off requests {canManage ? 'from any staff' : 'yet'}.
              </CardContent></Card>
            )}
          </div>
        </TabsContent>

        {/* PAYRUN */}
        {isOwner && (
          <TabsContent value="payrun" className="mt-4">
            <p className="text-xs text-gray-500 mb-3">
              Quick estimate only (flat tax/super approximation) — for STP-ready,
              ATO-compliant pay runs with leave accrual, use the{' '}
              <a href="/payroll" className="underline font-medium" style={{ color: theme.primary }}>full Payroll page</a>.
              These are two separate systems; a run committed on either page won't show up on the other's history.
            </p>
            <div className="flex items-center gap-3 mb-4">
              <select className="p-2 border rounded-md text-sm" value={payPeriod} onChange={e => setPayPeriod(e.target.value)} data-testid="payrun-period">
                <option value="week">This Week</option><option value="fortnight">Fortnight</option><option value="month">This Month</option><option value="quarter">This Quarter</option><option value="year">This Year</option>
              </select>
              <Button style={{ backgroundColor: theme.primary }} onClick={handleCalcPayrun} data-testid="calc-payrun-btn"><DollarSign size={16} className="mr-1" /> Calculate Payrun</Button>
            </div>
            {payrun && (
              <div className="space-y-4">
                <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                  <Card><CardContent className="p-4 text-center"><p className="text-sm text-gray-500">Gross Pay</p><p className="text-2xl font-bold" style={{ color: theme.primary }}>${payrun.totals.grossPay}</p></CardContent></Card>
                  <Card><CardContent className="p-4 text-center"><p className="text-sm text-gray-500">Super (11.5%)</p><p className="text-2xl font-bold text-blue-600">${payrun.totals.super}</p></CardContent></Card>
                  <Card><CardContent className="p-4 text-center"><p className="text-sm text-gray-500">Tax</p><p className="text-2xl font-bold text-amber-600">${payrun.totals.tax}</p></CardContent></Card>
                  <Card><CardContent className="p-4 text-center"><p className="text-sm text-gray-500">Net Pay</p><p className="text-2xl font-bold text-emerald-600">${payrun.totals.netPay}</p></CardContent></Card>
                </div>
                <Card><CardContent className="p-0 overflow-x-auto"><table className="w-full text-sm"><thead className="bg-gray-50"><tr><th className="text-left p-3">Staff</th><th className="text-left p-3">Role</th><th className="text-right p-3">Rate</th><th className="text-right p-3">Hours</th><th className="text-right p-3">Gross</th><th className="text-right p-3">Super</th><th className="text-right p-3">Tax</th><th className="text-right p-3">Net</th></tr></thead><tbody>
                  {payrun.staffPayroll.map(s => (<tr key={s.staffId} className="border-t"><td className="p-3 font-medium">{s.name}</td><td className="p-3"><Badge variant="outline" className="capitalize text-xs">{s.role}</Badge></td><td className="p-3 text-right">${s.payRate}/hr</td><td className="p-3 text-right">{s.totalHours}h</td><td className="p-3 text-right font-bold">${s.grossPay}</td><td className="p-3 text-right">${s.super}</td><td className="p-3 text-right">${s.tax}</td><td className="p-3 text-right font-bold text-emerald-600">${s.netPay}</td></tr>))}
                </tbody></table></CardContent></Card>
                <Button className="bg-emerald-600 hover:bg-emerald-700 text-white" onClick={handleProcessPayrun} data-testid="process-payrun-btn"><FileText size={16} className="mr-1" /> Process Payrun</Button>
              </div>
            )}
            {payHistory.length > 0 && (<div className="mt-6"><h3 className="font-semibold mb-3">Payrun History</h3><div className="space-y-2">{payHistory.map(p => (<Card key={p.id}><CardContent className="p-4 flex items-center justify-between"><div><span className="font-mono text-sm">{p.id}</span><span className="text-gray-500 text-sm ml-3">{p.period}</span></div><div className="text-right"><p className="font-bold" style={{ color: theme.primary }}>${p.totals?.grossPay || 0}</p><p className="text-xs text-gray-500">{new Date(p.processedAt).toLocaleDateString()}</p></div></CardContent></Card>))}</div></div>)}
          </TabsContent>
        )}

        {/* REPORTS */}
        {canManage && (
          <TabsContent value="reports" className="mt-4">
            <div className="flex items-center gap-3 mb-4">
              {['week', 'month', 'quarter', 'year'].map(p => (
                <Button key={p} size="sm" variant={reportPeriod === p ? 'default' : 'outline'} style={reportPeriod === p ? { backgroundColor: theme.primary } : {}} onClick={() => setReportPeriod(p)} data-testid={`report-period-${p}`}>{p.charAt(0).toUpperCase() + p.slice(1)}</Button>
              ))}
            </div>
            {staffReports && (
              <div className="space-y-4">
                <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                  <Card><CardContent className="p-4 text-center"><p className="text-sm text-gray-500">Total Staff</p><p className="text-2xl font-bold">{staffReports.summary.totalStaff}</p></CardContent></Card>
                  <Card><CardContent className="p-4 text-center"><p className="text-sm text-gray-500">Total Hours</p><p className="text-2xl font-bold" style={{ color: theme.primary }}>{staffReports.summary.totalHours}h</p></CardContent></Card>
                  <Card><CardContent className="p-4 text-center"><p className="text-sm text-gray-500">Total Wages</p><p className="text-2xl font-bold text-emerald-600">${staffReports.summary.totalWages}</p></CardContent></Card>
                  <Card><CardContent className="p-4 text-center"><p className="text-sm text-gray-500">Payruns</p><p className="text-2xl font-bold text-blue-600">{staffReports.summary.totalPayruns}</p></CardContent></Card>
                </div>
                <Card><CardContent className="p-0 overflow-x-auto"><table className="w-full text-sm" data-testid="staff-reports-table"><thead className="bg-gray-50"><tr><th className="text-left p-3">Staff</th><th className="text-left p-3">Role</th><th className="text-right p-3">Rate</th><th className="text-right p-3">Shifts</th><th className="text-right p-3">Hours</th><th className="text-right p-3">Avg/Shift</th><th className="text-right p-3">Total Wages</th><th className="text-center p-3">Status</th></tr></thead><tbody>
                  {staffReports.staffStats.map(s => (<tr key={s.id} className="border-t"><td className="p-3 font-medium">{s.name}</td><td className="p-3"><Badge variant="outline" className="capitalize text-xs">{s.role}</Badge></td><td className="p-3 text-right">${s.payRate}/hr</td><td className="p-3 text-right">{s.totalShifts}</td><td className="p-3 text-right">{s.totalHours}h</td><td className="p-3 text-right">{s.avgHoursPerShift}h</td><td className="p-3 text-right font-bold" style={{ color: theme.primary }}>${s.totalWages}</td><td className="p-3 text-center">{s.currentlyClockedIn ? <Badge className="bg-green-100 text-green-700 text-xs">Active</Badge> : <Badge variant="outline" className="text-xs">Off</Badge>}</td></tr>))}
                </tbody></table></CardContent></Card>
              </div>
            )}
          </TabsContent>
        )}
      </Tabs>

      {/* Add Week Roster Dialog */}
      <Dialog open={showWeekRoster} onOpenChange={setShowWeekRoster}>
        <DialogContent className="max-w-lg" data-testid="week-roster-dialog">
          <DialogHeader><DialogTitle>Add Week Roster</DialogTitle></DialogHeader>
          <div className="space-y-4 py-2 max-h-[70vh] overflow-y-auto">
            <select className="w-full p-2 border rounded-md text-sm" value={weekForm.staffId} onChange={e => setWeekForm({ ...weekForm, staffId: e.target.value })} data-testid="week-staff-select">
              <option value="">Select staff member...</option>
              {staff.map(s => <option key={s.id} value={s.id}>{s.name} ({s.role})</option>)}
            </select>
            <select className="w-full p-2 border rounded-md text-sm" value={weekForm.position} onChange={e => setWeekForm({ ...weekForm, position: e.target.value })} data-testid="week-position-select">
              {POSITIONS.map(p => <option key={p} value={p}>{p}</option>)}
            </select>
            <div><label className="text-xs font-medium text-gray-500 mb-1 block">Week Starting (for reference)</label>
              <Input type="date" value={weekForm.weekStart} onChange={e => setWeekForm({ ...weekForm, weekStart: e.target.value })} data-testid="week-start-date" />
            </div>

            <div className="space-y-2">
              <p className="text-sm font-medium text-gray-700">Select days and times:</p>
              {DAYS.map(day => {
                const shift = weekForm.shifts[day] || { enabled: false, startTime: '09:00', endTime: '17:00' };
                return (
                  <div key={day} className="flex items-center gap-3 p-2 rounded-lg border" data-testid={`week-day-${day.toLowerCase()}`}>
                    <label className="flex items-center gap-2 w-28 cursor-pointer">
                      <input type="checkbox" checked={shift.enabled} onChange={e => setWeekForm({ ...weekForm, shifts: { ...weekForm.shifts, [day]: { ...shift, enabled: e.target.checked } } })} />
                      <span className="text-sm font-medium">{day.slice(0, 3)}</span>
                    </label>
                    {shift.enabled && (
                      <div className="flex items-center gap-2 flex-1">
                        <Input type="time" className="h-8 text-sm flex-1" value={shift.startTime} onChange={e => setWeekForm({ ...weekForm, shifts: { ...weekForm.shifts, [day]: { ...shift, startTime: e.target.value } } })} />
                        <span className="text-gray-400 text-xs">to</span>
                        <Input type="time" className="h-8 text-sm flex-1" value={shift.endTime} onChange={e => setWeekForm({ ...weekForm, shifts: { ...weekForm.shifts, [day]: { ...shift, endTime: e.target.value } } })} />
                      </div>
                    )}
                  </div>
                );
              })}
            </div>

            {/* Preview cost */}
            {weekForm.staffId && (() => {
              const staffMember = staff.find(s => s.id === weekForm.staffId);
              const rate = staffMember?.payRate || 0;
              const hourlyRate = effectiveHourlyRate(staffMember?.payRate, staffMember?.salaryType);
              const totalHrs = Object.values(weekForm.shifts).filter(s => s.enabled).reduce((sum, s) => {
                const st = s.startTime?.split(':').map(Number) || [0, 0];
                const en = s.endTime?.split(':').map(Number) || [0, 0];
                return sum + Math.max((en[0] + en[1] / 60) - (st[0] + st[1] / 60), 0);
              }, 0);
              return totalHrs > 0 ? (
                <div className="p-3 bg-gray-50 rounded-lg text-sm">
                  <div className="flex justify-between"><span>Total Hours:</span><span className="font-bold">{totalHrs.toFixed(1)}h</span></div>
                  <div className="flex justify-between"><span>Rate:</span><span>${rate}{salaryTypeSuffix(staffMember?.salaryType)}</span></div>
                  <div className="flex justify-between text-emerald-700 font-bold"><span>Estimated Cost:</span><span>${(totalHrs * hourlyRate).toFixed(2)}</span></div>
                </div>
              ) : null;
            })()}

            <Button className="w-full" style={{ backgroundColor: theme.primary }} onClick={handleAddWeekRoster} data-testid="save-week-roster-btn">Add Week Roster</Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Request Time Off Dialog */}
      <Dialog open={showTimeOffDialog} onOpenChange={setShowTimeOffDialog}>
        <DialogContent className="max-w-sm" data-testid="time-off-dialog">
          <DialogHeader><DialogTitle>Request Time Off</DialogTitle></DialogHeader>
          <div className="space-y-3 py-2">
            <div className="grid grid-cols-2 gap-2">
              <div><label className="text-xs font-medium text-gray-500 mb-1 block">Start date</label>
                <Input type="date" value={timeOffForm.startDate} onChange={e => setTimeOffForm({ ...timeOffForm, startDate: e.target.value })} data-testid="timeoff-start" />
              </div>
              <div><label className="text-xs font-medium text-gray-500 mb-1 block">End date</label>
                <Input type="date" value={timeOffForm.endDate} onChange={e => setTimeOffForm({ ...timeOffForm, endDate: e.target.value })} data-testid="timeoff-end" />
              </div>
            </div>
            <textarea className="w-full min-h-[80px] p-2 border rounded-md text-sm resize-none" placeholder="Reason (e.g. family trip, appointment)"
              value={timeOffForm.reason} onChange={e => setTimeOffForm({ ...timeOffForm, reason: e.target.value })} data-testid="timeoff-reason" />
            <Button className="w-full" style={{ backgroundColor: theme.primary }} onClick={handleRequestTimeOff} data-testid="submit-timeoff-btn">Submit Request</Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Edit Timecard Dialog (owner/manager fix-up) */}
      <Dialog open={!!editingTimecard} onOpenChange={(o) => !o && setEditingTimecard(null)}>
        <DialogContent className="max-w-sm" data-testid="edit-timecard-dialog">
          <DialogHeader><DialogTitle>Edit Timecard — {editingTimecard?.staffName}</DialogTitle></DialogHeader>
          <div className="space-y-3 py-2">
            <p className="text-xs text-gray-500">Clocked in: {editingTimecard ? new Date(editingTimecard.clockIn).toLocaleString() : ''}</p>
            <div><label className="text-xs font-medium text-gray-500 mb-1 block">Clock out</label>
              <Input type="datetime-local" value={timecardEditForm.clockOut} onChange={e => setTimecardEditForm({ ...timecardEditForm, clockOut: e.target.value })} data-testid="edit-timecard-clockout" />
            </div>
            <div><label className="text-xs font-medium text-gray-500 mb-1 block">Break (minutes)</label>
              <Input type="number" value={timecardEditForm.breakMinutes} onChange={e => setTimecardEditForm({ ...timecardEditForm, breakMinutes: e.target.value })} data-testid="edit-timecard-break" />
            </div>
            <Button className="w-full" style={{ backgroundColor: theme.primary }} onClick={handleSaveTimecardEdit} data-testid="save-timecard-edit-btn">Save</Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Smart Rostering settings — owner-only full control */}
      <Dialog open={showRosterSettings} onOpenChange={setShowRosterSettings}>
        <DialogContent className="max-w-lg" data-testid="roster-settings-dialog">
          <DialogHeader><DialogTitle>Smart Rostering Settings</DialogTitle></DialogHeader>
          {rosterSettings && (
            <div className="space-y-3 py-2 text-sm">
              <p className="text-xs text-gray-500">
                Controls what AI Auto-Roster generates — shift lengths, staffing floors, and the
                cost/revenue balance it targets.
              </p>
              <div>
                <label className="text-xs font-medium text-gray-500 mb-1 block">
                  Minimum engagement (hours) — industry minimum a called-in casual must be paid for
                </label>
                <Input type="number" step="0.5" value={rosterSettings.minEngagementHours}
                  onChange={e => setRosterSettings({ ...rosterSettings, minEngagementHours: parseFloat(e.target.value) || 0 })}
                  data-testid="settings-min-engagement" />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div><label className="text-xs font-medium text-gray-500 mb-1 block">Weekday staff floor</label>
                  <Input type="number" value={rosterSettings.weekdayStaffTarget}
                    onChange={e => setRosterSettings({ ...rosterSettings, weekdayStaffTarget: parseInt(e.target.value) || 0 })}
                    data-testid="settings-weekday-target" /></div>
                <div><label className="text-xs font-medium text-gray-500 mb-1 block">Weekend staff floor</label>
                  <Input type="number" value={rosterSettings.weekendStaffTarget}
                    onChange={e => setRosterSettings({ ...rosterSettings, weekendStaffTarget: parseInt(e.target.value) || 0 })}
                    data-testid="settings-weekend-target" /></div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div><label className="text-xs font-medium text-gray-500 mb-1 block">Weekday shift</label>
                  <div className="flex gap-1">
                    <Input value={rosterSettings.weekdayShift.start} onChange={e => setRosterSettings({ ...rosterSettings, weekdayShift: { ...rosterSettings.weekdayShift, start: e.target.value } })} data-testid="settings-weekday-start" />
                    <Input value={rosterSettings.weekdayShift.end} onChange={e => setRosterSettings({ ...rosterSettings, weekdayShift: { ...rosterSettings.weekdayShift, end: e.target.value } })} data-testid="settings-weekday-end" />
                  </div></div>
                <div><label className="text-xs font-medium text-gray-500 mb-1 block">Weekend shift</label>
                  <div className="flex gap-1">
                    <Input value={rosterSettings.weekendShift.start} onChange={e => setRosterSettings({ ...rosterSettings, weekendShift: { ...rosterSettings.weekendShift, start: e.target.value } })} data-testid="settings-weekend-start" />
                    <Input value={rosterSettings.weekendShift.end} onChange={e => setRosterSettings({ ...rosterSettings, weekendShift: { ...rosterSettings.weekendShift, end: e.target.value } })} data-testid="settings-weekend-end" />
                  </div></div>
              </div>
              <div className="grid grid-cols-3 gap-3">
                <div><label className="text-xs font-medium text-gray-500 mb-1 block">Covers per staff</label>
                  <Input type="number" value={rosterSettings.coversPerStaff}
                    onChange={e => setRosterSettings({ ...rosterSettings, coversPerStaff: parseInt(e.target.value) || 1 })}
                    data-testid="settings-covers-per-staff" /></div>
                <div><label className="text-xs font-medium text-gray-500 mb-1 block">Target labor %</label>
                  <Input type="number" value={rosterSettings.targetLaborPct}
                    onChange={e => setRosterSettings({ ...rosterSettings, targetLaborPct: parseFloat(e.target.value) || 0 })}
                    data-testid="settings-target-labor-pct" /></div>
                <div><label className="text-xs font-medium text-gray-500 mb-1 block">Avg hourly rate $</label>
                  <Input type="number" value={rosterSettings.avgHourlyRate}
                    onChange={e => setRosterSettings({ ...rosterSettings, avgHourlyRate: parseFloat(e.target.value) || 0 })}
                    data-testid="settings-avg-rate" /></div>
              </div>
              <Button className="w-full" style={{ backgroundColor: theme.primary }} onClick={saveRosterSettings} data-testid="save-roster-settings-btn">
                Save Settings
              </Button>
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* AI Auto-Roster draft — nothing here touches the real roster until Commit is clicked */}
      <Dialog open={showDraftPreview} onOpenChange={(o) => { setShowDraftPreview(o); if (!o) setDraftRoster(null); }}>
        <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto" data-testid="draft-roster-dialog">
          <DialogHeader><DialogTitle className="flex items-center gap-2"><Brain size={18} /> Draft Roster</DialogTitle></DialogHeader>
          {draftRoster && (
            <div className="space-y-4 py-2 text-sm">
              <p className="text-xs text-gray-500">{draftRoster.reasoning}</p>

              <div className="grid grid-cols-3 gap-3">
                <div className="rounded-lg border p-3 text-center">
                  <p className="text-lg font-bold" style={{ color: theme.primary }}>{draftRoster.suggestions?.length || 0}</p>
                  <p className="text-[10px] text-gray-500">Shifts proposed</p>
                </div>
                <div className="rounded-lg border p-3 text-center">
                  <p className="text-lg font-bold">${(draftRoster.weekEstimate?.estLaborCost || 0).toLocaleString()}</p>
                  <p className="text-[10px] text-gray-500">Est. labor cost</p>
                </div>
                <div className="rounded-lg border p-3 text-center">
                  <p className="text-lg font-bold">{draftRoster.weekEstimate?.laborPct ?? '–'}%</p>
                  <p className="text-[10px] text-gray-500">Of forecast revenue</p>
                </div>
              </div>

              <div className="space-y-3" data-testid="draft-roster-days">
                {(draftRoster.daySummaries || []).map(day => {
                  const dayShifts = (draftRoster.suggestions || []).filter(s => s.date === day.date);
                  return (
                    <div key={day.date} className="rounded-lg border p-3">
                      <div className="flex items-center justify-between mb-2">
                        <p className="font-semibold">{day.date}</p>
                        <span className="text-xs text-gray-500">
                          {day.staffed} staffed · {day.forecastCovers} covers forecast{day.trimmedForCost ? ' · trimmed for cost' : ''}
                        </span>
                      </div>
                      <div className="space-y-1">
                        {dayShifts.map((s, i) => (
                          <div key={i} className="flex items-center justify-between text-xs py-1 border-t first:border-t-0">
                            <span className="font-medium">{s.staffName}</span>
                            <span className="text-gray-500">{s.role} · {s.startTime}-{s.endTime}</span>
                            <Badge variant="outline" className="text-[9px]" title="Performance score — sales, tips & punctuality">
                              ★ {Math.round(s.performanceScore || 0)}
                            </Badge>
                          </div>
                        ))}
                        {dayShifts.length === 0 && <p className="text-xs text-gray-400">No shifts</p>}
                      </div>
                    </div>
                  );
                })}
              </div>

              {(draftRoster.excluded || []).length > 0 && (
                <div className="rounded-lg border p-3" style={{ backgroundColor: `${theme.primary}0d` }} data-testid="draft-roster-excluded">
                  <p className="text-xs font-semibold mb-1" style={{ color: theme.primary }}>
                    {draftRoster.excluded.length} staff skipped (unavailable)
                  </p>
                  <div className="space-y-0.5">
                    {draftRoster.excluded.map((e, i) => (
                      <p key={i} className="text-[11px] text-gray-600">{e.staffName} — {e.date} ({(e.reason || '').replace('_', ' ')})</p>
                    ))}
                  </div>
                </div>
              )}

              <div className="flex gap-2 pt-2">
                <Button variant="outline" className="flex-1" onClick={() => { setShowDraftPreview(false); setDraftRoster(null); }} data-testid="discard-draft-btn">
                  Discard
                </Button>
                <Button className="flex-1" style={{ backgroundColor: theme.primary }} onClick={handleCommitDraft} disabled={committingDraft} data-testid="commit-draft-btn">
                  {committingDraft ? 'Committing...' : `Commit ${draftRoster.suggestions?.length || 0} Shifts`}
                </Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
