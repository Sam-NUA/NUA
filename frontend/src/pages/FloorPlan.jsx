import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  Plus, Save, Trash2, RotateCcw, Maximize2, Circle, Square, RectangleHorizontal,
  Users, ChevronDown, Eye, Settings, Pencil, Crown, BrushCleaning, Layers
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
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger
} from '../components/ui/dropdown-menu';
import { useTheme } from '../contexts/ThemeContext';
import { floorPlansAPI, tableCoursesAPI, v15API, reservationFeaturesAPI } from '../services/api';
import { toast } from 'sonner';
import { TableInfoDrawer } from '../components/floor/TableInfoDrawer';
import useLiveFeed from '../hooks/useLiveFeed';

// Table colour scheme: OPEN/SEATED/RESERVED are base statuses; VIP and
// OVERDUE are accents layered on top (a ring + badge, not a fill swap) so a
// seated table's course colour stays visible underneath. "Cleaning" is a
// real status internally (still cycled via shift-click, still saved) but
// renders visually the same as Open, with a small brush badge — there's no
// separate "needs cleaning" swatch in the legend.
// Colours per NUA_POS_DESIGN_TOKENS.md §6 (Floor plan / tables) — kept in
// sync with what nuapos.com.au depicts.
const TABLE_STATUS_COLORS = {
  available: { fill: '#FFFFFF', stroke: '#D9CFC5', label: 'Open' },
  occupied: { fill: '#1c1917', stroke: '#1c1917', label: 'Seated' },
  reserved: { fill: '#7c3aed', stroke: '#6d28d9', label: 'Reserved' },
  cleaning: { fill: '#FFFFFF', stroke: '#D9CFC5', label: 'Open' },
};
const VIP_COLOR = '#db2777';
const DEFAULT_OVERDUE_COLOR = '#f58c14';

const SECTIONS_COLORS = ['#3B82F6', '#10B981', '#F59E0B', '#EF4444', '#8B5CF6', '#EC4899', '#06B6D4'];

export default function FloorPlan() {
  const { theme, darkMode } = useTheme();
  const canvasRef = useRef(null);
  const [plans, setPlans] = useState([]);
  const [activePlanId, setActivePlanId] = useState(null);
  const [tables, setTables] = useState([]);
  const [sections, setSections] = useState([]);
  const [mode, setMode] = useState('view'); // view | edit
  const [selectedTable, setSelectedTable] = useState(null);
  const [dragging, setDragging] = useState(null);
  const [dragOffset, setDragOffset] = useState({ x: 0, y: 0 });
  const [planName, setPlanName] = useState('Main Floor');
  const [tableDialog, setTableDialog] = useState(false);
  const [newPlanDialog, setNewPlanDialog] = useState(false);
  const [newPlanName, setNewPlanName] = useState('');
  const [tableForm, setTableForm] = useState({ number: '', capacity: 4, shape: 'rectangle', section: 'main', minCovers: 1, maxCovers: 4 });

  // Course-aware live states (from /table-courses/states)
  const [courseStates, setCourseStates] = useState([]);
  const [courseDefs, setCourseDefs] = useState([]);
  const [overdueColour, setOverdueColour] = useState(DEFAULT_OVERDUE_COLOR);
  const [drawerTable, setDrawerTable] = useState(null);
  const [courseSettingsOpen, setCourseSettingsOpen] = useState(false);
  const [courseDraft, setCourseDraft] = useState([]);

  // Merge tables: multi-select occupied tables on the floor plan and combine
  // their open checks into one, so a large or growing party doesn't need
  // staff to juggle separate tabs or leave the floor to rearrange seating.
  const [mergeMode, setMergeMode] = useState(false);
  const [mergeSelection, setMergeSelection] = useState([]);

  // Table Combinations: which physical tables can be pushed together to seat
  // a party larger than any single table's capacity — a static grouping used
  // when assigning big bookings, not to be confused with Merge Tables above
  // (which combines two already-open POS checks into one, a live/financial
  // operation). Previously its own separate "Table Layout" nav page; folded
  // in here so staff have one destination for everything table-related
  // instead of two similarly-named, easy-to-confuse screens. Reuses the
  // existing table_combinations data model and reservationFeaturesAPI
  // unchanged — only the UI moved.
  const [combosOpen, setCombosOpen] = useState(false);
  const [combos, setCombos] = useState([]);
  const [comboSelection, setComboSelection] = useState([]);
  const [comboName, setComboName] = useState('');
  const [comboMaxCovers, setComboMaxCovers] = useState('');

  const fetchCombos = useCallback(async () => {
    try {
      const r = await reservationFeaturesAPI.getTableCombos();
      setCombos(r.data || []);
    } catch { /* non-fatal */ }
  }, []);

  const toggleComboSelect = (tableKey) => {
    setComboSelection(sel => sel.includes(tableKey) ? sel.filter(id => id !== tableKey) : [...sel, tableKey]);
  };

  const createCombo = async () => {
    if (comboSelection.length < 2) { toast.error('Select at least 2 tables'); return; }
    try {
      await reservationFeaturesAPI.createTableCombo({
        tableIds: comboSelection,
        name: comboName || `Combo ${comboSelection.join('+')}`,
        maxCovers: parseInt(comboMaxCovers) || comboSelection.length * 4,
      });
      toast.success('Combination created');
      setComboSelection([]); setComboName(''); setComboMaxCovers('');
      fetchCombos();
    } catch { toast.error('Failed to create combination'); }
  };

  const deleteCombo = async (id) => {
    try {
      await reservationFeaturesAPI.deleteTableCombo(id);
      setCombos(combos.filter(c => c.id !== id));
      toast.success('Combination deleted');
    } catch { toast.error('Failed to delete'); }
  };

  const fetchCourses = useCallback(async () => {
    try {
      const r = await tableCoursesAPI.listStates();
      setCourseStates(r.data.states || []);
      setCourseDefs(r.data.courses || []);
      setOverdueColour(r.data.overdueColour || DEFAULT_OVERDUE_COLOR);
    } catch { /* non-fatal */ }
  }, []);

  useEffect(() => {
    fetchCourses();
    const id = setInterval(fetchCourses, 30_000);
    return () => clearInterval(id);
  }, [fetchCourses]);

  const fetchPlans = useCallback(async () => {
    try {
      const res = await floorPlansAPI.getAll();
      setPlans(res.data);
      if (res.data.length > 0 && !activePlanId) {
        const first = res.data[0];
        setActivePlanId(first.id);
        setTables(first.tables || []);
        setSections(first.sections || []);
        setPlanName(first.name);
      }
    } catch (e) { console.error(e); toast.error('Could not load the floor plan'); }
  }, [activePlanId]);

  useEffect(() => {
    fetchPlans();
    const timer = setInterval(fetchPlans, 30000);
    return () => clearInterval(timer);
  }, [fetchPlans]);
  // Any staff device that moves/seats/clears a table pushes here — this
  // shared feed refreshes promptly, with a 30s reconciliation poll above.
  useLiveFeed(useCallback((event) => {
    if (event.type === 'sync.required' || event.type === 'floor_plan.updated') fetchPlans();
  }, [fetchPlans]));

  const switchPlan = (planId) => {
    const plan = plans.find(p => p.id === planId);
    if (plan) {
      setActivePlanId(plan.id);
      setTables(plan.tables || []);
      setSections(plan.sections || []);
      setPlanName(plan.name);
      setSelectedTable(null);
    }
  };

  const savePlan = async () => {
    if (!activePlanId) return;
    try {
      await floorPlansAPI.update(activePlanId, { name: planName, tables, sections });
      toast.success('Floor plan saved');
      fetchPlans();
    } catch (e) { toast.error('Failed to save'); }
  };

  const createPlan = async () => {
    try {
      const name = newPlanName || 'New Floor';
      const res = await floorPlansAPI.create({ name, tables: [], sections: [{ id: `SEC-${Date.now()}`, name: 'Main', color: '#3B82F6' }] });
      setNewPlanDialog(false);
      setNewPlanName('');
      setActivePlanId(res.data.id);
      setTables([]);
      setSections(res.data.sections || []);
      setPlanName(res.data.name);
      toast.success('Floor plan created');
      fetchPlans();
    } catch (e) { toast.error('Failed to create plan'); }
  };

  const addTable = () => {
    const num = tables.length + 1;
    const newTable = {
      id: `TBL-${Date.now()}-${num}`,
      number: String(num),
      capacity: 4, shape: 'rectangle',
      x: 100 + (num % 5) * 120, y: 100 + Math.floor(num / 5) * 100,
      width: 80, height: 60, rotation: 0,
      section: sections[0]?.name || 'main',
      status: 'available', isActive: true,
      minCovers: 1, maxCovers: 4,
    };
    setTables([...tables, newTable]);
    setSelectedTable(newTable.id);
  };

  const deleteTable = (id) => {
    setTables(tables.filter(t => t.id !== id));
    if (selectedTable === id) setSelectedTable(null);
  };

  const updateTable = (id, updates) => {
    setTables(tables.map(t => t.id === id ? { ...t, ...updates } : t));
  };

  const openTableEditor = (t) => {
    setTableForm({ number: t.number, capacity: t.capacity || t.maxCovers, shape: t.shape, section: t.section, minCovers: t.minCovers || 1, maxCovers: t.maxCovers || t.capacity || 4 });
    setSelectedTable(t.id);
    setTableDialog(true);
  };

  const saveTableEdit = () => {
    if (selectedTable) {
      updateTable(selectedTable, {
        number: tableForm.number, capacity: parseInt(tableForm.capacity),
        shape: tableForm.shape, section: tableForm.section,
        minCovers: parseInt(tableForm.minCovers), maxCovers: parseInt(tableForm.maxCovers),
      });
    }
    setTableDialog(false);
  };

  // Mouse handlers for drag
  const handleMouseDown = (e, tableId) => {
    if (mode !== 'edit') return;
    const t = tables.find(tb => tb.id === tableId);
    if (!t) return;
    const rect = canvasRef.current.getBoundingClientRect();
    setDragging(tableId);
    setDragOffset({ x: e.clientX - rect.left - t.x, y: e.clientY - rect.top - t.y });
    setSelectedTable(tableId);
  };

  const handleMouseMove = (e) => {
    if (!dragging || mode !== 'edit') return;
    const rect = canvasRef.current.getBoundingClientRect();
    const x = Math.max(0, Math.min(e.clientX - rect.left - dragOffset.x, 920));
    const y = Math.max(0, Math.min(e.clientY - rect.top - dragOffset.y, 520));
    updateTable(dragging, { x, y });
  };

  const handleMouseUp = () => { setDragging(null); };

  const toggleMergeSelect = (tableId) => {
    setMergeSelection(sel => sel.includes(tableId) ? sel.filter(id => id !== tableId) : [...sel, tableId]);
  };

  const handleMergeTables = async () => {
    try {
      const res = await v15API.getTabs();
      const openTabs = res.data || [];
      const selectedTables = tables.filter(t => mergeSelection.includes(t.id));
      const matched = selectedTables
        .map(t => ({ table: t, tab: openTabs.find(tb => String(tb.tableNumber) === String(t.number)) }))
        .filter(m => m.tab);
      if (matched.length < 2) {
        toast.error('Selected tables need an open order each to merge');
        return;
      }
      const [primary, ...rest] = matched;
      for (const m of rest) {
        await v15API.mergeTabs(primary.tab.id, m.tab.id);
      }
      // The absorbed tables' checks now live on the primary table — free them
      // up on the floor plan so staff can seat the next party there.
      const freedIds = new Set(rest.map(m => m.table.id));
      const updatedTables = tables.map(t => freedIds.has(t.id) ? { ...t, status: 'available' } : t);
      setTables(updatedTables);
      if (activePlanId) await floorPlansAPI.update(activePlanId, { tables: updatedTables });
      toast.success(`Merged ${matched.length} tables into Table ${primary.table.number}`);
    } catch {
      toast.error('Merge failed');
    } finally {
      setMergeMode(false);
      setMergeSelection([]);
    }
  };

  const handleTableStatusClick = (tableId, evt) => {
    if (mode !== 'view') return;
    if (mergeMode) { toggleMergeSelect(tableId); return; }
    const t = tables.find(tb => tb.id === tableId);
    if (!t) return;
    // Shift-click = cycle status directly (legacy shortcut). Regular click
    // now opens the drawer so staff can see live state + Send.
    if (evt && evt.shiftKey) {
      const order = ['available', 'reserved', 'occupied', 'cleaning'];
      const idx = order.indexOf(t.status);
      const next = order[(idx + 1) % order.length];
      updateTable(tableId, { status: next });
      if (activePlanId) {
        const updated = tables.map(tb => tb.id === tableId ? { ...tb, status: next } : tb);
        floorPlansAPI.update(activePlanId, { tables: updated }).catch(() => {});
      }
      return;
    }
    setDrawerTable(t);
    setSelectedTable(tableId);
  };

  // Stats — VIP/Overdue are accents (from live course state), not a `status`
  // value, so they're counted separately rather than folded into statusCounts.
  const statusCounts = { available: 0, occupied: 0, reserved: 0, cleaning: 0 };
  tables.forEach(t => { if (statusCounts[t.status] !== undefined) statusCounts[t.status]++; });
  const vipCount = tables.filter(t => courseStates.find(cs => cs.tableId === t.id)?.isVip).length;
  const overdueCount = tables.filter(t => courseStates.find(cs => cs.tableId === t.id)?.overdue).length;
  const legendItems = [
    { key: 'vip', label: 'VIP', color: VIP_COLOR, count: vipCount },
    { key: 'seated', label: 'Seated', color: darkMode ? '#334155' : TABLE_STATUS_COLORS.occupied.fill, count: statusCounts.occupied },
    { key: 'overdue', label: 'Overdue', color: overdueColour || DEFAULT_OVERDUE_COLOR, count: overdueCount },
    { key: 'open', label: 'Open', color: darkMode ? '#1c1c26' : TABLE_STATUS_COLORS.available.fill, count: statusCounts.available + statusCounts.cleaning },
    { key: 'reserved', label: 'Reserved', color: TABLE_STATUS_COLORS.reserved.fill, count: statusCounts.reserved },
  ];

  // White text reads fine on every dark/saturated fill this page uses; only
  // the Open/white base fill needs dark text instead, so this only has to
  // catch that one case rather than compute real luminance per colour.
  const isLightFill = (hex) => ['#FFFFFF', '#ffffff'].includes(hex);

  const renderTable = (t) => {
    const sc = TABLE_STATUS_COLORS[t.status] || TABLE_STATUS_COLORS.available;
    const isSelected = selectedTable === t.id;
    const isMergeSelected = mergeMode && mergeSelection.includes(t.id);
    const sectionObj = sections.find(s => s.name === t.section);
    const sectionColor = sectionObj?.color || '#6B7280';
    // Course-driven colour overrides status colour when a live state exists
    // (the table is actually seated) — VIP/overdue are drawn as separate
    // accent rings below rather than changing this fill, so which course a
    // table is in stays visible even when it's flagged VIP or running late.
    const liveState = courseStates.find(cs => cs.tableId === t.id);
    const isOpenBase = !liveState && (t.status === 'available' || t.status === 'cleaning');
    const fillColor = liveState?.colour || (isOpenBase && darkMode ? '#1c1c26' : sc.fill);
    const strokeColor = isMergeSelected ? '#4F46E5' : isSelected ? theme.primary : (liveState ? liveState.colour : (isOpenBase && darkMode ? '#3f3f4a' : sc.stroke));
    const textColor = isLightFill(fillColor) ? '#1F2937' : 'white';
    const textColorMuted = isLightFill(fillColor) ? 'rgba(31,41,55,0.7)' : 'rgba(255,255,255,0.8)';
    const isVip = !!liveState?.isVip;
    const isOverdue = !!liveState?.overdue;
    const needsCleaning = t.status === 'cleaning';
    const cx = t.x + t.width / 2, cy = t.y + t.height / 2;

    return (
      <g key={t.id} data-testid={`floor-table-${t.id}`}
        style={{ cursor: mode === 'edit' ? 'grab' : 'pointer' }}
        onMouseDown={(e) => handleMouseDown(e, t.id)}
        onClick={(e) => mode === 'view' ? handleTableStatusClick(t.id, e) : setSelectedTable(t.id)}
        onDoubleClick={() => mode === 'edit' && openTableEditor(t)}>
        {/* Shadow */}
        {t.shape === 'circle' ? (
          <ellipse cx={cx} cy={cy + 3} rx={t.width / 2} ry={t.height / 2} fill="rgba(0,0,0,0.08)" />
        ) : (
          <rect x={t.x + 2} y={t.y + 3} width={t.width} height={t.height}
            rx={t.shape === 'square' ? 4 : 8} fill="rgba(0,0,0,0.08)" />
        )}
        {/* Overdue accent ring — sits outside the table body so it reads as
            an alert around a table, not a colour change to the table itself. */}
        {isOverdue && (t.shape === 'circle' ? (
          <ellipse cx={cx} cy={cy} rx={t.width / 2 + 4} ry={t.height / 2 + 4}
            fill="none" stroke={overdueColour || DEFAULT_OVERDUE_COLOR} strokeWidth={2.5} data-testid={`overdue-ring-${t.id}`} />
        ) : (
          <rect x={t.x - 4} y={t.y - 4} width={t.width + 8} height={t.height + 8}
            rx={(t.shape === 'square' ? 4 : 8) + 4}
            fill="none" stroke={overdueColour || DEFAULT_OVERDUE_COLOR} strokeWidth={2.5} data-testid={`overdue-ring-${t.id}`} />
        ))}
        {/* Table body */}
        {t.shape === 'circle' ? (
          <ellipse cx={cx} cy={cy}
            rx={t.width / 2} ry={t.height / 2}
            fill={fillColor} stroke={strokeColor}
            strokeWidth={isMergeSelected ? 4 : isSelected ? 3 : 1.5} strokeDasharray={isMergeSelected ? '6 3' : undefined} opacity={0.9} />
        ) : (
          <rect x={t.x} y={t.y} width={t.width} height={t.height}
            rx={t.shape === 'square' ? 4 : 8}
            fill={fillColor} stroke={strokeColor}
            strokeWidth={isMergeSelected ? 4 : isSelected ? 3 : 1.5} strokeDasharray={isMergeSelected ? '6 3' : undefined} opacity={0.9} />
        )}
        {/* Table number */}
        <text x={cx} y={cy - 4}
          textAnchor="middle" fill={textColor} fontSize="14" fontWeight="bold">
          {t.number}
        </text>
        {/* Capacity */}
        <text x={cx} y={cy + 12}
          textAnchor="middle" fill={textColorMuted} fontSize="10">
          {t.maxCovers || t.capacity}p
        </text>
        {/* Section indicator */}
        <circle cx={t.x + t.width - 4} cy={t.y + 4} r={4} fill={sectionColor} stroke="white" strokeWidth={1} />
        {/* VIP badge */}
        {isVip && (
          <g transform={`translate(${t.x + 4}, ${t.y + 4})`} data-testid={`vip-badge-${t.id}`}>
            <circle r={7} fill={VIP_COLOR} stroke="white" strokeWidth={1} />
            <Crown x={-4} y={-4} width={8} height={8} color="white" strokeWidth={2.5} />
          </g>
        )}
        {/* Needs-cleaning badge */}
        {needsCleaning && (
          <g transform={`translate(${t.x + 4}, ${t.y + t.height - 4})`} data-testid={`cleaning-badge-${t.id}`}>
            <circle r={7} fill="#F59E0B" stroke="white" strokeWidth={1} />
            <BrushCleaning x={-4} y={-4} width={8} height={8} color="white" strokeWidth={2.5} />
          </g>
        )}
      </g>
    );
  };

  return (
    <div className="space-y-6" data-testid="floor-plan-page">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold" style={{ color: theme.text }}>Floor Plan</h1>
          <p className="text-sm text-gray-500 mt-1">Manage table layouts, sections & real-time status</p>
        </div>
        <div className="flex items-center gap-2">
          {plans.length > 1 && (
            <Select value={activePlanId || ''} onValueChange={switchPlan}>
              <SelectTrigger className="w-40" data-testid="plan-selector">
                <SelectValue placeholder="Select Floor" />
              </SelectTrigger>
              <SelectContent>
                {plans.map(p => <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>)}
              </SelectContent>
            </Select>
          )}
          <Button variant="outline" onClick={() => setNewPlanDialog(true)} data-testid="new-plan-btn">
            <Plus size={16} className="mr-1" /> New Floor
          </Button>
          {mode === 'view' && (
            <Button variant="outline" onClick={() => { setCombosOpen(true); fetchCombos(); }} data-testid="table-combos-btn">
              <Layers size={16} className="mr-1" /> Table Combinations
            </Button>
          )}
          {mode === 'view' && (
            <Button variant={mergeMode ? 'default' : 'outline'}
              onClick={() => { setMergeMode(m => !m); setMergeSelection([]); }}
              style={mergeMode ? { background: '#4F46E5' } : {}}
              data-testid="merge-tables-btn">
              {mergeMode ? 'Cancel Merge' : 'Merge Tables'}
            </Button>
          )}
          <Button variant={mode === 'edit' ? 'default' : 'outline'}
            onClick={() => setMode(mode === 'edit' ? 'view' : 'edit')}
            style={mode === 'edit' ? { background: theme.primary } : {}}
            data-testid="edit-mode-btn">
            {mode === 'edit' ? <><Eye size={16} className="mr-1" /> View Mode</> : <><Pencil size={16} className="mr-1" /> Edit Mode</>}
          </Button>
          {mode === 'edit' && (
            <Button onClick={savePlan} style={{ background: theme.primary }} data-testid="save-plan-btn">
              <Save size={16} className="mr-1" /> Save
            </Button>
          )}
        </div>
      </div>

      {/* Status legend */}
      <div className="flex items-center gap-6" data-testid="floor-legend">
        {legendItems.map(item => (
          <div key={item.key} className="flex items-center gap-2" data-testid={`legend-${item.key}`}>
            <div className="w-4 h-4 rounded border" style={{ background: item.color, borderColor: item.key === 'open' ? (darkMode ? '#3f3f4a' : '#CBD5E1') : item.color }} />
            <span className="text-sm" style={{ color: theme.text }}>{item.label}</span>
            <Badge variant="outline" className="text-xs ml-1">{item.count}</Badge>
          </div>
        ))}
        <div className="ml-auto text-sm text-gray-500">
          Total: <span className="font-bold">{tables.length}</span> tables |
          Capacity: <span className="font-bold">{tables.reduce((s, t) => s + (t.maxCovers || t.capacity || 0), 0)}</span> covers
        </div>
      </div>

      {mergeMode && (
        <div className="flex items-center gap-3 bg-indigo-50 border border-indigo-200 rounded-lg px-4 py-2" data-testid="merge-action-bar">
          <span className="text-sm text-indigo-700">
            {mergeSelection.length === 0 ? 'Select 2 or more occupied tables to combine their checks' : `${mergeSelection.length} table${mergeSelection.length === 1 ? '' : 's'} selected`}
          </span>
          {mergeSelection.length >= 2 && (
            <Button size="sm" style={{ background: '#4F46E5' }} onClick={handleMergeTables} data-testid="confirm-merge-btn">
              Merge into one check
            </Button>
          )}
          {mergeSelection.length > 0 && (
            <Button size="sm" variant="outline" onClick={() => setMergeSelection([])}>Clear</Button>
          )}
        </div>
      )}

      <div className="flex gap-4">
        {/* Canvas */}
        <Card className="flex-1 border-0 shadow-sm">
          <CardContent className="p-4">
            <svg ref={canvasRef} width="100%" height="580" viewBox="0 0 1000 580"
              className="rounded-lg border"
              style={{
                // Light mode: a soft brand-tinted gradient (orange → white →
                // purple, echoing the logo) instead of a flat grey box. Dark
                // mode: the same surface colour as the sidebar/menu panel
                // (--nua-surface) so the canvas doesn't look like a mismatched
                // cutout against the rest of the dark shell.
                background: darkMode
                  ? 'var(--nua-surface)'
                  : 'linear-gradient(135deg, rgba(245,140,20,0.06), rgba(255,255,255,1) 45%, rgba(139,92,246,0.06))',
                borderColor: darkMode ? '#2a2a35' : '#e5e7eb',
              }}
              onMouseMove={handleMouseMove} onMouseUp={handleMouseUp} onMouseLeave={handleMouseUp}
              data-testid="floor-canvas">
              {/* Grid lines */}
              {Array.from({ length: 21 }, (_, i) => (
                <line key={`gv${i}`} x1={i * 50} y1={0} x2={i * 50} y2={580} stroke={darkMode ? '#26262f' : '#e5e7eb'} strokeWidth={0.5} />
              ))}
              {Array.from({ length: 12 }, (_, i) => (
                <line key={`gh${i}`} x1={0} y1={i * 50} x2={1000} y2={i * 50} stroke={darkMode ? '#26262f' : '#e5e7eb'} strokeWidth={0.5} />
              ))}
              {/* Tables */}
              {tables.map(renderTable)}
              {/* Empty state */}
              {tables.length === 0 && (
                <text x="500" y="290" textAnchor="middle" fill="#9CA3AF" fontSize="16">
                  {mode === 'edit' ? 'Click "Add Table" to start designing your floor plan' : 'No tables yet. Switch to Edit mode to add tables.'}
                </text>
              )}
            </svg>
          </CardContent>
        </Card>

        {/* Side panel - Edit mode tools */}
        {mode === 'edit' && (
          <div className="w-64 space-y-4">
            <Card className="border-0 shadow-sm">
              <CardHeader className="pb-2 pt-4 px-4">
                <CardTitle className="text-sm">Tools</CardTitle>
              </CardHeader>
              <CardContent className="p-4 pt-0 space-y-2">
                <Button className="w-full justify-start" variant="outline" onClick={addTable} data-testid="add-table-btn">
                  <Plus size={16} className="mr-2" /> Add Table
                </Button>
                {selectedTable && (
                  <>
                    <Button className="w-full justify-start" variant="outline" onClick={() => {
                      const t = tables.find(tb => tb.id === selectedTable);
                      if (t) openTableEditor(t);
                    }} data-testid="edit-table-props-btn">
                      <Settings size={16} className="mr-2" /> Edit Properties
                    </Button>
                    <Button className="w-full justify-start text-red-600 hover:text-red-700" variant="outline"
                      onClick={() => deleteTable(selectedTable)} data-testid="delete-table-btn">
                      <Trash2 size={16} className="mr-2" /> Delete Table
                    </Button>
                  </>
                )}
              </CardContent>
            </Card>

            {/* Sections */}
            <Card className="border-0 shadow-sm">
              <CardHeader className="pb-2 pt-4 px-4">
                <CardTitle className="text-sm">Sections</CardTitle>
              </CardHeader>
              <CardContent className="p-4 pt-0 space-y-2">
                {sections.map((s, i) => (
                  <div key={s.id || i} className="flex items-center gap-2">
                    <div className="w-3 h-3 rounded-full" style={{ background: s.color }} />
                    <Input value={s.name} className="h-8 text-sm" onChange={e => {
                      const updated = [...sections];
                      updated[i] = { ...updated[i], name: e.target.value };
                      setSections(updated);
                    }} />
                  </div>
                ))}
                <Button variant="ghost" size="sm" className="w-full text-xs" onClick={() => {
                  setSections([...sections, { id: `SEC-${Date.now()}`, name: `Section ${sections.length + 1}`, color: SECTIONS_COLORS[sections.length % SECTIONS_COLORS.length] }]);
                }} data-testid="add-section-btn">
                  <Plus size={12} className="mr-1" /> Add Section
                </Button>
              </CardContent>
            </Card>

            {/* Selected table info */}
            {selectedTable && (() => {
              const t = tables.find(tb => tb.id === selectedTable);
              if (!t) return null;
              return (
                <Card className="border-0 shadow-sm">
                  <CardHeader className="pb-2 pt-4 px-4">
                    <CardTitle className="text-sm">Table {t.number}</CardTitle>
                  </CardHeader>
                  <CardContent className="p-4 pt-0 text-xs space-y-1 text-gray-600">
                    <p>Shape: {t.shape}</p>
                    <p>Section: {t.section}</p>
                    <p>Covers: {t.minCovers}-{t.maxCovers}</p>
                    <p>Position: ({Math.round(t.x)}, {Math.round(t.y)})</p>
                  </CardContent>
                </Card>
              );
            })()}
          </div>
        )}
      </div>

      {/* Table editor dialog */}
      <Dialog open={tableDialog} onOpenChange={setTableDialog}>
        <DialogContent className="max-w-sm" data-testid="table-editor-dialog">
          <DialogHeader>
            <DialogTitle>Table Properties</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <label className="text-xs font-medium text-gray-500 mb-1 block">Table Number</label>
              <Input data-testid="table-number-input" value={tableForm.number} onChange={e => setTableForm(f => ({ ...f, number: e.target.value }))} />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs font-medium text-gray-500 mb-1 block">Min Covers</label>
                <Input type="number" min={1} value={tableForm.minCovers} onChange={e => setTableForm(f => ({ ...f, minCovers: e.target.value }))} />
              </div>
              <div>
                <label className="text-xs font-medium text-gray-500 mb-1 block">Max Covers</label>
                <Input type="number" min={1} value={tableForm.maxCovers} onChange={e => setTableForm(f => ({ ...f, maxCovers: e.target.value }))} />
              </div>
            </div>
            <div>
              <label className="text-xs font-medium text-gray-500 mb-1 block">Shape</label>
              <Select value={tableForm.shape} onValueChange={v => setTableForm(f => ({ ...f, shape: v }))}>
                <SelectTrigger data-testid="shape-select"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="rectangle">Rectangle</SelectItem>
                  <SelectItem value="circle">Circle</SelectItem>
                  <SelectItem value="square">Square</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <label className="text-xs font-medium text-gray-500 mb-1 block">Section</label>
              <Select value={tableForm.section} onValueChange={v => setTableForm(f => ({ ...f, section: v }))}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {sections.map(s => <SelectItem key={s.id} value={s.name}>{s.name}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setTableDialog(false)}>Cancel</Button>
            <Button onClick={saveTableEdit} style={{ background: theme.primary }} data-testid="save-table-btn">Save</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* New plan dialog */}
      <Dialog open={newPlanDialog} onOpenChange={setNewPlanDialog}>
        <DialogContent className="max-w-sm" data-testid="new-plan-dialog">
          <DialogHeader>
            <DialogTitle>New Floor Plan</DialogTitle>
          </DialogHeader>
          <div>
            <label className="text-xs font-medium text-gray-500 mb-1 block">Floor Name</label>
            <Input data-testid="new-plan-name-input" value={newPlanName} onChange={e => setNewPlanName(e.target.value)}
              placeholder="e.g. Outdoor Patio, Upstairs" />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setNewPlanDialog(false)}>Cancel</Button>
            <Button onClick={createPlan} style={{ background: theme.primary }} data-testid="create-plan-btn">Create</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Table Combinations dialog — which tables can be pushed together for
          a large party. Separate concept from Merge Tables (live checks). */}
      <Dialog open={combosOpen} onOpenChange={setCombosOpen}>
        <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto" data-testid="table-combos-dialog">
          <DialogHeader>
            <DialogTitle>Table Combinations</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-gray-500 -mt-2">
            Group tables that can be pushed together for a large party. Click to select, then combine.
          </p>
          <div className="grid grid-cols-6 md:grid-cols-8 gap-2">
            {tables.map(t => {
              const key = t.number?.toString() || t.id;
              const isSelected = comboSelection.includes(key);
              return (
                <button key={key} onClick={() => toggleComboSelect(key)}
                  className={`p-2 rounded-lg border-2 text-center transition-all cursor-pointer ${isSelected ? 'border-blue-500 bg-blue-50 shadow-md' : 'border-gray-200 hover:border-gray-400'}`}
                  data-testid={`combo-table-${key}`}>
                  <p className="text-sm font-bold">{t.number || t.id}</p>
                  <p className="text-[10px] text-gray-500">{t.maxCovers || t.capacity || 4} seats</p>
                </button>
              );
            })}
            {tables.length === 0 && <p className="col-span-full text-gray-400 text-sm text-center py-4">No tables on this floor yet.</p>}
          </div>
          {comboSelection.length > 0 && (
            <div className="flex items-center gap-3 p-3 bg-blue-50 rounded-lg border border-blue-200">
              <Badge className="bg-blue-600 text-white">{comboSelection.length} selected</Badge>
              <Input placeholder="Combination name" className="flex-1 h-8 text-sm" value={comboName} onChange={e => setComboName(e.target.value)} data-testid="combo-name-input" />
              <Input type="number" placeholder="Max covers" className="w-28 h-8 text-sm" value={comboMaxCovers} onChange={e => setComboMaxCovers(e.target.value)} data-testid="combo-covers-input" />
              <Button size="sm" style={{ background: theme.primary }} onClick={createCombo} data-testid="create-combo-btn"><Plus size={14} className="mr-1" /> Add</Button>
            </div>
          )}
          <div className="space-y-2 pt-2 border-t">
            <p className="text-sm font-medium">Existing Combinations</p>
            {combos.map(c => (
              <div key={c.id} className="flex items-center justify-between p-3 bg-gray-50 rounded-lg" data-testid={`combo-${c.id}`}>
                <div>
                  <p className="font-medium text-sm">{c.name}</p>
                  <p className="text-xs text-gray-500">Tables: {(c.tableIds || []).join(', ')} | Max {c.maxCovers} covers</p>
                </div>
                <Button variant="ghost" size="sm" className="text-red-500" onClick={() => deleteCombo(c.id)}><Trash2 size={14} /></Button>
              </div>
            ))}
            {combos.length === 0 && <p className="text-gray-400 text-sm text-center py-4">No combinations yet</p>}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCombosOpen(false)}>Close</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Course-aware side drawer */}
      <TableInfoDrawer
        open={!!drawerTable}
        onClose={() => setDrawerTable(null)}
        table={drawerTable}
        states={courseStates}
        courses={courseDefs}
        overdueColour={overdueColour}
        onRefresh={fetchCourses}
        onOpenCourseSettings={() => { setCourseDraft(courseDefs.map(c => ({ ...c }))); setCourseSettingsOpen(true); }}
      />

      {/* Course settings dialog */}
      <Dialog open={courseSettingsOpen} onOpenChange={setCourseSettingsOpen}>
        <DialogContent className="max-w-lg max-h-[90vh] overflow-y-auto" data-testid="course-settings-dialog">
          <DialogHeader>
            <DialogTitle>Dining Course Thresholds</DialogTitle>
          </DialogHeader>
          <div className="text-xs text-gray-500 mb-2">
            Set the maximum minutes a table should stay in each course. Colours are applied to the floor plan; tables that go over the threshold flash in the overdue colour.
          </div>
          <div className="space-y-2">
            {courseDraft.map((c, idx) => (
              <div key={c.key} className="flex items-center gap-2 border rounded p-2" data-testid={`course-row-${c.key}`}>
                <input type="color" value={c.colour} onChange={e => setCourseDraft(d => d.map((x, i) => i === idx ? { ...x, colour: e.target.value } : x))} data-testid={`course-colour-${c.key}`} />
                <Input value={c.label} onChange={e => setCourseDraft(d => d.map((x, i) => i === idx ? { ...x, label: e.target.value } : x))} className="flex-1" data-testid={`course-label-${c.key}`} />
                <Input type="number" min="1" value={c.maxMinutes} onChange={e => setCourseDraft(d => d.map((x, i) => i === idx ? { ...x, maxMinutes: parseInt(e.target.value || '0', 10) } : x))} className="w-20" data-testid={`course-max-${c.key}`} />
                <span className="text-[10px] text-gray-400">min</span>
              </div>
            ))}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCourseSettingsOpen(false)}>Cancel</Button>
            <Button onClick={async () => {
              try {
                await tableCoursesAPI.updateSettings({ courses: courseDraft, autoAdvance: false });
                toast.success('Course thresholds saved');
                setCourseSettingsOpen(false);
                fetchCourses();
              } catch { toast.error('Save failed'); }
            }} style={{ background: theme.primary }} data-testid="save-course-settings">Save</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
