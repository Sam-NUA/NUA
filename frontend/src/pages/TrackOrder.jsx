import React, { useEffect, useState, useCallback } from 'react';
import { useParams, useNavigate, useSearchParams } from 'react-router-dom';
import { Clock, ChefHat, Bike, CheckCircle, Sparkles, RefreshCw, Bell, Package, CreditCard, Loader2 } from 'lucide-react';
import { Card, CardContent } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { onlineAPI, stripeAPI } from '../services/api';

const STEPS = [
  { key: 'pending', label: 'Order received', icon: Bell, color: '#f59e0b' },
  { key: 'accepted', label: 'Accepted', icon: CheckCircle, color: '#3b82f6' },
  { key: 'preparing', label: 'Preparing', icon: ChefHat, color: '#8b5cf6' },
  { key: 'ready', label: 'Ready', icon: Package, color: '#10b981' },
  { key: 'out_for_delivery', label: 'Out for delivery', icon: Bike, color: '#ec4899' },
  { key: 'completed', label: 'Delivered / Picked up', icon: CheckCircle, color: '#10b981' },
];

const stepIdx = (status) => STEPS.findIndex(s => s.key === status);

export default function TrackOrder() {
  const { code: codeFromUrl } = useParams();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const sessionId = searchParams.get('session_id');
  const business = searchParams.get('business');
  const businessQuery = business ? `?business=${encodeURIComponent(business)}` : '';
  const [code, setCode] = useState(codeFromUrl || '');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState('');
  const [paymentPolling, setPaymentPolling] = useState(!!sessionId);

  const fetchData = useCallback(async (c) => {
    if (!c) return;
    setLoading(true); setErr('');
    try {
      const r = await onlineAPI.track(c.toUpperCase());
      setData(r.data);
    } catch (e) { setErr(e?.response?.data?.detail || 'Not found'); setData(null); }
    setLoading(false);
  }, []);

  useEffect(() => { if (codeFromUrl) fetchData(codeFromUrl); }, [codeFromUrl, fetchData]);
  useEffect(() => {
    if (!data || ['completed', 'cancelled'].includes(data.status)) return;
    const t = setInterval(() => fetchData(data.id), 12000);
    return () => clearInterval(t);
  }, [data, fetchData]);

  // Push updates over SSE so a guest watching this page sees "Preparing"
  // flip to "Ready" the moment staff act, not up to 12s later. The poll
  // above stays running regardless — if the stream can't connect (proxy
  // strips SSE, browser quirk) the guest still gets updates, just slower.
  useEffect(() => {
    if (!data?.id || ['completed', 'cancelled'].includes(data.status)) return;
    if (typeof EventSource === 'undefined') return;
    const source = new EventSource(onlineAPI.trackStreamUrl(data.id));
    source.addEventListener('order', (ev) => {
      try { setData(JSON.parse(ev.data)); } catch { /* ignore malformed payload */ }
    });
    source.addEventListener('not_found', () => source.close());
    source.onerror = () => { /* EventSource retries on its own; poll above covers the gap */ };
    return () => source.close();
  }, [data?.id, data?.status]);

  // Coming back from Stripe checkout — poll until the webhook/status-check
  // has flipped paymentStatus, then refresh the order so the "paid" banner
  // reflects reality instead of trusting the redirect alone.
  useEffect(() => {
    if (!sessionId || !data) return;
    if (data.paymentStatus === 'paid') { setPaymentPolling(false); return; }
    let attempts = 0;
    let cancelled = false;
    const poll = async () => {
      if (cancelled || attempts >= 8) { setPaymentPolling(false); return; }
      attempts++;
      try {
        const r = await stripeAPI.checkStatus(sessionId);
        if (r.data?.configured === false) { setPaymentPolling(false); return; }
        if (r.data?.paymentStatus === 'paid') {
          await fetchData(data.id);
          setPaymentPolling(false);
          return;
        }
      } catch { /* keep polling until attempts run out */ }
      if (!cancelled) setTimeout(poll, 2000);
    };
    poll();
    return () => { cancelled = true; };
    // eslint-disable-next-line
  }, [sessionId, data?.id]);

  // For delivery the flow includes out_for_delivery; for pickup/dine-in it skips that.
  const stepsForChannel = (() => {
    if (!data) return STEPS;
    if (data.channel === 'delivery') return STEPS;
    return STEPS.filter(s => s.key !== 'out_for_delivery');
  })();

  const current = data ? stepIdx(data.status) : -1;

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 to-slate-100" data-testid="track-order-page">
      <div className="max-w-2xl mx-auto p-4 sm:p-6 space-y-5">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold">Track your order</h1>
          <div className="flex gap-2">
            <Button variant="ghost" size="sm" onClick={() => navigate(`/rewards${businessQuery}`)}>My Rewards</Button>
            <Button variant="ghost" size="sm" onClick={() => navigate(`/order-online${businessQuery}`)}>← Back to menu</Button>
          </div>
        </div>

        {!codeFromUrl && (
          <Card><CardContent className="p-4 flex gap-2">
            <Input placeholder="Enter order code (ORD-XXXXXXXX)" value={code} onChange={e => setCode(e.target.value)} data-testid="track-code-input" />
            <Button onClick={() => fetchData(code)} disabled={!code} data-testid="track-lookup-btn">Lookup</Button>
          </CardContent></Card>
        )}

        {err && <p className="text-sm text-center text-red-600">{err}</p>}

        {data && sessionId && (
          <Card className={paymentPolling ? 'border-blue-200 bg-blue-50/60' : data.paymentStatus === 'paid' ? 'border-emerald-200 bg-emerald-50/60' : 'border-amber-200 bg-amber-50/60'} data-testid="track-payment-status">
            <CardContent className="p-3 flex items-center gap-2 text-sm">
              {paymentPolling ? (
                <><Loader2 size={16} className="animate-spin text-blue-600" /> Confirming your payment…</>
              ) : data.paymentStatus === 'paid' ? (
                <><CreditCard size={16} className="text-emerald-600" /> <span className="font-medium text-emerald-800">Payment confirmed — nothing to pay on arrival.</span></>
              ) : (
                <><CreditCard size={16} className="text-amber-600" /> <span className="text-amber-800">We couldn't confirm payment yet. You can pay at pickup/delivery instead.</span></>
              )}
            </CardContent>
          </Card>
        )}

        {data && (
          <>
            <Card>
              <CardContent className="p-5 space-y-3" data-testid="track-order-card">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="font-mono font-bold text-xs text-gray-400">{data.id}</p>
                    <p className="text-xl font-bold mt-0.5">Hi {data.customerName}!</p>
                  </div>
                  <Button variant="outline" size="sm" onClick={() => fetchData(data.id)} disabled={loading}><RefreshCw size={12} className={loading ? 'animate-spin' : ''} /></Button>
                </div>

                <div className="bg-gradient-to-br from-purple-50 to-indigo-50 border border-purple-200 rounded-xl p-4">
                  <div className="flex items-center gap-2 text-xs uppercase font-bold tracking-wider text-purple-700">
                    <Sparkles size={12} /> AI ETA
                  </div>
                  <p className="text-5xl font-bold text-purple-900 mt-1" data-testid="track-eta">{data.eta?.etaMinutes ?? '—'} <span className="text-xl text-purple-500">min</span></p>
                  {data.etaMessage && <p className="text-sm text-gray-700 mt-1">{data.etaMessage}</p>}
                </div>

                <ol className="space-y-3" data-testid="status-timeline">
                  {stepsForChannel.map((s, idx) => {
                    const Icon = s.icon;
                    const isCompleted = current >= idx;
                    const isActive = current === idx;
                    return (
                      <li key={s.key} className="flex items-start gap-3" data-testid={`track-step-${s.key}`}>
                        <div className={`w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 transition ${isCompleted ? 'text-white' : 'bg-gray-100 text-gray-400'}`}
                          style={isCompleted ? { background: s.color } : {}}>
                          <Icon size={14} />
                        </div>
                        <div className="flex-1">
                          <p className={`text-sm font-medium ${isActive ? 'text-gray-900' : (isCompleted ? 'text-gray-700' : 'text-gray-400')}`}>{s.label}</p>
                          {isActive && <p className="text-xs text-gray-500 mt-0.5">In progress…</p>}
                        </div>
                      </li>
                    );
                  })}
                </ol>
              </CardContent>
            </Card>

            <Card>
              <CardContent className="p-4">
                <p className="text-xs uppercase font-bold tracking-wider text-gray-500 mb-2">Your items</p>
                {data.items.map((it, i) => (
                  <div key={i} className="flex justify-between text-sm py-1.5 border-b last:border-0">
                    <span>{it.quantity}× {it.name}</span>
                    <span className="font-mono">${(it.price * it.quantity).toFixed(2)}</span>
                  </div>
                ))}
                <div className="flex justify-between text-sm pt-2 mt-1 font-bold border-t"><span>Total</span><span>${data.total.toFixed(2)}</span></div>
              </CardContent>
            </Card>

            {data.notifications?.length > 0 && (
              <Card>
                <CardContent className="p-4 space-y-2">
                  <p className="text-xs uppercase font-bold tracking-wider text-gray-500">Messages from the restaurant</p>
                  {data.notifications.slice().reverse().map((n, i) => (
                    <div key={i} className="text-sm bg-amber-50 border-l-4 border-amber-400 p-2 rounded">
                      <p>{n.message}</p>
                      <p className="text-[10px] text-gray-400 mt-0.5">{new Date(n.at).toLocaleString()}</p>
                    </div>
                  ))}
                </CardContent>
              </Card>
            )}
          </>
        )}
      </div>
    </div>
  );
}
