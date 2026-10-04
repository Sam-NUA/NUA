import React, { useEffect, useState } from 'react';
import axios from 'axios';
import { AuthProvider, useAuth } from '../contexts/AuthContext';
import './BookingProduct.css';

const base = process.env.REACT_APP_BACKEND_URL || '';
const api = axios.create({ baseURL: `${base}/api/booking-product` });
api.interceptors.request.use(config => {
  const token = localStorage.getItem('nua_token');
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});
const message = e => {
  const detail = e.response?.data?.detail;
  return typeof detail === 'string' ? detail : 'Please check your details and try again.';
};
const dateToday = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
};
function Field({ label, ...props }) {
  return <label className="booking-field"><span>{label}</span><input {...props} /></label>;
}
function BookingForm({ onSubmit, venue, disabled }) {
  const empty = () => ({ requestId: crypto.randomUUID(), guestName: '', guestEmail: '', guestPhone: '', partySize: 2, date: '', time: '', specialRequests: '' });
  const [form, setForm] = useState(empty);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const change = e => { setForm(v => ({ ...v, [e.target.name]: e.target.name === 'partySize' ? Number(e.target.value) : e.target.value })); };
  async function submit(e) {
    e.preventDefault(); setBusy(true); setError(''); setNotice('');
    try {
      const r = await onSubmit(form);
      setNotice(`Booking ${r.status}: ${r.date} at ${r.time}. Reference ${r.id}. Please save this confirmation.`);
      setForm(empty());
    } catch (e) { setError(message(e)); }
    finally { setBusy(false); }
  }
  return <form onSubmit={submit} className="booking-card">
    <h2>Make a booking</h2>
    <p>Times are in {venue.timezone}. Bookings last 90 minutes. No payment is collected here.</p>
    <div className="booking-grid">
      <Field label="Guest name" name="guestName" value={form.guestName} onChange={change} required maxLength={120} />
      <Field label="Email" name="guestEmail" type="email" value={form.guestEmail} onChange={change} required />
      <Field label="Phone (optional)" name="guestPhone" value={form.guestPhone} onChange={change} maxLength={40} />
      <Field label="Guests" name="partySize" type="number" min="1" max={venue.maxPartySize} value={form.partySize} onChange={change} required />
      <Field label="Date" name="date" type="date" value={form.date} onChange={change} required />
      <Field label={`Time (${venue.openTime}–${venue.closeTime})`} name="time" type="time" value={form.time} onChange={change} required />
    </div>
    <Field label="Special requests (optional)" name="specialRequests" value={form.specialRequests} onChange={change} maxLength={1000} />
    <p>Confirmation appears on this page. Email and SMS reminders are not included in this pilot.</p>
    <button disabled={disabled || busy}>{busy ? 'Confirming…' : 'Confirm booking'}</button>
    {error && <p role="alert" className="booking-error">{error}</p>}
    {notice && <p role="status" className="booking-success">{notice}</p>}
  </form>;
}
function Guest({ businessId }) {
  const [venue, setVenue] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => { let live = true; api.get(`/public/${encodeURIComponent(businessId)}`).then(r => { if (live) setVenue(r.data); }).catch(e => { if (live) setError(message(e)); }); return () => { live = false; }; }, [businessId]);
  if (error) return <p role="alert">{error}</p>;
  if (!venue) return <p>Loading booking page…</p>;
  return <><h1>{venue.name}</h1><BookingForm venue={venue} onSubmit={async data => (await api.post(`/public/${encodeURIComponent(businessId)}`, data)).data} /></>;
}
function Access() {
  const { login, checkAuth, completeTwoFactor } = useAuth();
  const [signup, setSignup] = useState(false);
  const [enabled, setEnabled] = useState(false);
  const [form, setForm] = useState({ name: '', venueName: '', email: '', password: '', timezone: 'Australia/Melbourne' });
  const [challenge, setChallenge] = useState(null);
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => { api.get('/availability').then(r => setEnabled(r.data.signupEnabled)).catch(e => setError(message(e))); }, []);
  const change = e => setForm({ ...form, [e.target.name]: e.target.value });
  async function submit(e) {
    e.preventDefault(); setBusy(true); setError('');
    try {
      if (challenge) {
        await completeTwoFactor(challenge.challengeToken, code, false);
      } else if (signup) {
        const r = await api.post('/signup', form);
        localStorage.setItem('nua_token', r.data.token); await checkAuth();
      } else {
        const r = await login(form.email, form.password);
        if (r.twoFactor) setChallenge(r.twoFactor);
      }
    } catch (e) { setError(message(e)); }
    finally { setBusy(false); }
  }
  return <><h1>Bookings that fit your business.</h1><p>Keep your existing POS. Manage your reservations with NUA.</p>
    <form onSubmit={submit} className="booking-card">
      <h2>{challenge ? 'Verify your sign-in' : signup ? 'Start your 14-day Booking pilot' : 'Sign in to NUA Booking'}</h2>
      {challenge ? <Field label="Authenticator or recovery code" value={code} onChange={e => setCode(e.target.value)} required autoComplete="one-time-code" /> : <>
        {signup && <><Field label="Your name" name="name" value={form.name} onChange={change} required maxLength={120} /><Field label="Venue name" name="venueName" value={form.venueName} onChange={change} required maxLength={120} /><Field label="Venue timezone" name="timezone" value={form.timezone} onChange={change} required /></>}
        <Field label="Email" name="email" type="email" value={form.email} onChange={change} autoComplete="username" required />
        <Field label={signup ? 'Password (12–72 characters)' : 'Password'} name="password" type="password" value={form.password} onChange={change} minLength={signup ? 12 : 1} maxLength={72} autoComplete={signup ? 'new-password' : 'current-password'} required />
      </>}
      {signup && <p>No card required. This pilot includes reservations and guest links. Paid plans, deposits and messaging are not enabled. After 14 days, records remain available to read and export.</p>}
      <button disabled={busy}>{busy ? 'Please wait…' : challenge ? 'Verify' : signup ? 'Create Booking account' : 'Sign in'}</button>
      {error && <p role="alert" className="booking-error">{error}</p>}
    </form>
    {!challenge && <button className="booking-secondary" disabled={!signup && !enabled} onClick={() => { setSignup(!signup); setError(''); }}>{signup ? 'Already have a Booking account? Sign in' : enabled ? 'Create a Booking account' : 'New pilot registrations are currently closed'}</button>}
  </>;
}
function Workspace() {
  const { logout } = useAuth();
  const [account, setAccount] = useState(null);
  const [venue, setVenue] = useState(null);
  const [day, setDay] = useState(dateToday);
  const [rows, setRows] = useState([]);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [cancelConfirm, setCancelConfirm] = useState(false);
  async function loadAccount() { const r = await api.get('/account'); setAccount(r.data); setVenue(r.data.venue); }
  async function loadRows() { const r = await api.get('/reservations', { params: { day } }); setRows(r.data); }
  useEffect(() => { loadAccount().catch(e => setError(message(e))); }, []);
  useEffect(() => { let live = true; api.get('/reservations', { params: { day } }).then(r => { if (live) setRows(r.data); }).catch(e => { if (live) setError(message(e)); }); return () => { live = false; }; }, [day]);
  async function act(fn) { setBusy(true); setError(''); setNotice(''); try { await fn(); } catch (e) { setError(message(e)); } finally { setBusy(false); } }
  async function exportData() {
    const r = await api.get('/export');
    const url = URL.createObjectURL(new Blob([JSON.stringify(r.data, null, 2)], { type: 'application/json' }));
    const a = document.createElement('a'); a.href = url; a.download = 'nua-booking-export.json'; a.click(); URL.revokeObjectURL(url);
  }
  if (!account) return <><p>{error || 'Loading your Booking account…'}</p><button onClick={logout}>Sign out</button></>;
  const sub = account.products.booking;
  const set = e => setVenue({ ...venue, [e.target.name]: ['capacity', 'maxPartySize'].includes(e.target.name) ? Number(e.target.value) : e.target.value });
  return <>
    <div className="booking-top"><div><h1>{account.venue.name}</h1><p>NUA Booking · {account.canWrite ? 'Pilot active' : 'Read-only'} · Trial ends {new Date(sub.trialEndsAt).toLocaleDateString()}</p></div><button className="booking-secondary" onClick={logout}>Sign out</button></div>
    {error && <p role="alert" className="booking-error">{error}</p>}{notice && <p role="status">{notice}</p>}
    {!account.canWrite && <p className="booking-card">Your trial is no longer active. New bookings are paused. You can still view, export and cancel existing reservations.</p>}
    <section className="booking-card"><h2>Your reservations</h2><div className="booking-actions"><Field label="Service date" type="date" value={day} onChange={e => setDay(e.target.value)} /><button disabled={busy} onClick={() => act(loadRows)}>Refresh</button><button disabled={busy} onClick={() => act(exportData)}>Export all bookings</button></div>
      <div className="booking-table"><table><thead><tr><th>Time</th><th>Guest</th><th>Guests</th><th>Status</th><th>Action</th></tr></thead><tbody>{rows.map(row => <tr key={row.id}><td>{row.time}</td><td>{row.guestName}<br /><small>{row.guestEmail}</small></td><td>{row.partySize}</td><td>{row.status}</td><td>{row.status !== 'cancelled' && <button disabled={busy} onClick={() => act(async () => { await api.post(`/reservations/${row.id}/cancel`); await loadRows(); })}>Cancel booking</button>}</td></tr>)}</tbody></table></div>{!rows.length && <p>No reservations for this date.</p>}
    </section>
    {account.canWrite && <BookingForm venue={account.venue} onSubmit={async data => { const r = await api.post('/reservations', data); setDay(data.date); await loadRows(); return r.data; }} />}
    <form className="booking-card" onSubmit={e => { e.preventDefault(); act(async () => { const r = await api.put('/venue', venue); setAccount(r.data); setVenue(r.data.venue); setNotice('Venue settings saved.'); }); }}>
      <h2>Venue and guest booking page</h2><p>Capacity is shared across overlapping 90-minute bookings. This pilot uses venue capacity rather than individual table assignment.</p>
      <div className="booking-grid"><Field label="Venue name" name="name" value={venue.name} onChange={set} required maxLength={120} /><Field label="Timezone" name="timezone" value={venue.timezone} onChange={set} required /><Field label="First booking time" name="openTime" type="time" value={venue.openTime} onChange={set} required /><Field label="Last booking cutoff" name="closeTime" type="time" value={venue.closeTime} onChange={set} required /><Field label="Simultaneous guest capacity" name="capacity" type="number" min="1" max="500" value={venue.capacity} onChange={set} required /><Field label="Maximum party size" name="maxPartySize" type="number" min="1" max="50" value={venue.maxPartySize} onChange={set} required /></div>
      <label><input type="checkbox" checked={venue.published} onChange={e => setVenue({ ...venue, published: e.target.checked })} /> Publish guest booking page</label><p><button disabled={busy || !account.canWrite}>Save venue settings</button></p>
      {account.venue.published && account.canWrite && <p><a href={account.guestPath} target="_blank" rel="noreferrer">Open guest booking page</a><br /><small>{window.location.origin}{account.guestPath}</small></p>}
    </form>
    <section className="booking-card"><h2>Booking subscription</h2><p>This is a no-charge pilot. Paid checkout is not yet available. Cancelling makes Booking read-only immediately and closes your guest page; it does not erase your reservations.</p>
      {account.canWrite && (cancelConfirm ? <div className="booking-actions"><button disabled={busy} onClick={() => act(async () => { await api.post('/cancel'); await loadAccount(); setCancelConfirm(false); })}>Confirm cancellation</button><button className="booking-secondary" onClick={() => setCancelConfirm(false)}>Keep trial</button></div> : <button className="booking-secondary" onClick={() => setCancelConfirm(true)}>Cancel Booking trial</button>)}
    </section>
  </>;
}
function Content() {
  const { user, loading } = useAuth();
  const guest = window.location.pathname.match(/^\/book\/v\/([^/]+)\/?$/);
  if (guest) return <Guest businessId={decodeURIComponent(guest[1])} />;
  if (loading) return <p>Checking your account…</p>;
  if (!user) return <Access />;
  if (!user.businessId?.startsWith('nb_')) return <><h1>NUA Booking pilot</h1><p>This workspace is for standalone Booking accounts. Your existing venue continues to use reservations in NUA.</p><a href="/">Return to NUA</a></>;
  return <Workspace />;
}
export default function BookingProduct() {
  return <AuthProvider><main className="booking-product"><header className="booking-brand">NUA <span>Booking</span></header><Content /></main></AuthProvider>;
}
