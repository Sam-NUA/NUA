import React, { useEffect, useState, useCallback } from 'react';
import { useParams, useNavigate, useSearchParams } from 'react-router-dom';
import { Clock, Users, CheckCircle, Bell, RefreshCw, PartyPopper, XCircle } from 'lucide-react';
import { Card, CardContent } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { publicAPI } from '../services/api';

const STATUS_COPY = {
  waiting: { label: "You're in the queue", icon: Clock, color: '#f59e0b' },
  notified: { label: 'Your table is almost ready — head to the host stand', icon: Bell, color: '#3b82f6' },
  seated: { label: "You're seated — enjoy!", icon: PartyPopper, color: '#10b981' },
  cancelled: { label: 'This waitlist entry was cancelled', icon: XCircle, color: '#94a3b8' },
  left: { label: 'Marked as left the queue', icon: XCircle, color: '#94a3b8' },
};

export default function TrackWaitlist() {
  const { code: codeFromUrl } = useParams();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const business = searchParams.get('business');
  const businessQuery = business ? `?business=${encodeURIComponent(business)}` : '';
  const [code, setCode] = useState(codeFromUrl || '');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState('');

  const fetchData = useCallback(async (c) => {
    if (!c) return;
    setLoading(true); setErr('');
    try {
      const r = await publicAPI.trackWaitlist(c.toUpperCase());
      setData(r.data);
    } catch (e) { setErr(e?.response?.data?.detail || 'Not found'); setData(null); }
    setLoading(false);
  }, []);

  useEffect(() => { if (codeFromUrl) fetchData(codeFromUrl); }, [codeFromUrl, fetchData]);

  // Poll as the floor — SSE (below) covers the common case, this is the
  // fallback for anywhere a proxy strips server-sent events.
  useEffect(() => {
    if (!data || ['seated', 'cancelled', 'left'].includes(data.status)) return;
    const t = setInterval(() => fetchData(data.id), 10000);
    return () => clearInterval(t);
  }, [data, fetchData]);

  useEffect(() => {
    if (!data?.id || ['seated', 'cancelled', 'left'].includes(data.status)) return;
    if (typeof EventSource === 'undefined') return;
    const source = new EventSource(publicAPI.trackWaitlistStreamUrl(data.id));
    source.addEventListener('waitlist', (ev) => {
      try { setData(JSON.parse(ev.data)); } catch { /* ignore malformed payload */ }
    });
    source.addEventListener('not_found', () => source.close());
    source.onerror = () => { /* EventSource retries on its own; poll above covers the gap */ };
    return () => source.close();
  }, [data?.id, data?.status]);

  const status = data ? (STATUS_COPY[data.status] || STATUS_COPY.waiting) : null;
  const StatusIcon = status?.icon || Clock;

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 to-slate-100" data-testid="track-waitlist-page">
      <div className="max-w-xl mx-auto p-4 sm:p-6 space-y-5">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold">Waitlist status</h1>
          <Button variant="ghost" size="sm" onClick={() => navigate(`/booking${businessQuery}`)}>← Back</Button>
        </div>

        {!codeFromUrl && (
          <Card><CardContent className="p-4 flex gap-2">
            <Input placeholder="Enter waitlist code (WL-XXXXXXXX)" value={code} onChange={e => setCode(e.target.value)} data-testid="waitlist-track-code-input" />
            <Button onClick={() => fetchData(code)} disabled={!code} data-testid="waitlist-track-lookup-btn">Lookup</Button>
          </CardContent></Card>
        )}

        {err && <p className="text-sm text-center text-red-600">{err}</p>}

        {data && (
          <Card>
            <CardContent className="p-5 space-y-4" data-testid="track-waitlist-card">
              <div className="flex items-center justify-between">
                <div>
                  <p className="font-mono font-bold text-xs text-gray-400">{data.id}</p>
                  <p className="text-xl font-bold mt-0.5">Hi {data.guestName}!</p>
                </div>
                <Button variant="outline" size="sm" onClick={() => fetchData(data.id)} disabled={loading}>
                  <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
                </Button>
              </div>

              <div className="rounded-xl p-4 border" style={{ background: `${status.color}12`, borderColor: `${status.color}44` }} data-testid={`waitlist-status-${data.status}`}>
                <div className="flex items-center gap-2 text-sm font-semibold" style={{ color: status.color }}>
                  <StatusIcon size={16} /> {status.label}
                </div>
              </div>

              {data.status === 'waiting' && (
                <div className="bg-gradient-to-br from-purple-50 to-indigo-50 border border-purple-200 rounded-xl p-4 text-center">
                  <p className="text-xs uppercase font-bold tracking-wider text-purple-700">Your position</p>
                  <p className="text-5xl font-bold text-purple-900 mt-1" data-testid="track-waitlist-position">#{data.position}</p>
                  {data.aheadOfYou > 0 && (
                    <p className="text-sm text-gray-600 mt-1">{data.aheadOfYou} {data.aheadOfYou === 1 ? 'party' : 'parties'} ahead of you</p>
                  )}
                  {data.quotedWait != null && (
                    <p className="text-xs text-gray-500 mt-1">Quoted wait: ~{data.quotedWait} min</p>
                  )}
                </div>
              )}

              <div className="flex items-center gap-2 text-sm text-gray-500">
                <Users size={14} /> Party of {data.partySize}
                <span className="mx-1">·</span>
                <Clock size={14} /> Checked in {data.checkInTime ? new Date(data.checkInTime).toLocaleTimeString() : '—'}
              </div>

              {data.status === 'seated' && (
                <div className="flex items-center gap-2 text-sm text-emerald-700">
                  <CheckCircle size={14} /> Seated {data.seatedTime ? new Date(data.seatedTime).toLocaleTimeString() : ''}
                </div>
              )}
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
