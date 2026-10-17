import React, { useEffect, useMemo, useState } from 'react';
import { CalendarClock, Plus, Check, X, UserX, Scissors, NotebookPen, Search } from 'lucide-react';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Card, CardContent } from '../components/ui/card';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '../components/ui/dialog';
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from '../components/ui/select';
import { Badge } from '../components/ui/badge';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '../components/ui/tabs';
import { useTheme } from '../contexts/ThemeContext';
import { appointmentsAPI, servicesAPI, staffRosterAPI, clientIntakeAPI } from '../services/api';
import { toast } from 'sonner';
import { DialogService } from '../platform';

const todayISO = () => new Date().toISOString().slice(0, 10);

const BLANK_APPT = { customerName: '', customerPhone: '', staffId: '', serviceId: '', date: todayISO(), time: '', notes: '', depositRequired: '' };
const BLANK_SERVICE = { name: '', category: '', durationMinutes: 30, price: '' };
const BLANK_INTAKE = { customerName: '', customerPhone: '', allergies: '', skinType: '', notes: '' };

export default function Appointments() {
  const { theme } = useTheme();
  const [tab, setTab] = useState('book');

  const [date, setDate] = useState(todayISO());
  const [appointments, setAppointments] = useState([]);
  const [services, setServices] = useState([]);
  const [staff, setStaff] = useState([]);
  const [loading, setLoading] = useState(true);

  const [showBook, setShowBook] = useState(false);
  const [form, setForm] = useState(BLANK_APPT);
  const [slots, setSlots] = useState([]);
  const [slotsLoading, setSlotsLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [busyId, setBusyId] = useState(null);

  const [showService, setShowService] = useState(false);
  const [serviceForm, setServiceForm] = useState(BLANK_SERVICE);
  const [savingService, setSavingService] = useState(false);

  const load = () => {
    setLoading(true);
    Promise.all([
      appointmentsAPI.list({ date }),
      servicesAPI.list(),
      staffRosterAPI.list(),
    ]).then(([a, s, st]) => {
      setAppointments(a.data || []);
      setServices(s.data || []);
      setStaff((st.data || []).filter(u => u.status === 'active'));
    }).catch(() => toast.error('Failed to load appointments')).finally(() => setLoading(false));
  };
  useEffect(load, [date]);

  useEffect(() => {
    if (!form.staffId || !form.serviceId || !form.date) { setSlots([]); return; }
    setSlotsLoading(true);
    appointmentsAPI.availability({ staffId: form.staffId, serviceId: form.serviceId, date: form.date })
      .then(r => setSlots(r.data?.slots || []))
      .catch(() => setSlots([]))
      .finally(() => setSlotsLoading(false));
  }, [form.staffId, form.serviceId, form.date]);

  const openBook = () => { setForm({ ...BLANK_APPT, date }); setShowBook(true); };

  const bookAppointment = async () => {
    if (!form.customerName || !form.staffId || !form.serviceId || !form.date || !form.time) {
      toast.error('Fill in the client, staff member, service, and a time'); return;
    }
    setSaving(true);
    try {
      await appointmentsAPI.create({ ...form, depositRequired: parseFloat(form.depositRequired) || 0 });
      toast.success('Appointment booked');
      setShowBook(false);
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Failed to book appointment');
    } finally { setSaving(false); }
  };

  const transition = async (appt, action) => {
    if (action === 'no_show') {
      const raw = await DialogService.prompt(`No-show fee for ${appt.customerName}? (leave blank for $0)`, appt.depositRequired || '');
      if (raw === null) return; // cancelled the prompt
      setBusyId(appt.id);
      try {
        await appointmentsAPI.noShow(appt.id, parseFloat(raw) || 0);
        load();
      } catch (e) { toast.error(e.response?.data?.detail || 'Failed to mark no-show'); }
      finally { setBusyId(null); }
      return;
    }
    setBusyId(appt.id);
    try {
      if (action === 'complete') await appointmentsAPI.complete(appt.id);
      else await appointmentsAPI.cancel(appt.id);
      load();
    } catch (e) { toast.error(e.response?.data?.detail || 'Failed to update appointment'); }
    finally { setBusyId(null); }
  };

  const toggleDepositPaid = async (appt) => {
    setBusyId(appt.id);
    try {
      await appointmentsAPI.update(appt.id, { depositPaid: !appt.depositPaid });
      load();
    } catch { toast.error('Failed to update deposit status'); }
    finally { setBusyId(null); }
  };

  const openAddService = () => { setServiceForm(BLANK_SERVICE); setShowService(true); };
  const saveService = async () => {
    if (!serviceForm.name.trim()) { toast.error('Give the service a name'); return; }
    setSavingService(true);
    try {
      await servicesAPI.create({
        ...serviceForm,
        durationMinutes: parseInt(serviceForm.durationMinutes) || 30,
        price: parseFloat(serviceForm.price) || 0,
      });
      toast.success('Service added');
      setShowService(false);
      load();
    } catch (e) { toast.error(e.response?.data?.detail || 'Failed to save service'); }
    finally { setSavingService(false); }
  };
  const removeService = async (svc) => {
    if (!await DialogService.confirm(`Remove "${svc.name}" from the catalog?`)) return;
    try { await servicesAPI.delete(svc.id); toast.success('Service removed'); load(); }
    catch { toast.error('Failed to remove service'); }
  };

  // ---- Client intake / consultation notes ----
  const [lookupPhone, setLookupPhone] = useState('');
  const [intakeHistory, setIntakeHistory] = useState(null); // null = not searched yet
  const [intakeLoading, setIntakeLoading] = useState(false);
  const [intakeForm, setIntakeForm] = useState(BLANK_INTAKE);
  const [savingIntake, setSavingIntake] = useState(false);

  const searchIntake = async () => {
    if (!lookupPhone.trim()) { toast.error('Enter a phone number to search'); return; }
    setIntakeLoading(true);
    try {
      const r = await clientIntakeAPI.list({ customerPhone: lookupPhone.trim() });
      setIntakeHistory(r.data || []);
      setIntakeForm({ ...BLANK_INTAKE, customerPhone: lookupPhone.trim(), customerName: r.data?.[0]?.customerName || '' });
    } catch { toast.error('Search failed'); }
    finally { setIntakeLoading(false); }
  };

  const saveIntakeNote = async () => {
    if (!intakeForm.customerName.trim() || !intakeForm.customerPhone.trim()) {
      toast.error('Client name and phone are required'); return;
    }
    setSavingIntake(true);
    try {
      await clientIntakeAPI.create(intakeForm);
      toast.success('Note saved');
      searchIntake();
    } catch (e) { toast.error(e.response?.data?.detail || 'Failed to save note'); }
    finally { setSavingIntake(false); }
  };

  const statusBadge = (status) => {
    if (status === 'confirmed') return <Badge className="bg-blue-100 text-blue-700 hover:bg-blue-100">Confirmed</Badge>;
    if (status === 'completed') return <Badge className="bg-emerald-100 text-emerald-700 hover:bg-emerald-100">Completed</Badge>;
    if (status === 'no_show') return <Badge className="bg-red-100 text-red-700 hover:bg-red-100">No-Show</Badge>;
    return <Badge variant="secondary">Cancelled</Badge>;
  };

  const eligibleStaff = useMemo(() => {
    const svc = services.find(s => s.id === form.serviceId);
    if (!svc || !svc.staffIds || svc.staffIds.length === 0) return staff;
    return staff.filter(s => svc.staffIds.includes(s.id));
  }, [services, form.serviceId, staff]);

  return (
    <div className="space-y-6" data-testid="appointments-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2" style={{ color: theme.text }}>
            <CalendarClock size={24} /> Appointments
          </h1>
          <p className="text-sm text-gray-500">Book a service with a specific staff member — no two clients ever land on the same person at once.</p>
        </div>
      </div>

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="book" data-testid="tab-book">Book</TabsTrigger>
          <TabsTrigger value="services" data-testid="tab-services">Services</TabsTrigger>
          <TabsTrigger value="notes" data-testid="tab-notes">Client Notes</TabsTrigger>
        </TabsList>

        <TabsContent value="book" className="space-y-4 pt-4">
          <div className="flex items-center justify-between">
            <Input type="date" value={date} onChange={e => setDate(e.target.value)} className="w-44" data-testid="appointments-date-input" />
            <Button onClick={openBook} data-testid="new-appointment-btn">
              <Plus size={14} className="mr-1.5" /> New Appointment
            </Button>
          </div>

          {loading ? (
            <p className="text-sm text-gray-400 text-center py-12">Loading…</p>
          ) : appointments.length === 0 ? (
            <Card><CardContent className="p-12 text-center text-gray-400">No appointments this day.</CardContent></Card>
          ) : (
            <div className="space-y-2">
              {appointments.map(a => (
                <Card key={a.id} data-testid={`appointment-row-${a.id}`}>
                  <CardContent className="p-4 flex items-center justify-between gap-4">
                    <div>
                      <p className="font-medium text-sm">{a.time} · {a.serviceName} with {a.staffName}</p>
                      <p className="text-xs text-gray-500">{a.customerName}{a.customerPhone ? ` · ${a.customerPhone}` : ''} · {a.durationMinutes} min · ${Number(a.price).toFixed(2)}</p>
                      {a.notes && <p className="text-xs text-gray-400 italic mt-0.5">{a.notes}</p>}
                      {a.depositRequired > 0 && (
                        <button onClick={() => toggleDepositPaid(a)} disabled={busyId === a.id} className="mt-1" data-testid={`deposit-toggle-${a.id}`}>
                          <Badge variant="outline" className={a.depositPaid ? 'text-emerald-600 border-emerald-300' : 'text-amber-600 border-amber-300'}>
                            Deposit ${Number(a.depositRequired).toFixed(2)} {a.depositPaid ? '· paid' : '· unpaid, tap to mark paid'}
                          </Badge>
                        </button>
                      )}
                      {a.status === 'no_show' && a.noShowFee > 0 && (
                        <p className="text-xs text-red-500 mt-1">No-show fee: ${Number(a.noShowFee).toFixed(2)}</p>
                      )}
                    </div>
                    <div className="flex items-center gap-2">
                      {statusBadge(a.status)}
                      {a.status === 'confirmed' && (
                        <>
                          <Button size="sm" variant="outline" disabled={busyId === a.id} onClick={() => transition(a, 'complete')} data-testid={`complete-appt-${a.id}`}>
                            <Check size={13} className="mr-1" /> Complete
                          </Button>
                          <Button size="sm" variant="ghost" disabled={busyId === a.id} onClick={() => transition(a, 'no_show')} data-testid={`noshow-appt-${a.id}`} title="No-show">
                            <UserX size={13} />
                          </Button>
                          <Button size="sm" variant="ghost" disabled={busyId === a.id} onClick={() => transition(a, 'cancel')} data-testid={`cancel-appt-${a.id}`}>
                            <X size={13} />
                          </Button>
                        </>
                      )}
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </TabsContent>

        <TabsContent value="services" className="space-y-4 pt-4">
          <div className="flex justify-end">
            <Button onClick={openAddService} data-testid="new-service-btn">
              <Plus size={14} className="mr-1.5" /> New Service
            </Button>
          </div>
          {services.length === 0 ? (
            <Card><CardContent className="p-12 text-center text-gray-400">No services in the catalog yet.</CardContent></Card>
          ) : (
            <div className="grid gap-3 md:grid-cols-2">
              {services.map(s => (
                <Card key={s.id} data-testid={`service-row-${s.id}`}>
                  <CardContent className="p-4 flex items-start justify-between gap-3">
                    <div className="flex items-start gap-3">
                      <Scissors size={16} className="text-gray-400 mt-0.5" />
                      <div>
                        <p className="font-medium text-sm">{s.name}</p>
                        <p className="text-xs text-gray-500">{s.category ? `${s.category} · ` : ''}{s.durationMinutes} min · ${Number(s.price).toFixed(2)}</p>
                        {s.description && <p className="text-xs text-gray-400 mt-0.5">{s.description}</p>}
                      </div>
                    </div>
                    <button onClick={() => removeService(s)} className="text-gray-400 hover:text-red-500" data-testid={`remove-service-${s.id}`}>
                      <X size={14} />
                    </button>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </TabsContent>

        <TabsContent value="notes" className="space-y-4 pt-4">
          <div className="flex gap-2">
            <Input placeholder="Search by client phone…" value={lookupPhone} onChange={e => setLookupPhone(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && searchIntake()} data-testid="intake-search-input" />
            <Button variant="outline" onClick={searchIntake} disabled={intakeLoading} data-testid="intake-search-btn">
              <Search size={14} className="mr-1.5" /> Search
            </Button>
          </div>

          {intakeHistory !== null && (
            <>
              {intakeHistory.length === 0 ? (
                <p className="text-xs text-gray-400">No notes on file for this number yet — add the first one below.</p>
              ) : (
                <div className="space-y-2">
                  {intakeHistory.map(n => (
                    <Card key={n.id} data-testid={`intake-note-${n.id}`}>
                      <CardContent className="p-3 text-sm">
                        <div className="flex items-center justify-between">
                          <p className="font-medium">{n.customerName}</p>
                          <span className="text-[11px] text-gray-400">{new Date(n.createdAt).toLocaleDateString()} · {n.staffName}</span>
                        </div>
                        {(n.allergies || n.skinType) && (
                          <p className="text-xs text-amber-700 mt-1">
                            {n.allergies && `Allergies: ${n.allergies}`}{n.allergies && n.skinType ? ' · ' : ''}{n.skinType && `Skin: ${n.skinType}`}
                          </p>
                        )}
                        {n.notes && <p className="text-xs text-gray-600 mt-1">{n.notes}</p>}
                      </CardContent>
                    </Card>
                  ))}
                </div>
              )}

              <Card className="bg-gray-50">
                <CardContent className="p-3 space-y-2">
                  <p className="text-xs font-medium text-gray-500 flex items-center gap-1.5"><NotebookPen size={13} /> Add a note for this visit</p>
                  <Input placeholder="Client name" value={intakeForm.customerName} onChange={e => setIntakeForm({ ...intakeForm, customerName: e.target.value })} data-testid="intake-name-input" />
                  <div className="grid grid-cols-2 gap-2">
                    <Input placeholder="Allergies" value={intakeForm.allergies} onChange={e => setIntakeForm({ ...intakeForm, allergies: e.target.value })} data-testid="intake-allergies-input" />
                    <Input placeholder="Skin/hair type" value={intakeForm.skinType} onChange={e => setIntakeForm({ ...intakeForm, skinType: e.target.value })} data-testid="intake-skintype-input" />
                  </div>
                  <Input placeholder="Consultation notes for this visit" value={intakeForm.notes} onChange={e => setIntakeForm({ ...intakeForm, notes: e.target.value })} data-testid="intake-notes-input" />
                  <Button size="sm" className="w-full" onClick={saveIntakeNote} disabled={savingIntake} data-testid="save-intake-btn">
                    {savingIntake ? 'Saving…' : 'Save Note'}
                  </Button>
                </CardContent>
              </Card>
            </>
          )}
        </TabsContent>
      </Tabs>

      <Dialog open={showBook} onOpenChange={setShowBook}>
        <DialogContent data-testid="book-appointment-dialog">
          <DialogHeader><DialogTitle>New Appointment</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <Input placeholder="Client name" value={form.customerName} onChange={e => setForm({ ...form, customerName: e.target.value })} data-testid="appt-customer-input" />
            <Input placeholder="Phone (optional)" value={form.customerPhone} onChange={e => setForm({ ...form, customerPhone: e.target.value })} data-testid="appt-phone-input" />
            <div>
              <label className="text-xs font-medium text-gray-500 mb-1 block">Service</label>
              <Select value={form.serviceId} onValueChange={v => setForm({ ...form, serviceId: v, staffId: '', time: '' })}>
                <SelectTrigger data-testid="appt-service-select"><SelectValue placeholder="Choose a service…" /></SelectTrigger>
                <SelectContent>
                  {services.map(s => <SelectItem key={s.id} value={s.id}>{s.name} ({s.durationMinutes} min, ${Number(s.price).toFixed(0)})</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div>
              <label className="text-xs font-medium text-gray-500 mb-1 block">Staff</label>
              <Select value={form.staffId} onValueChange={v => setForm({ ...form, staffId: v, time: '' })} disabled={!form.serviceId}>
                <SelectTrigger data-testid="appt-staff-select"><SelectValue placeholder="Choose a staff member…" /></SelectTrigger>
                <SelectContent>
                  {eligibleStaff.map(s => <SelectItem key={s.id} value={s.id}>{s.name}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <Input type="date" value={form.date} onChange={e => setForm({ ...form, date: e.target.value, time: '' })} data-testid="appt-date-input" />
            {form.staffId && form.serviceId && (
              <div>
                <label className="text-xs font-medium text-gray-500 mb-1 block">Time</label>
                {slotsLoading ? (
                  <p className="text-xs text-gray-400">Checking availability…</p>
                ) : slots.length === 0 ? (
                  <p className="text-xs text-gray-400">No open slots this day.</p>
                ) : (
                  <div className="flex flex-wrap gap-1.5 max-h-32 overflow-y-auto" data-testid="appt-slots">
                    {slots.map(t => (
                      <button key={t} type="button" onClick={() => setForm({ ...form, time: t })}
                        className={`px-2.5 py-1 text-xs rounded-full font-medium border ${form.time === t ? 'text-white border-transparent' : 'bg-white text-gray-700 border-gray-200 hover:border-gray-400'}`}
                        style={form.time === t ? { background: theme.primary } : {}}
                        data-testid={`slot-${t}`}>
                        {t}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
            <Input type="number" step="0.01" placeholder="Deposit required (optional)" value={form.depositRequired} onChange={e => setForm({ ...form, depositRequired: e.target.value })} data-testid="appt-deposit-input" />
            <Input placeholder="Notes (optional)" value={form.notes} onChange={e => setForm({ ...form, notes: e.target.value })} data-testid="appt-notes-input" />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowBook(false)}>Cancel</Button>
            <Button onClick={bookAppointment} disabled={saving || !form.time} data-testid="save-appointment-btn">{saving ? 'Booking…' : 'Book Appointment'}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={showService} onOpenChange={setShowService}>
        <DialogContent data-testid="add-service-dialog">
          <DialogHeader><DialogTitle>New Service</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <Input placeholder="Service name (e.g. Haircut)" value={serviceForm.name} onChange={e => setServiceForm({ ...serviceForm, name: e.target.value })} data-testid="service-name-input" />
            <Input placeholder="Category (optional)" value={serviceForm.category} onChange={e => setServiceForm({ ...serviceForm, category: e.target.value })} data-testid="service-category-input" />
            <div className="grid grid-cols-2 gap-3">
              <Input type="number" placeholder="Duration (min)" value={serviceForm.durationMinutes} onChange={e => setServiceForm({ ...serviceForm, durationMinutes: e.target.value })} data-testid="service-duration-input" />
              <Input type="number" step="0.01" placeholder="Price" value={serviceForm.price} onChange={e => setServiceForm({ ...serviceForm, price: e.target.value })} data-testid="service-price-input" />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowService(false)}>Cancel</Button>
            <Button onClick={saveService} disabled={savingService} data-testid="save-service-btn">{savingService ? 'Saving…' : 'Add Service'}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
