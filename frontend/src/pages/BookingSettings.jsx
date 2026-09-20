import React, { useState, useEffect } from 'react';
import { Settings as SettingsIcon, Save, Clock, Users, CalendarDays, Plus, Trash2, ShieldAlert } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Badge } from '../components/ui/badge';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs';
import { useTheme } from '../contexts/ThemeContext';
import { reservationFeaturesAPI, reservationsAPI } from '../services/api';
import { toast } from 'sonner';

const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

function newTier(minGuests) {
  return {
    id: `tier-${Date.now()}-${Math.floor(Math.random() * 1000)}`,
    minGuests, maxGuests: null, label: '', requiresExperience: false,
    allowedExperienceIds: [], requireDeposit: false, requirePreOrder: false, requireApproval: false,
  };
}

export default function BookingSettings() {
  const { theme } = useTheme();
  const [tab, setTab] = useState('rules');
  const [rules, setRules] = useState(null);
  const [schedule, setSchedule] = useState([]);
  const [experiences, setExperiences] = useState([]);
  const [cancellationPolicy, setCancellationPolicy] = useState(null);

  useEffect(() => {
    reservationFeaturesAPI.getBookingRules().then(r => setRules(r.data)).catch(() => {});
    reservationFeaturesAPI.getBookingSchedule().then(r => setSchedule(r.data)).catch(() => {});
    reservationFeaturesAPI.getExperiences().then(r => setExperiences(r.data)).catch(() => {});
    reservationsAPI.getCancellationPolicy().then(r => setCancellationPolicy(r.data)).catch(() => {});
  }, []);

  const saveCancellationPolicy = async () => {
    try {
      await reservationsAPI.updateCancellationPolicy({ cutoffHours: cancellationPolicy.cutoffHours });
      toast.success('Cancellation policy saved');
    } catch { toast.error('Failed'); }
  };

  const saveRules = async () => {
    // Basic tier sanity check before it ever hits the server — overlapping
    // or reversed ranges are confusing for an owner to reason about and
    // easy to catch here, though the engine itself just uses first-match
    // order so a bad config degrades rather than crashes bookings.
    const tiers = rules.sizeTiers || [];
    for (const t of tiers) {
      if (t.maxGuests != null && Number(t.maxGuests) < Number(t.minGuests)) {
        toast.error(`Tier "${t.label || t.id}": max guests can't be less than min guests`);
        return;
      }
    }
    try { await reservationFeaturesAPI.saveBookingRules(rules); toast.success('Booking rules saved'); } catch { toast.error('Failed'); }
  };

  const saveSchedule = async () => {
    try { await reservationFeaturesAPI.saveBookingSchedule(schedule); toast.success('Schedule saved'); } catch { toast.error('Failed'); }
  };

  const updateShift = (idx, field, value) => {
    const s = [...schedule]; s[idx] = { ...s[idx], [field]: value }; setSchedule(s);
  };

  const addShift = () => {
    setSchedule([...schedule, { id: '', name: 'New Shift', startTime: '12:00', endTime: '15:00', interval: 30, tables: [], enabled: true }]);
  };

  const tiers = rules?.sizeTiers || [];
  const updateTier = (idx, field, value) => {
    const next = [...tiers]; next[idx] = { ...next[idx], [field]: value };
    setRules({ ...rules, sizeTiers: next });
  };
  const addTier = () => {
    const lastMax = tiers.length ? tiers[tiers.length - 1].maxGuests : null;
    const suggestedMin = lastMax != null ? Number(lastMax) + 1 : (tiers.length ? undefined : 1);
    setRules({ ...rules, sizeTiers: [...tiers, newTier(suggestedMin ?? tiers.length + 1)] });
  };
  const removeTier = (idx) => {
    setRules({ ...rules, sizeTiers: tiers.filter((_, i) => i !== idx) });
  };
  const toggleTierExperience = (idx, expId) => {
    const t = tiers[idx];
    const has = (t.allowedExperienceIds || []).includes(expId);
    const next = has ? t.allowedExperienceIds.filter(id => id !== expId) : [...(t.allowedExperienceIds || []), expId];
    updateTier(idx, 'allowedExperienceIds', next);
  };
  const toggleBlockedWeekday = (day) => {
    const cur = rules.blockedWeekdays || [];
    const next = cur.includes(day) ? cur.filter(d => d !== day) : [...cur, day];
    setRules({ ...rules, blockedWeekdays: next });
  };

  return (
    <div className="space-y-6" data-testid="booking-settings-page">
      <div><h1 className="text-2xl font-bold" style={{ color: theme.text }}>Booking Settings & Rules</h1><p className="text-sm text-gray-500">Configure booking window, capacity, large-booking tiers, and shifts</p></div>

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="rules">Rules</TabsTrigger>
          <TabsTrigger value="capacity">Capacity</TabsTrigger>
          <TabsTrigger value="tiers">Booking Size Tiers</TabsTrigger>
          <TabsTrigger value="schedule">Schedule</TabsTrigger>
          <TabsTrigger value="cancellation">Cancellation Policy</TabsTrigger>
        </TabsList>

        {/* RULES */}
        <TabsContent value="rules" className="mt-4">
          {rules && (
            <Card><CardHeader><CardTitle className="text-sm flex items-center gap-2"><Clock size={16} /> Booking Window</CardTitle></CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div><label className="text-sm font-medium mb-1 block">Max Online Party Size</label><Input type="number" value={rules.maxOnlinePartySize} onChange={e => setRules({ ...rules, maxOnlinePartySize: parseInt(e.target.value) || 0 })} data-testid="max-party-size" /></div>
                <div><label className="text-sm font-medium mb-1 block">Max Advance Days</label><Input type="number" value={rules.maxAdvanceDays} onChange={e => setRules({ ...rules, maxAdvanceDays: parseInt(e.target.value) || 0 })} /></div>
                <div><label className="text-sm font-medium mb-1 block">Minimum Notice (hours)</label><Input type="number" step="0.5" value={rules.minAdvanceHours} onChange={e => setRules({ ...rules, minAdvanceHours: parseFloat(e.target.value) || 0 })} data-testid="min-advance-hours" /></div>
                <div><label className="text-sm font-medium mb-1 block">Booking Window (minutes)</label>
                  <select className="w-full p-2 border rounded-md text-sm" value={rules.bookingWindowMinutes} onChange={e => setRules({ ...rules, bookingWindowMinutes: parseInt(e.target.value) })} data-testid="booking-window">
                    <option value={30}>Every 30 minutes</option><option value={60}>Every 1 hour</option>
                  </select>
                </div>
                <div><label className="text-sm font-medium mb-1 block">Bookings Open (time)</label><Input type="time" value={rules.bookingOpenTime} onChange={e => setRules({ ...rules, bookingOpenTime: e.target.value })} /></div>
                <div><label className="text-sm font-medium mb-1 block">Bookings Close (time)</label><Input type="time" value={rules.bookingCloseTime} onChange={e => setRules({ ...rules, bookingCloseTime: e.target.value })} /></div>
                <div><label className="text-sm font-medium mb-1 block">Cancellation Window (hours)</label><Input type="number" value={rules.cancellationHours} onChange={e => setRules({ ...rules, cancellationHours: parseInt(e.target.value) || 0 })} /></div>
              </div>
              <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={rules.autoConfirm} onChange={e => setRules({ ...rules, autoConfirm: e.target.checked })} /> Auto-confirm bookings</label>
              <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={rules.allowSameDay} onChange={e => setRules({ ...rules, allowSameDay: e.target.checked })} data-testid="allow-same-day" /> Allow same-day bookings</label>
              <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={rules.requireDeposit} onChange={e => setRules({ ...rules, requireDeposit: e.target.checked })} /> Require deposit (standard bookings)</label>
              {rules.requireDeposit && <Input type="number" step="0.01" placeholder="Deposit amount ($)" value={rules.depositAmount} onChange={e => setRules({ ...rules, depositAmount: parseFloat(e.target.value) || 0 })} />}

              <div>
                <label className="text-sm font-medium mb-1 block">Blocked Days of the Week</label>
                <div className="flex flex-wrap gap-1.5">
                  {WEEKDAYS.map(d => (
                    <button key={d} type="button" onClick={() => toggleBlockedWeekday(d)}
                      className={`px-2.5 py-1 text-xs rounded-full font-medium ${(rules.blockedWeekdays || []).includes(d) ? 'bg-red-600 text-white' : 'bg-gray-100 text-gray-600'}`}>
                      {d.slice(0, 3)}
                    </button>
                  ))}
                </div>
              </div>

              <Button style={{ backgroundColor: theme.primary }} onClick={saveRules} data-testid="save-rules-btn"><Save size={16} className="mr-1" /> Save Rules</Button>
            </CardContent></Card>
          )}
        </TabsContent>

        {/* CAPACITY */}
        <TabsContent value="capacity" className="mt-4">
          {rules && (
            <Card><CardHeader><CardTitle className="text-sm flex items-center gap-2"><Users size={16} /> Capacity</CardTitle></CardHeader>
            <CardContent className="space-y-4">
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={rules.enforceCapacity} onChange={e => setRules({ ...rules, enforceCapacity: e.target.checked })} data-testid="enforce-capacity" />
                Enforce capacity limits (blocks a booking once a slot is full, instead of just warning staff)
              </label>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="text-sm font-medium mb-1 block">Max Covers Per Slot</label>
                  <Input type="number" min="0" placeholder="0 = derive from floor plan" value={rules.maxCoversPerSlot}
                    onChange={e => setRules({ ...rules, maxCoversPerSlot: parseInt(e.target.value) || 0 })} data-testid="max-covers-per-slot" />
                  <p className="text-xs text-gray-500 mt-1">0 uses the sum of your floor plan's table capacity instead of a fixed number.</p>
                </div>
                <div>
                  <label className="text-sm font-medium mb-1 block">Slot Window (± minutes)</label>
                  <Input type="number" min="5" value={rules.slotBufferMinutes} onChange={e => setRules({ ...rules, slotBufferMinutes: parseInt(e.target.value) || 30 })} />
                  <p className="text-xs text-gray-500 mt-1">Bookings within this many minutes of each other count against the same slot's capacity.</p>
                </div>
                <div>
                  <label className="text-sm font-medium mb-1 block">Max Large Bookings Per Session</label>
                  <Input type="number" min="0" placeholder="0 = unlimited" value={rules.maxLargeBookingsPerSession}
                    onChange={e => setRules({ ...rules, maxLargeBookingsPerSession: parseInt(e.target.value) || 0 })} data-testid="max-large-per-session" />
                </div>
              </div>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={rules.capacityBySession} onChange={e => setRules({ ...rules, capacityBySession: e.target.checked })} />
                Track large-booking limits per shift/session (uses the shifts defined under Schedule)
              </label>
              <Button style={{ backgroundColor: theme.primary }} onClick={saveRules}><Save size={16} className="mr-1" /> Save Capacity Settings</Button>
            </CardContent></Card>
          )}
        </TabsContent>

        {/* SIZE TIERS */}
        <TabsContent value="tiers" className="mt-4">
          {rules && (
            <Card>
              <CardHeader className="flex flex-row items-center justify-between">
                <CardTitle className="text-sm flex items-center gap-2"><ShieldAlert size={16} /> Booking Size Tiers</CardTitle>
                <Button size="sm" variant="outline" onClick={addTier} data-testid="add-tier-btn"><Plus size={14} className="mr-1" /> Add Tier</Button>
              </CardHeader>
              <CardContent className="space-y-4">
                <p className="text-xs text-gray-500">
                  Define party-size ranges and what each requires. E.g. 1–6 guests = normal à la carte;
                  7–12 = Set Menu required; 13+ = Private Dining. Leave empty for no restrictions.
                  A tier that "Requires Experience" blocks à la carte for that party size — the customer
                  cannot confirm without picking one of the allowed menus/experiences.
                </p>
                {tiers.length === 0 && (
                  <div className="text-center py-8 text-gray-400 text-sm border-2 border-dashed rounded-lg">
                    No tiers configured — every party size books normally with no restrictions.
                  </div>
                )}
                {tiers.map((t, idx) => (
                  <div key={t.id} className="p-4 border rounded-lg space-y-3" data-testid={`tier-${idx}`}>
                    <div className="grid grid-cols-4 gap-3 items-end">
                      <div><label className="text-xs text-gray-500">Min Guests</label>
                        <Input type="number" min="1" className="h-8 text-sm" value={t.minGuests}
                          onChange={e => updateTier(idx, 'minGuests', parseInt(e.target.value) || 1)} data-testid={`tier-${idx}-min`} />
                      </div>
                      <div><label className="text-xs text-gray-500">Max Guests</label>
                        <Input type="number" min="1" className="h-8 text-sm" placeholder="No limit" value={t.maxGuests ?? ''}
                          onChange={e => updateTier(idx, 'maxGuests', e.target.value === '' ? null : parseInt(e.target.value))} data-testid={`tier-${idx}-max`} />
                      </div>
                      <div className="col-span-2"><label className="text-xs text-gray-500">Label</label>
                        <Input className="h-8 text-sm" placeholder="e.g. Set Menu" value={t.label}
                          onChange={e => updateTier(idx, 'label', e.target.value)} data-testid={`tier-${idx}-label`} />
                      </div>
                    </div>
                    <div className="flex flex-wrap gap-4">
                      <label className="flex items-center gap-1.5 text-xs"><input type="checkbox" checked={t.requiresExperience} onChange={e => updateTier(idx, 'requiresExperience', e.target.checked)} data-testid={`tier-${idx}-requires-experience`} /> Requires Experience/Set Menu</label>
                      <label className="flex items-center gap-1.5 text-xs"><input type="checkbox" checked={t.requireDeposit} onChange={e => updateTier(idx, 'requireDeposit', e.target.checked)} /> Require Deposit</label>
                      <label className="flex items-center gap-1.5 text-xs"><input type="checkbox" checked={t.requirePreOrder} onChange={e => updateTier(idx, 'requirePreOrder', e.target.checked)} /> Require Pre-Order</label>
                      <label className="flex items-center gap-1.5 text-xs"><input type="checkbox" checked={t.requireApproval} onChange={e => updateTier(idx, 'requireApproval', e.target.checked)} data-testid={`tier-${idx}-requires-approval`} /> Require Owner/Manager Approval</label>
                    </div>
                    {t.requiresExperience && (
                      <div>
                        <label className="text-xs text-gray-500 mb-1 block">Allowed Experiences (none checked = any active experience)</label>
                        <div className="flex flex-wrap gap-1.5">
                          {experiences.length === 0 && <span className="text-xs text-gray-400">No experiences created yet — see Marketing &gt; Experiences.</span>}
                          {experiences.map(exp => (
                            <button key={exp.id} type="button" onClick={() => toggleTierExperience(idx, exp.id)}
                              className={`px-2.5 py-1 text-xs rounded-full font-medium ${(t.allowedExperienceIds || []).includes(exp.id) ? 'bg-gray-900 text-white' : 'bg-gray-100 text-gray-600'}`}>
                              {exp.name}
                            </button>
                          ))}
                        </div>
                      </div>
                    )}
                    <div className="flex justify-between items-center pt-1">
                      <Badge variant="outline" className="text-[10px]">
                        {t.minGuests}{t.maxGuests ? `–${t.maxGuests}` : '+'} guests
                      </Badge>
                      <Button variant="ghost" size="sm" className="text-red-500" onClick={() => removeTier(idx)} data-testid={`tier-${idx}-remove`}><Trash2 size={14} /></Button>
                    </div>
                  </div>
                ))}
                <Button style={{ backgroundColor: theme.primary }} onClick={saveRules} data-testid="save-tiers-btn"><Save size={16} className="mr-1" /> Save Tiers</Button>
              </CardContent>
            </Card>
          )}
        </TabsContent>

        {/* SCHEDULE */}
        <TabsContent value="schedule" className="mt-4">
          <Card><CardHeader><CardTitle className="text-sm flex items-center justify-between">Booking Shifts<Button size="sm" variant="outline" onClick={addShift} data-testid="add-shift-btn"><CalendarDays size={14} className="mr-1" /> Add Shift</Button></CardTitle></CardHeader>
          <CardContent className="space-y-4">
            {schedule.map((shift, i) => (
              <div key={shift.id || i} className="p-4 border rounded-lg space-y-3" data-testid={`shift-${i}`}>
                <div className="grid grid-cols-4 gap-3">
                  <div><label className="text-xs text-gray-500">Shift Name</label><Input className="h-8 text-sm" value={shift.name} onChange={e => updateShift(i, 'name', e.target.value)} /></div>
                  <div><label className="text-xs text-gray-500">Start</label><Input type="time" className="h-8 text-sm" value={shift.startTime} onChange={e => updateShift(i, 'startTime', e.target.value)} /></div>
                  <div><label className="text-xs text-gray-500">End</label><Input type="time" className="h-8 text-sm" value={shift.endTime} onChange={e => updateShift(i, 'endTime', e.target.value)} /></div>
                  <div><label className="text-xs text-gray-500">Interval</label>
                    <select className="w-full h-8 text-sm border rounded px-2" value={shift.interval} onChange={e => updateShift(i, 'interval', parseInt(e.target.value))}>
                      <option value={30}>30 min</option><option value={60}>1 hour</option>
                    </select>
                  </div>
                </div>
                <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={shift.enabled} onChange={e => updateShift(i, 'enabled', e.target.checked)} /> Enabled</label>
              </div>
            ))}
            <Button style={{ backgroundColor: theme.primary }} onClick={saveSchedule} data-testid="save-schedule-btn"><Save size={16} className="mr-1" /> Save Schedule</Button>
          </CardContent></Card>
        </TabsContent>

        {/* CANCELLATION POLICY */}
        <TabsContent value="cancellation" className="mt-4">
          {cancellationPolicy && (
            <Card><CardHeader><CardTitle className="text-sm flex items-center gap-2"><ShieldAlert size={16} /> Cancellation Policy</CardTitle></CardHeader>
            <CardContent className="space-y-4">
              <p className="text-sm text-gray-500">
                A booking cancelled at least this many hours before its own time gets any collected deposit
                refunded in full. Cancel later than that and the deposit is kept as a cancellation fee instead —
                the same real money capture as a no-show, just triggered by a late cancellation.
              </p>
              <div className="max-w-xs">
                <label className="text-sm font-medium mb-1 block">Free Cancellation Cutoff (hours before booking)</label>
                <Input type="number" min={0} step="0.5" value={cancellationPolicy.cutoffHours}
                  onChange={e => setCancellationPolicy({ ...cancellationPolicy, cutoffHours: parseFloat(e.target.value) || 0 })}
                  data-testid="cancellation-cutoff-hours" />
              </div>
              <Button style={{ backgroundColor: theme.primary }} onClick={saveCancellationPolicy} data-testid="save-cancellation-policy-btn">
                <Save size={16} className="mr-1" /> Save Policy
              </Button>
            </CardContent></Card>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}
