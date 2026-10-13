import React, { useMemo, useState, useEffect } from 'react';
import { ChevronLeft, ChevronRight, Sparkles, RefreshCcw, Wand2, Trash2, Send, Calendar, Pencil, Copy, Clock, TrendingUp } from 'lucide-react';
import { Button } from '../ui/button';
import { Input } from '../ui/input';
import { Card, CardContent } from '../ui/card';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '../ui/dialog';
import { toast } from 'sonner';
import { socialAPI } from '../../services/api';
import { DialogService } from '../../platform';
import {
  DndContext, PointerSensor, TouchSensor, useSensor, useSensors,
  useDraggable, useDroppable, DragOverlay,
} from '@dnd-kit/core';

/**
 * Month-grid content calendar for /social-media.
 *
 * Each day cell shows scheduled & published posts as colour-coded chips
 * (one colour per platform). Drag a chip onto another day → reschedules
 * the post via PATCH /api/social/posts/{id}. The "AI Weekly Plan" button
 * generates a 7-day cross-platform schedule from top-selling products +
 * active promos (POST /api/social/ai-weekly-plan).
 *
 * Pure presentational where it can be — the parent SocialMedia.jsx owns
 * the posts array, account list and reload() callback.
 */
const PLATFORM_COLORS = {
  instagram: '#E1306C',
  facebook:  '#1877F2',
  tiktok:    '#69C9D0',
  x:         '#000000',
  google_business: '#34A853',
};

const sameDay = (a, b) =>
  a.getFullYear() === b.getFullYear()
  && a.getMonth() === b.getMonth()
  && a.getDate() === b.getDate();

const startOfMonthGrid = (anchor) => {
  // First Monday-or-earlier sunday before the 1st of the month.
  const first = new Date(anchor.getFullYear(), anchor.getMonth(), 1);
  const weekday = first.getDay();           // 0..6, Sunday=0
  const offset = (weekday + 6) % 7;          // Monday-first grid → Mon=0
  return new Date(first.getFullYear(), first.getMonth(), 1 - offset);
};

// ── Draggable chip (touch-friendly via @dnd-kit) ─────────────────────
const DraggablePostChip = ({ post, onClick }) => {
  const disabled = post.status === 'published';
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `post-${post.id}`,
    data: { postId: post.id, platform: post.platform, status: post.status },
    disabled,
  });
  return (
    <div
      ref={setNodeRef}
      {...(disabled ? {} : listeners)}
      {...(disabled ? {} : attributes)}
      onClick={onClick}
      className={`text-[10px] rounded px-1.5 py-0.5 truncate cursor-grab active:cursor-grabbing hover:brightness-95 ${post.status === 'published' ? 'opacity-80' : ''} ${isDragging ? 'opacity-40' : ''}`}
      style={{
        background: `${PLATFORM_COLORS[post.platform] || '#888'}15`,
        borderLeft: `3px solid ${PLATFORM_COLORS[post.platform] || '#888'}`,
        color: PLATFORM_COLORS[post.platform] || '#444',
        touchAction: 'none',
      }}
      title={post.caption}
      data-testid={`cal-post-${post.id}`}
    >
      <span className="font-semibold mr-1">
        {post.status === 'published' ? '✓' : post.status === 'scheduled' ? '◷' : '✎'}
      </span>
      <span className="font-medium">{(post.platform || '').slice(0, 2).toUpperCase()}</span>
      <span className="ml-1 opacity-80">{(post.caption || '').slice(0, 16)}</span>
    </div>
  );
};

// ── Droppable day cell ────────────────────────────────────────────────
const DroppableDay = ({ day, inMonth, isToday, children }) => {
  const { setNodeRef, isOver } = useDroppable({
    id: `day-${day.toISOString().slice(0, 10)}`,
    data: { day: day.toISOString() },
  });
  return (
    <div
      ref={setNodeRef}
      className={`min-h-[88px] p-1.5 rounded border text-xs transition-colors ${inMonth ? 'bg-white' : 'bg-gray-50/60 opacity-60'} ${isToday ? 'ring-2 ring-orange-300' : ''} ${isOver ? 'bg-amber-50 ring-2 ring-amber-300' : ''}`}
      data-testid={`cal-cell-${day.toISOString().slice(0, 10)}`}
    >
      {children}
    </div>
  );
};

export const SocialCalendar = ({ theme, posts, accounts, onReload }) => {
  const [anchor, setAnchor] = useState(new Date());
  const [planning, setPlanning] = useState(false);
  const [planJob, setPlanJob] = useState(null);   // {planId, completed, expected, status}
  const [activeDragPost, setActiveDragPost] = useState(null);
  const [editingPost, setEditingPost] = useState(null);
  const [editForm, setEditForm] = useState({ caption: '', hashtags: '', scheduledFor: '', imageUrl: '', status: 'scheduled' });
  const [bestTimes, setBestTimes] = useState([]);     // [{platform, recommendedHour, recommendedTime, sampleSize, source, band}]
  const [useBestTimes, setUseBestTimes] = useState(true);

  // Sensors: mouse + touch. `activationConstraint` prevents the pointer
  // from grabbing a chip when the user just wants to click/tap.
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 180, tolerance: 6 } }),
  );

  // Pull POS peak-hour analytics once on mount so the chip strip + AI
  // weekly plan can both lean on the same numbers.
  useEffect(() => {
    let cancelled = false;
    socialAPI.bestTimes()
      .then(r => { if (!cancelled) setBestTimes(r.data || []); })
      .catch(() => { /* non-fatal — chips just won't render */ });
    return () => { cancelled = true; };
  }, []);

  // Convenient lookup: { instagram: 12, facebook: 18, ... }
  const bestHourByPlatform = useMemo(() => {
    const m = {};
    bestTimes.forEach(b => { m[b.platform] = b.recommendedHour; });
    return m;
  }, [bestTimes]);

  // Build a 6-week grid (42 cells) starting at the first Monday on/before
  // the 1st of the anchored month. This keeps the layout stable across
  // 28/29/30/31-day months.
  const gridDays = useMemo(() => {
    const start = startOfMonthGrid(anchor);
    return Array.from({ length: 42 }, (_, i) => {
      const d = new Date(start);
      d.setDate(start.getDate() + i);
      return d;
    });
  }, [anchor]);

  const postsByDay = useMemo(() => {
    const map = new Map();
    (posts || []).forEach((p) => {
      const ts = p.scheduledFor || p.publishedAt || p.createdAt;
      if (!ts) return;
      const d = new Date(ts);
      if (isNaN(d)) return;
      const key = `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
      if (!map.has(key)) map.set(key, []);
      map.get(key).push(p);
    });
    return map;
  }, [posts]);

  const monthLabel = anchor.toLocaleDateString(undefined, { month: 'long', year: 'numeric' });
  const today = new Date();

  // -------- Drag-to-reschedule (touch-friendly via @dnd-kit) --------
  const rescheduleTo = async (post, day) => {
    const old = post.scheduledFor ? new Date(post.scheduledFor) : new Date();
    const next = new Date(day);
    if (useBestTimes && bestHourByPlatform[post.platform] !== undefined) {
      next.setHours(bestHourByPlatform[post.platform], 0, 0, 0);
    } else {
      next.setHours(old.getHours() || 12, old.getMinutes() || 0, 0, 0);
    }
    try {
      await socialAPI.updatePost(post.id, {
        scheduledFor: next.toISOString(),
        status: post.status === 'draft' ? 'scheduled' : post.status,
      });
      toast.success(`Rescheduled to ${next.toLocaleDateString()} ${next.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`);
      onReload && onReload();
    } catch {
      toast.error('Reschedule failed');
    }
  };

  const onDragStart = (event) => {
    const p = (posts || []).find(x => `post-${x.id}` === event.active.id);
    if (p) setActiveDragPost(p);
  };
  const onDragEnd = (event) => {
    setActiveDragPost(null);
    const { active, over } = event;
    if (!over) return;
    const postId = active.data?.current?.postId;
    const dayIso = over.data?.current?.day;
    if (!postId || !dayIso) return;
    const post = (posts || []).find(p => p.id === postId);
    if (!post) return;
    rescheduleTo(post, new Date(dayIso));
  };

  const handleWeeklyPlan = async () => {
    if (!accounts || accounts.length === 0) {
      return toast.error('Connect at least one social account first');
    }
    if (!await DialogService.confirm('Generate a 7-day plan? Existing auto-plan posts in the window will be replaced.')) return;
    setPlanning(true);
    try {
      const r = await socialAPI.aiWeeklyPlan({ daysAhead: 7, save: true, tone: 'warm', postTime: '12:00', useBestTimes });
      const job = r.data || {};
      if (job.status === 'queued' || job.status === 'in_progress') {
        // Background mode: poll progress until done.
        setPlanJob({ planId: job.planId, completed: 0, expected: job.expected, status: job.status });
        toast.success(`Plan queued — ${job.expected} posts coming up…`);
        const startedAt = Date.now();
        const poll = async () => {
          try {
            const s = await socialAPI.getPlanJob(job.planId);
            setPlanJob(s.data);
            if (s.data?.status === 'complete') {
              toast.success(`Done — ${s.data.completed} posts saved${s.data.fallbacks ? ` (${s.data.fallbacks} fallback)` : ''}`);
              onReload && onReload();
              setPlanJob(null);
              setPlanning(false);
              return;
            }
            if (s.data?.status === 'failed') {
              toast.error(`Plan failed: ${s.data.error || 'unknown'}`);
              onReload && onReload();
              setPlanJob(null);
              setPlanning(false);
              return;
            }
            // Refresh the calendar mid-flight so chips appear as they're generated.
            if ((s.data?.completed || 0) > 0) onReload && onReload();
            if (Date.now() - startedAt > 180000) {  // 3min safety net
              toast.warning('Plan still running — check back shortly.');
              setPlanJob(null);
              setPlanning(false);
              return;
            }
            setTimeout(poll, 2500);
          } catch {
            setTimeout(poll, 3500);
          }
        };
        setTimeout(poll, 2000);
      } else {
        // Legacy synchronous path (shouldn't fire post-iter40 but kept for safety).
        toast.success(`Saved ${r.data?.saved} posts across ${r.data?.platformsUsed?.length || 0} platforms`);
        onReload && onReload();
        setPlanning(false);
      }
    } catch (e) {
      const detail = e?.response?.data?.detail;
      const msg = typeof detail === 'object' && detail !== null
        ? (detail.message || JSON.stringify(detail))
        : (detail || 'AI plan failed');
      toast.error(msg);
      setPlanning(false);
    }
  };

  const handlePublish = async (id) => {
    try { await socialAPI.publishPost(id); toast.success('Published'); onReload && onReload(); }
    catch { toast.error('Publish failed'); }
  };
  const handleDelete = async (id) => {
    if (!await DialogService.confirm('Delete this post?')) return;
    try { await socialAPI.deletePost(id); toast.success('Deleted'); onReload && onReload(); }
    catch { toast.error('Failed'); }
  };

  // Edit existing post (owner reuse / tweak)
  const openEdit = (post) => {
    setEditingPost(post);
    const sched = post.scheduledFor ? new Date(post.scheduledFor) : null;
    const local = sched && !isNaN(sched)
      ? new Date(sched.getTime() - sched.getTimezoneOffset() * 60000).toISOString().slice(0, 16)
      : '';
    setEditForm({
      caption: post.caption || '',
      hashtags: (post.hashtags || []).join(' '),
      scheduledFor: local,
      imageUrl: post.imageUrl || '',
      status: post.status === 'published' ? 'published' : (post.status || 'scheduled'),
    });
  };
  const saveEdit = async () => {
    if (!editingPost) return;
    const body = {
      caption: editForm.caption,
      hashtags: editForm.hashtags.split(/\s+/).filter(Boolean),
      imageUrl: editForm.imageUrl || null,
    };
    if (editForm.scheduledFor) body.scheduledFor = new Date(editForm.scheduledFor).toISOString();
    if (editForm.status && editingPost.status !== 'published') body.status = editForm.status;
    try {
      await socialAPI.updatePost(editingPost.id, body);
      toast.success('Post updated');
      setEditingPost(null);
      onReload && onReload();
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Update failed');
    }
  };
  const duplicatePost = async (post) => {
    if (!await DialogService.confirm(`Duplicate this post as a new draft? You can edit and reschedule the copy.`)) return;
    try {
      await socialAPI.duplicatePost(post.id, { status: 'draft' });
      toast.success('Duplicated as draft');
      onReload && onReload();
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Duplicate failed');
    }
  };

  // KPIs
  const counts = useMemo(() => {
    const c = { scheduled: 0, published: 0, draft: 0 };
    (posts || []).forEach((p) => {
      if (p.status === 'scheduled') c.scheduled++;
      else if (p.status === 'published') c.published++;
      else if (p.status === 'draft') c.draft++;
    });
    return c;
  }, [posts]);

  return (
    <Card data-testid="social-calendar">
      <CardContent className="p-4 space-y-3">
        {/* Header row */}
        <div className="flex flex-wrap items-center gap-2">
          <Calendar size={18} style={{ color: theme.primary }} />
          <h2 className="text-lg font-bold" style={{ color: theme.text }}>Content Calendar</h2>
          <div className="ml-auto flex items-center gap-1.5">
            <Button size="sm" variant="outline" onClick={() => setAnchor(new Date(anchor.getFullYear(), anchor.getMonth() - 1, 1))} data-testid="cal-prev">
              <ChevronLeft size={14} />
            </Button>
            <span className="text-sm font-semibold min-w-[150px] text-center" data-testid="cal-month-label">{monthLabel}</span>
            <Button size="sm" variant="outline" onClick={() => setAnchor(new Date(anchor.getFullYear(), anchor.getMonth() + 1, 1))} data-testid="cal-next">
              <ChevronRight size={14} />
            </Button>
            <Button size="sm" variant="outline" onClick={() => setAnchor(new Date())} data-testid="cal-today">Today</Button>
            <Button
              size="sm"
              className="text-white hover:opacity-90"
              style={{ background: theme.primary }}
              onClick={handleWeeklyPlan}
              disabled={planning}
              data-testid="ai-weekly-plan-btn"
            >
              {planning ? <><RefreshCcw size={12} className="mr-1.5 animate-spin" /> Planning…</>
                        : <><Wand2 size={12} className="mr-1.5" /> AI Weekly Plan</>}
            </Button>
          </div>
        </div>

        {/* AI Weekly Plan progress */}
        {planJob && (
          <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 flex items-center gap-3" data-testid="plan-progress-bar">
            <RefreshCcw size={14} className="animate-spin" style={{ color: theme.primary }} />
            <div className="flex-1">
              <div className="text-xs font-semibold text-amber-900">
                AI Weekly Plan running — {planJob.completed || 0} / {planJob.expected || '?'} posts
              </div>
              <div className="h-1.5 bg-amber-200 rounded-full mt-1 overflow-hidden">
                <div
                  className="h-full rounded-full transition-all"
                  style={{
                    width: `${Math.min(100, ((planJob.completed || 0) / Math.max(1, planJob.expected || 1)) * 100)}%`,
                    background: theme.primary,
                  }}
                />
              </div>
            </div>
            <span className="text-[10px] uppercase text-amber-700 tracking-widest">{planJob.status}</span>
          </div>
        )}

        {/* KPI strip */}
        <div className="flex items-center gap-3 text-xs">
          <span className="px-2 py-0.5 rounded-full bg-amber-100 text-amber-800 font-semibold" data-testid="kpi-scheduled">
            {counts.scheduled} scheduled
          </span>
          <span className="px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-800 font-semibold" data-testid="kpi-published">
            {counts.published} published
          </span>
          <span className="px-2 py-0.5 rounded-full bg-gray-100 text-gray-700 font-semibold" data-testid="kpi-drafts">
            {counts.draft} drafts
          </span>
          <span className="ml-auto text-[10px] text-gray-400">Drag a chip onto another day to reschedule</span>
        </div>

        {/* Best-time-to-post strip — POS analytics → recommended hour per platform */}
        {bestTimes.length > 0 && (
          <div className="rounded-lg border border-dashed bg-gradient-to-r from-emerald-50/40 via-amber-50/40 to-rose-50/40 px-3 py-2" data-testid="best-times-strip">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="flex items-center gap-1 text-[10px] uppercase tracking-widest text-gray-500 font-semibold">
                <TrendingUp size={11} /> Best time to post
              </span>
              {bestTimes.map(bt => {
                const src = bt.source === 'pos_peak'
                  ? { label: 'POS', tone: 'bg-emerald-100 text-emerald-700' }
                  : bt.source === 'pos_peak_clamped'
                  ? { label: 'POS±', tone: 'bg-amber-100 text-amber-700' }
                  : { label: 'Default', tone: 'bg-gray-100 text-gray-500' };
                return (
                  <span
                    key={bt.platform}
                    className="inline-flex items-center gap-1 text-[10px] rounded-full px-2 py-0.5 border bg-white"
                    style={{ borderLeft: `3px solid ${PLATFORM_COLORS[bt.platform] || '#888'}` }}
                    title={`${bt.platformLabel} — recommended ${bt.recommendedTime} (sample ${bt.sampleSize}, source ${bt.source})`}
                    data-testid={`best-time-${bt.platform}`}
                  >
                    <Clock size={10} style={{ color: PLATFORM_COLORS[bt.platform] || '#888' }} />
                    <span className="font-semibold capitalize">{bt.platform.replace('_', ' ')}</span>
                    <span className="font-mono">{bt.recommendedTime}</span>
                    <span className={`px-1 rounded-sm font-bold ${src.tone}`}>{src.label}</span>
                  </span>
                );
              })}
              <label className="ml-auto flex items-center gap-1 text-[10px] text-gray-600 cursor-pointer" data-testid="use-best-times-toggle">
                <input
                  type="checkbox"
                  className="accent-emerald-600"
                  checked={useBestTimes}
                  onChange={e => setUseBestTimes(e.target.checked)}
                  data-testid="use-best-times-checkbox"
                />
                Use best times in AI plan &amp; drag-drop
              </label>
            </div>
          </div>
        )}

        {/* Day-of-week header */}
        <div className="grid grid-cols-7 gap-1 text-[10px] uppercase tracking-widest text-gray-400 px-0.5">
          {['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].map(d => <div key={d}>{d}</div>)}
        </div>

        {/* 6×7 month grid */}
        <DndContext sensors={sensors} onDragStart={onDragStart} onDragEnd={onDragEnd}>
          <div className="grid grid-cols-7 gap-1" data-testid="calendar-grid">
            {gridDays.map((day, idx) => {
              const inMonth = day.getMonth() === anchor.getMonth();
              const isToday = sameDay(day, today);
              const key = `${day.getFullYear()}-${day.getMonth()}-${day.getDate()}`;
              const dayPosts = postsByDay.get(key) || [];
              return (
                <DroppableDay key={idx} day={day} inMonth={inMonth} isToday={isToday}>
                  <div className={`text-[10px] font-semibold ${isToday ? 'text-orange-600' : 'text-gray-500'} mb-1`}>
                    {day.getDate()}
                  </div>
                  <div className="space-y-1">
                    {dayPosts.slice(0, 4).map((p) => (
                      <DraggablePostChip key={p.id} post={p} onClick={() => openEdit(p)} />
                    ))}
                    {dayPosts.length > 4 && (
                      <div className="text-[9px] text-gray-400">+{dayPosts.length - 4} more</div>
                    )}
                  </div>
                </DroppableDay>
              );
            })}
          </div>
          <DragOverlay dropAnimation={null}>
            {activeDragPost ? (
              <div
                className="text-[10px] rounded px-1.5 py-0.5 shadow-lg"
                style={{
                  background: `${PLATFORM_COLORS[activeDragPost.platform] || '#888'}30`,
                  borderLeft: `3px solid ${PLATFORM_COLORS[activeDragPost.platform] || '#888'}`,
                  color: PLATFORM_COLORS[activeDragPost.platform] || '#444',
                }}
                data-testid="drag-overlay"
              >
                <span className="font-medium">{(activeDragPost.platform || '').slice(0, 2).toUpperCase()}</span>
                <span className="ml-1 opacity-80">{(activeDragPost.caption || '').slice(0, 16)}</span>
              </div>
            ) : null}
          </DragOverlay>
        </DndContext>

        {/* Upcoming next 7 days */}
        <div className="mt-2 border-t pt-3" data-testid="upcoming-strip">
          <h3 className="text-xs uppercase tracking-widest text-gray-500 mb-2 flex items-center gap-1.5">
            <Sparkles size={12} /> Next 7 days
          </h3>
          {(() => {
            const win = (posts || [])
              .filter((p) => p.scheduledFor)
              .filter((p) => {
                const t = new Date(p.scheduledFor).getTime();
                return t >= Date.now() && t <= Date.now() + 7 * 86400000;
              })
              .sort((a, b) => a.scheduledFor.localeCompare(b.scheduledFor))
              .slice(0, 8);
            if (win.length === 0) {
              return <p className="text-xs text-gray-400 italic">Nothing scheduled in the next 7 days — try AI Weekly Plan.</p>;
            }
            return (
              <ul className="space-y-1">
                {win.map((p) => (
                  <li
                    key={p.id}
                    className="flex items-center gap-2 text-xs hover:bg-gray-50 rounded px-1.5 py-1"
                    data-testid={`upcoming-${p.id}`}
                  >
                    <span
                      className="w-2 h-2 rounded-full shrink-0"
                      style={{ background: PLATFORM_COLORS[p.platform] || '#888' }}
                    />
                    <span className="font-semibold w-20">{new Date(p.scheduledFor).toLocaleDateString(undefined, { weekday: 'short', day: 'numeric' })}</span>
                    <span className="text-gray-500 w-20">{p.platform}</span>
                    <span className="flex-1 truncate">{p.caption}</span>
                    <button onClick={() => openEdit(p)} className="text-gray-400 hover:text-blue-600" data-testid={`upcoming-edit-${p.id}`} title="Edit">
                      <Pencil size={12} />
                    </button>
                    <button onClick={() => duplicatePost(p)} className="text-gray-400 hover:text-purple-600" data-testid={`upcoming-duplicate-${p.id}`} title="Duplicate / reuse">
                      <Copy size={12} />
                    </button>
                    <button onClick={() => handlePublish(p.id)} className="text-gray-400 hover:text-emerald-600" data-testid={`upcoming-publish-${p.id}`} title="Publish now">
                      <Send size={12} />
                    </button>
                    <button onClick={() => handleDelete(p.id)} className="text-gray-400 hover:text-red-600" data-testid={`upcoming-delete-${p.id}`} title="Delete">
                      <Trash2 size={12} />
                    </button>
                  </li>
                ))}
              </ul>
            );
          })()}
        </div>

        {/* Edit/Reuse dialog */}
        <Dialog open={!!editingPost} onOpenChange={(o) => { if (!o) setEditingPost(null); }}>
          <DialogContent className="max-w-md" data-testid="edit-post-dialog">
            <DialogHeader>
              <DialogTitle className="flex items-center justify-between">
                <span>Edit Post</span>
                {editingPost && (
                  <button onClick={() => duplicatePost(editingPost)}
                    className="text-xs text-purple-600 hover:underline flex items-center gap-1"
                    data-testid="edit-dialog-duplicate">
                    <Copy size={12} /> Duplicate as draft
                  </button>
                )}
              </DialogTitle>
            </DialogHeader>
            {editingPost && (
              <div className="space-y-3 py-2">
                <div className="text-[10px] uppercase text-gray-500 tracking-widest">
                  {editingPost.platform} · {editingPost.postType} · {editingPost.status}
                </div>
                <textarea
                  className="w-full p-2 border rounded text-sm min-h-[100px]"
                  value={editForm.caption}
                  onChange={(e) => setEditForm({ ...editForm, caption: e.target.value })}
                  placeholder="Caption..."
                  data-testid="edit-caption"
                />
                <Input
                  placeholder="Hashtags (space-separated, e.g. #foodie #nua)"
                  value={editForm.hashtags}
                  onChange={(e) => setEditForm({ ...editForm, hashtags: e.target.value })}
                  data-testid="edit-hashtags"
                />
                <Input
                  type="datetime-local"
                  value={editForm.scheduledFor}
                  onChange={(e) => setEditForm({ ...editForm, scheduledFor: e.target.value })}
                  data-testid="edit-scheduledfor"
                />
                <Input
                  placeholder="Image URL (or paste a data URL)"
                  value={editForm.imageUrl}
                  onChange={(e) => setEditForm({ ...editForm, imageUrl: e.target.value })}
                  data-testid="edit-imageurl"
                />
                {editingPost.status !== 'published' && (
                  <select
                    className="w-full p-2 border rounded text-sm"
                    value={editForm.status}
                    onChange={(e) => setEditForm({ ...editForm, status: e.target.value })}
                    data-testid="edit-status"
                  >
                    <option value="draft">Draft</option>
                    <option value="scheduled">Scheduled</option>
                  </select>
                )}
                <div className="flex gap-2 pt-2">
                  <Button variant="outline" onClick={() => setEditingPost(null)} className="flex-1" data-testid="edit-cancel">
                    Cancel
                  </Button>
                  <Button
                    onClick={saveEdit}
                    className="flex-1 text-white"
                    style={{ background: theme.primary }}
                    data-testid="edit-save"
                  >Save changes</Button>
                </div>
              </div>
            )}
          </DialogContent>
        </Dialog>
      </CardContent>
    </Card>
  );
};
