import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  CalendarDays, Clock, Users, MapPin, ChevronRight, Check,
  Phone, Mail, User, UtensilsCrossed, Music, Ticket, Star, ClipboardList, ShieldCheck, X
} from 'lucide-react';
import { Card, CardContent } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Badge } from '../components/ui/badge';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue
} from '../components/ui/select';
import { publicAPI, reservationFeaturesAPI } from '../services/api';
import { useGuestSession } from '../hooks/useGuestSession';
import { matchTier } from '../lib/bookingTiers';
import { toast } from 'sonner';

const STEPS = ['select', 'details', 'confirmed'];
const EVENT_ICONS = { dining: UtensilsCrossed, wine_pairing: Star, cooking_class: UtensilsCrossed, live_music: Music, private: Ticket };

export default function BookingPortal() {
  const navigate = useNavigate();
  const business = new URLSearchParams(window.location.search).get("business");
  const businessQuery = business ? `?business=${encodeURIComponent(business)}` : '';
  const [tab, setTab] = useState('reserve'); // reserve, waitlist, events, menu
  const [step, setStep] = useState('select');
  const [menu, setMenu] = useState([]);
  const [events, setEvents] = useState([]);
  const [slots, setSlots] = useState([]);
  const [form, setForm] = useState({
    guestName: '', guestPhone: '', guestEmail: '',
    partySize: 2, date: new Date().toISOString().split('T')[0],
    time: '', duration: 90, specialRequests: '', experienceId: null,
  });
  const [waitlistForm, setWaitlistForm] = useState({ guestName: '', guestPhone: '', partySize: 2, preferences: '' });
  const [confirmData, setConfirmData] = useState(null);
  const [bookingRules, setBookingRules] = useState(null);
  const [experiences, setExperiences] = useState([]);

  useEffect(() => {
    reservationFeaturesAPI.getBookingRules(business).then(r => setBookingRules(r.data)).catch(() => {});
    reservationFeaturesAPI.getExperiences(business).then(r => setExperiences(r.data || [])).catch(() => {});
  }, []);

  const matchedTier = matchTier(bookingRules?.sizeTiers, form.partySize);
  const requiresExperience = !!matchedTier?.requiresExperience;
  const tierExperiences = requiresExperience
    ? (matchedTier.allowedExperienceIds?.length
        ? experiences.filter(e => matchedTier.allowedExperienceIds.includes(e.id))
        : experiences.filter(e => e.active !== false))
    : [];

  const guest = useGuestSession(business);
  const [verifyPhone, setVerifyPhone] = useState('');
  const [verifyCode, setVerifyCode] = useState('');
  const [verifyStep, setVerifyStep] = useState('phone'); // phone, code
  const [verifyBusy, setVerifyBusy] = useState(false);

  // Prefill whichever form is in view once a returning guest verifies —
  // only fills blanks, never clobbers something already typed this visit.
  useEffect(() => {
    if (!guest.profile) return;
    setForm(f => ({
      ...f,
      guestName: f.guestName || guest.profile.name || '',
      guestPhone: f.guestPhone || guest.profile.phone || '',
      guestEmail: f.guestEmail || guest.profile.email || '',
    }));
    setWaitlistForm(f => ({
      ...f,
      guestName: f.guestName || guest.profile.name || '',
      guestPhone: f.guestPhone || guest.profile.phone || '',
    }));
  }, [guest.profile]);

  const sendVerifyCode = async () => {
    if (!verifyPhone.trim()) return toast.error('Enter your phone number');
    setVerifyBusy(true);
    try {
      await guest.requestCode(verifyPhone.trim());
      setVerifyStep('code');
      toast.success('Code sent — check your phone');
    } catch { toast.error('Failed to send code'); }
    finally { setVerifyBusy(false); }
  };

  const confirmVerifyCode = async () => {
    if (verifyCode.length !== 6) return;
    setVerifyBusy(true);
    try {
      await guest.verify(verifyPhone.trim(), verifyCode);
      toast.success('Verified — your details will prefill from here on');
      setVerifyStep('phone'); setVerifyPhone(''); setVerifyCode('');
    } catch (e) { toast.error(e?.response?.data?.detail || 'That code didn’t match'); }
    finally { setVerifyBusy(false); }
  };

  useEffect(() => {
    publicAPI.getMenu(business).then(r => setMenu(r.data.categories || [])).catch(() => {});
    publicAPI.getEvents(business).then(r => setEvents(r.data || [])).catch(() => {});
  }, []);

  useEffect(() => {
    if (form.date && form.partySize) {
      publicAPI.getAvailableSlots(form.date, form.partySize, business)
        .then(r => setSlots(r.data.slots || []))
        .catch(() => setSlots([]));
    }
  }, [form.date, form.partySize]);

  const handleBook = async () => {
    if (!form.guestName || !form.date || !form.time) { toast.error('Please fill in all required fields'); return; }
    // Client-side mirror of the same gate the server enforces — this is
    // UX only, not the actual restriction. Confirming with an unmet
    // requirement never reaches the server thinking it's fine; POST
    // /public/book re-checks and would 409 anyway.
    if (requiresExperience && !form.experienceId) {
      toast.error(
        `For parties of ${matchedTier.minGuests} or more, bookings are available with our `
        + `${matchedTier.label || 'Set Menu / Dining Experience'} only.`
      );
      return;
    }
    try {
      const res = await publicAPI.book(form, business);
      setConfirmData(res.data);
      setStep('confirmed');
      toast.success(res.data?.message || 'Reservation confirmed!');
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Booking failed. Please try again.');
    }
  };

  const handleJoinWaitlist = async () => {
    if (!waitlistForm.guestName) { toast.error('Name is required'); return; }
    try {
      const res = await publicAPI.joinWaitlist(waitlistForm, business);
      setConfirmData(res.data);
      setStep('confirmed');
      toast.success(`You're #${res.data.position} on the waitlist!`);
    } catch (e) { toast.error('Failed to join waitlist'); }
  };

  const reset = () => { setStep('select'); setConfirmData(null); setForm(f => ({ ...f, time: '' })); };

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-900 via-gray-800 to-gray-900" data-testid="booking-portal">
      {/* Header */}
      <div className="max-w-4xl mx-auto pt-10 pb-6 px-4">
        <div className="text-center">
          <h1 className="text-4xl font-bold text-white tracking-tight">NUA</h1>
        </div>

        {/* Passwordless guest verification — one phone check that prefills
            every form on this page (and, via the same shared token, online
            ordering) instead of re-typing name/phone/email each time. */}
        <div className="max-w-md mx-auto mt-5">
          {guest.profile ? (
            <div className="flex items-center justify-between gap-2 bg-white/10 border border-white/20 rounded-full px-4 py-2 text-sm text-white"
              data-testid="guest-session-verified-banner">
              <span className="flex items-center gap-2 truncate">
                <ShieldCheck size={14} className="text-emerald-400 flex-shrink-0" />
                {guest.profile.known ? `Welcome back, ${guest.profile.name}!` : `Verified as ${guest.profile.phone}`}
              </span>
              <button onClick={guest.clearSession} className="text-gray-400 hover:text-white flex-shrink-0" data-testid="guest-session-clear-btn">
                <X size={14} />
              </button>
            </div>
          ) : !guest.loading && (
            <div className="bg-white/10 border border-white/20 rounded-2xl p-3" data-testid="guest-session-verify-banner">
              {verifyStep === 'phone' ? (
                <div className="flex gap-2">
                  <Input placeholder="Verify your phone to skip re-typing your details"
                    value={verifyPhone} onChange={e => setVerifyPhone(e.target.value)}
                    className="bg-white/90 text-sm" data-testid="guest-session-phone-input" />
                  <Button size="sm" onClick={sendVerifyCode} disabled={verifyBusy} data-testid="guest-session-send-code-btn">
                    Verify
                  </Button>
                </div>
              ) : (
                <div className="flex gap-2">
                  <Input placeholder="6-digit code" value={verifyCode} maxLength={6}
                    onChange={e => setVerifyCode(e.target.value.replace(/\D/g, ''))}
                    className="bg-white/90 text-sm" data-testid="guest-session-code-input" />
                  <Button size="sm" onClick={confirmVerifyCode} disabled={verifyBusy || verifyCode.length !== 6}
                    data-testid="guest-session-confirm-code-btn">
                    Confirm
                  </Button>
                  <Button size="sm" variant="ghost" className="text-gray-300" onClick={() => setVerifyStep('phone')}>
                    Back
                  </Button>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Tab Navigation */}
        <div className="flex flex-wrap justify-center gap-2 mt-6 sm:mt-8">
          {[
            { id: 'reserve', label: 'Reserve', fullLabel: 'Reserve a Table', icon: CalendarDays },
            { id: 'waitlist', label: 'Waitlist', fullLabel: 'Join Waitlist', icon: ClipboardList },
            { id: 'events', label: 'Events', fullLabel: 'Events', icon: Ticket },
            { id: 'menu', label: 'Menu', fullLabel: 'View Menu', icon: UtensilsCrossed },
          ].map(t => (
            <button key={t.id} onClick={() => { setTab(t.id); reset(); }}
              className={`flex items-center gap-1.5 sm:gap-2 px-3 sm:px-5 py-2 sm:py-2.5 rounded-full text-xs sm:text-sm font-medium transition-all ${tab === t.id ? 'bg-white text-gray-900' : 'text-gray-400 hover:text-white hover:bg-white/10'}`}
              data-testid={`portal-tab-${t.id}`}>
              <t.icon size={14} className="sm:w-4 sm:h-4" /> <span className="hidden sm:inline">{t.fullLabel}</span><span className="sm:hidden">{t.label}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="max-w-2xl mx-auto px-4 pb-16">
        {/* RESERVE A TABLE */}
        {tab === 'reserve' && step !== 'confirmed' && (
          <Card className="border-0 shadow-2xl bg-white/95 backdrop-blur">
            <CardContent className="p-8">
              {step === 'select' && (
                <div className="space-y-6">
                  <h2 className="text-xl font-bold text-gray-900">Find a Table</h2>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    <div>
                      <label className="text-xs font-medium text-gray-500 mb-1.5 block">Date</label>
                      <Input type="date" value={form.date} onChange={e => setForm(f => ({ ...f, date: e.target.value }))}
                        min={new Date().toISOString().split('T')[0]} data-testid="portal-date" />
                    </div>
                    <div>
                      <label className="text-xs font-medium text-gray-500 mb-1.5 block">Party Size</label>
                      <Select value={String(form.partySize)} onValueChange={v => setForm(f => ({ ...f, partySize: parseInt(v), experienceId: null }))}>
                        <SelectTrigger data-testid="portal-party-size"><SelectValue /></SelectTrigger>
                        <SelectContent>
                          {[1, 2, 3, 4, 5, 6, 7, 8, 10, 12, 15, 20].map(n => (
                            <SelectItem key={n} value={String(n)}>{n} {n === 1 ? 'guest' : 'guests'}</SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                  </div>

                  {requiresExperience && (
                    <div className="rounded-lg bg-amber-50 border border-amber-200 px-4 py-3 text-sm text-amber-800" data-testid="portal-large-booking-notice">
                      For parties of {matchedTier.minGuests} or more, bookings are available with our{' '}
                      <strong>{matchedTier.label || 'Set Menu / Dining Experience'}</strong> only.
                    </div>
                  )}

                  <div>
                    <label className="text-xs font-medium text-gray-500 mb-2 block">Available Times</label>
                    {slots.length === 0 ? (
                      <p className="text-sm text-gray-400 text-center py-6">No slots available for this date/party size</p>
                    ) : (
                      <div className="grid grid-cols-3 sm:grid-cols-4 gap-2 max-h-48 overflow-y-auto">
                        {slots.map(s => (
                          <button key={s.time} onClick={() => setForm(f => ({ ...f, time: s.time }))}
                            className={`px-3 py-2.5 rounded-lg text-sm font-medium border transition-all ${form.time === s.time ? 'bg-gray-900 text-white border-gray-900' : 'bg-white text-gray-700 border-gray-200 hover:border-gray-400'}`}
                            data-testid={`slot-${s.time}`}>
                            {s.time}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>

                  <Button className="w-full h-12 bg-gray-900 hover:bg-gray-800 text-white" disabled={!form.time}
                    onClick={() => setStep('details')} data-testid="portal-continue-btn">
                    Continue <ChevronRight size={16} className="ml-1" />
                  </Button>
                </div>
              )}

              {step === 'details' && (
                <div className="space-y-5">
                  <div className="flex items-center gap-2 mb-2">
                    <button onClick={() => setStep('select')} className="text-sm text-gray-500 hover:text-gray-700">Back</button>
                    <span className="text-gray-300">|</span>
                    <span className="text-sm text-gray-900 font-medium">{form.date} at {form.time} for {form.partySize}</span>
                  </div>
                  <h2 className="text-xl font-bold text-gray-900">Your Details</h2>
                  <div className="space-y-3">
                    <div>
                      <label className="text-xs font-medium text-gray-500 mb-1 block">Full Name *</label>
                      <Input data-testid="portal-name" value={form.guestName} onChange={e => setForm(f => ({ ...f, guestName: e.target.value }))}
                        placeholder="John Smith" />
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <label className="text-xs font-medium text-gray-500 mb-1 block">Phone</label>
                        <Input data-testid="portal-phone" value={form.guestPhone} onChange={e => setForm(f => ({ ...f, guestPhone: e.target.value }))}
                          placeholder="+61 400 000 000" />
                      </div>
                      <div>
                        <label className="text-xs font-medium text-gray-500 mb-1 block">Email</label>
                        <Input data-testid="portal-email" type="email" value={form.guestEmail}
                          onChange={e => setForm(f => ({ ...f, guestEmail: e.target.value }))} placeholder="email@example.com" />
                      </div>
                    </div>
                    <div>
                      <label className="text-xs font-medium text-gray-500 mb-1 block">Special Requests</label>
                      <Input data-testid="portal-requests" value={form.specialRequests}
                        onChange={e => setForm(f => ({ ...f, specialRequests: e.target.value }))}
                        placeholder="Birthday, high chair, dietary needs..." />
                    </div>

                    {requiresExperience && (
                      <div className="pt-2 border-t" data-testid="portal-experience-picker">
                        <p className="text-sm font-semibold text-gray-900 mb-1">Choose your {matchedTier.label || 'experience'}</p>
                        <p className="text-xs text-gray-500 mb-3">
                          For parties of {matchedTier.minGuests} or more, bookings are available with our{' '}
                          {matchedTier.label || 'Set Menu / Dining Experience'} only — à la carte isn't available at this size.
                        </p>
                        {tierExperiences.length === 0 ? (
                          <p className="text-sm text-red-600">No experiences are currently available for this party size — please call us to book.</p>
                        ) : (
                          <div className="space-y-2">
                            {tierExperiences.map(exp => (
                              <button key={exp.id} type="button"
                                onClick={() => setForm(f => ({ ...f, experienceId: exp.id }))}
                                data-testid={`portal-experience-${exp.id}`}
                                className={`w-full text-left px-3 py-2.5 rounded-lg border text-sm transition-all ${
                                  form.experienceId === exp.id ? 'bg-gray-900 text-white border-gray-900' : 'bg-white text-gray-700 border-gray-200 hover:border-gray-400'
                                }`}>
                                <span className="font-medium">{exp.name}</span>
                                {exp.pricePerPerson > 0 && <span className="float-right">${exp.pricePerPerson}/pp</span>}
                                {exp.description && <p className={`text-xs mt-0.5 ${form.experienceId === exp.id ? 'text-gray-300' : 'text-gray-500'}`}>{exp.description}</p>}
                              </button>
                            ))}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                  <Button className="w-full h-12 bg-gray-900 hover:bg-gray-800 text-white"
                    disabled={requiresExperience && !form.experienceId}
                    onClick={handleBook} data-testid="portal-confirm-btn">
                    Confirm Reservation
                  </Button>
                </div>
              )}
            </CardContent>
          </Card>
        )}

        {/* WAITLIST */}
        {tab === 'waitlist' && step !== 'confirmed' && (
          <Card className="border-0 shadow-2xl bg-white/95 backdrop-blur">
            <CardContent className="p-8 space-y-5">
              <h2 className="text-xl font-bold text-gray-900">Join the Waitlist</h2>
              <p className="text-sm text-gray-500">No tables available right now? Join our waitlist and we'll seat you as soon as possible.</p>
              <div className="space-y-3">
                <div>
                  <label className="text-xs font-medium text-gray-500 mb-1 block">Your Name *</label>
                  <Input data-testid="wl-portal-name" value={waitlistForm.guestName}
                    onChange={e => setWaitlistForm(f => ({ ...f, guestName: e.target.value }))} placeholder="Your name" />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-xs font-medium text-gray-500 mb-1 block">Phone</label>
                    <Input value={waitlistForm.guestPhone} onChange={e => setWaitlistForm(f => ({ ...f, guestPhone: e.target.value }))}
                      placeholder="+61 400 000 000" />
                  </div>
                  <div>
                    <label className="text-xs font-medium text-gray-500 mb-1 block">Party Size</label>
                    <Select value={String(waitlistForm.partySize)} onValueChange={v => setWaitlistForm(f => ({ ...f, partySize: parseInt(v) }))}>
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        {[1, 2, 3, 4, 5, 6, 8, 10].map(n => <SelectItem key={n} value={String(n)}>{n} guests</SelectItem>)}
                      </SelectContent>
                    </Select>
                  </div>
                </div>
                <div>
                  <label className="text-xs font-medium text-gray-500 mb-1 block">Seating Preference</label>
                  <Select value={waitlistForm.preferences || 'any'} onValueChange={v => setWaitlistForm(f => ({ ...f, preferences: v === 'any' ? '' : v }))}>
                    <SelectTrigger><SelectValue placeholder="Any" /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="any">Any</SelectItem>
                      <SelectItem value="indoor">Indoor</SelectItem>
                      <SelectItem value="outdoor">Outdoor</SelectItem>
                      <SelectItem value="bar">Bar</SelectItem>
                      <SelectItem value="window">Window</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>
              <Button className="w-full h-12 bg-gray-900 hover:bg-gray-800 text-white"
                onClick={handleJoinWaitlist} data-testid="portal-join-waitlist-btn">
                Join Waitlist
              </Button>
            </CardContent>
          </Card>
        )}

        {/* CONFIRMATION */}
        {step === 'confirmed' && confirmData && (
          <Card className="border-0 shadow-2xl bg-white/95 backdrop-blur">
            <CardContent className="p-8 text-center">
              <div className="w-16 h-16 rounded-full bg-green-100 flex items-center justify-center mx-auto mb-4">
                <Check size={32} className="text-green-600" />
              </div>
              <h2 className="text-2xl font-bold text-gray-900 mb-2">
                {tab === 'reserve' ? 'Reservation Confirmed!' : 'Added to Waitlist!'}
              </h2>
              {tab === 'reserve' && (
                <div className="space-y-2 mt-4 text-sm text-gray-600">
                  <p>Booking Reference: <span className="font-mono font-bold text-gray-900">{confirmData.reservationId}</span></p>
                  <p>{form.date} at {form.time} for {form.partySize} guests</p>
                </div>
              )}
              {tab === 'waitlist' && (
                <div className="space-y-2 mt-4 text-sm text-gray-600">
                  <p>Your position: <span className="text-2xl font-bold text-gray-900">#{confirmData.position}</span></p>
                  <p>Estimated wait: ~{confirmData.estimatedWait} minutes</p>
                </div>
              )}
              <div className="flex flex-col sm:flex-row gap-2 justify-center mt-6">
                {tab === 'waitlist' && confirmData.id && (
                  <Button className="bg-purple-600 hover:bg-purple-700 text-white"
                    onClick={() => navigate(`/waitlist-track/${confirmData.id}${businessQuery}`)}
                    data-testid="portal-track-waitlist-btn">
                    Track my position live
                  </Button>
                )}
                <Button className="bg-gray-900 hover:bg-gray-800 text-white" onClick={reset} data-testid="portal-new-booking-btn">
                  Make Another Booking
                </Button>
              </div>
            </CardContent>
          </Card>
        )}

        {/* EVENTS */}
        {tab === 'events' && (
          <div className="space-y-4">
            {events.length === 0 ? (
              <Card className="border-0 shadow-2xl bg-white/95"><CardContent className="p-8 text-center text-gray-400">No upcoming events</CardContent></Card>
            ) : events.map(evt => {
              const Icon = EVENT_ICONS[evt.eventType] || Ticket;
              const remaining = evt.capacity - (evt.ticketsBooked || 0);
              return (
                <Card key={evt.id} className="border-0 shadow-xl bg-white/95 backdrop-blur overflow-hidden" data-testid={`portal-event-${evt.id}`}>
                  <CardContent className="p-6">
                    <div className="flex items-start justify-between">
                      <div>
                        <Badge className="bg-gray-900 text-white text-[10px] mb-2 capitalize">{evt.eventType?.replace('_', ' ')}</Badge>
                        <h3 className="text-lg font-bold text-gray-900">{evt.name}</h3>
                        {evt.description && <p className="text-sm text-gray-500 mt-1">{evt.description}</p>}
                      </div>
                      {evt.ticketPrice > 0 && <div className="text-right">
                        <p className="text-2xl font-bold text-gray-900">${evt.ticketPrice}</p>
                        <p className="text-[10px] text-gray-500">per ticket</p>
                      </div>}
                    </div>
                    <div className="flex items-center gap-4 mt-4 text-sm text-gray-600">
                      <span className="flex items-center gap-1"><CalendarDays size={14} />{evt.date}</span>
                      <span className="flex items-center gap-1"><Clock size={14} />{evt.time}</span>
                      <span className="flex items-center gap-1"><Users size={14} />{remaining} spots left</span>
                    </div>
                  </CardContent>
                </Card>
              );
            })}
          </div>
        )}

        {/* MENU */}
        {tab === 'menu' && (
          <div className="space-y-6">
            {menu.map((cat, i) => (
              <Card key={i} className="border-0 shadow-xl bg-white/95 backdrop-blur">
                <CardContent className="p-6">
                  <h3 className="text-lg font-bold text-gray-900 mb-3">{cat.name}</h3>
                  <div className="space-y-3">
                    {cat.items.map((item, j) => (
                      <div key={j} className="flex items-center justify-between py-2 border-b border-gray-100 last:border-0">
                        <div>
                          <p className="font-medium text-gray-900">{item.name}</p>
                          {item.description && <p className="text-xs text-gray-500">{item.description}</p>}
                        </div>
                        <span className="font-bold text-gray-900">${item.price.toFixed(2)}</span>
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
