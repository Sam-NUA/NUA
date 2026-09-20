import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, CardContent } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Badge } from '../components/ui/badge';
import { loyaltyGuestAPI } from '../services/api';
import {
  Sparkles, Coffee, Heart, Trophy, DollarSign, Crown, Sunrise, Wine, Users, Gift,
  Lock, CheckCircle2, Target, Loader2, Phone, MapPin, Star,
} from 'lucide-react';

const ICONS = {
  sparkles: Sparkles, coffee: Coffee, heart: Heart, trophy: Trophy,
  'dollar-sign': DollarSign, crown: Crown, sunrise: Sunrise, wine: Wine,
  users: Users, gift: Gift,
};

const TIER_COLOR = {
  Bronze: '#a16207', Silver: '#94a3b8', Gold: '#eab308', Platinum: '#a855f7',
};

/**
 * Guest-facing loyalty portal — no login exists for a customer, so this
 * looks them up by the phone number checkout already keys their loyalty
 * account on. A texted one-time code gates the actual lookup: knowing (or
 * guessing) someone's number is no longer enough to see their points and
 * badges, the code has to land on that phone. Unauthenticated by design
 * (mirrors /vouchers/public-check): the backend returns first name only,
 * never the full customer record.
 */
export default function LoyaltyGuestPortal() {
  const navigate = useNavigate();
  const business = new URLSearchParams(window.location.search).get('business');
  const businessQuery = business ? `?business=${encodeURIComponent(business)}` : '';
  const [phone, setPhone] = useState('');
  const [code, setCode] = useState('');
  const [codeSent, setCodeSent] = useState(false);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState('');

  const requestCode = async () => {
    if (!phone.trim()) return;
    setLoading(true); setErr('');
    try {
      await loyaltyGuestAPI.requestCode(phone.trim());
      setCodeSent(true);
    } catch {
      setErr('Something went wrong — please try again.');
    } finally {
      setLoading(false);
    }
  };

  const lookup = async () => {
    if (!code.trim()) return;
    setLoading(true); setErr(''); setData(null);
    try {
      const r = await loyaltyGuestAPI.lookup(phone.trim(), code.trim(), business);
      if (!r.data.found) {
        setErr("We couldn't find a rewards account for that number.");
      } else {
        setData(r.data);
      }
    } catch (e) {
      setErr(e?.response?.data?.detail || 'That code didn\'t work — please try again.');
    } finally {
      setLoading(false);
    }
  };

  const startOver = () => { setData(null); setPhone(''); setCode(''); setCodeSent(false); };

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 to-slate-100" data-testid="loyalty-guest-portal">
      <div className="max-w-lg mx-auto p-4 sm:p-6 space-y-5">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold flex items-center gap-2"><Sparkles className="text-violet-500" /> My Rewards</h1>
          <Button variant="ghost" size="sm" onClick={() => navigate(`/order-online${businessQuery}`)}>← Back to menu</Button>
        </div>

        {!data && !codeSent && (
          <Card>
            <CardContent className="p-5 space-y-3">
              <p className="text-sm text-slate-500">Enter the phone number you use at checkout — we'll text you a code to confirm it's you.</p>
              <div className="flex gap-2">
                <div className="relative flex-1">
                  <Phone size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                  <Input className="pl-8" placeholder="0400 000 000" value={phone}
                    onChange={e => setPhone(e.target.value)}
                    onKeyDown={e => e.key === 'Enter' && requestCode()}
                    data-testid="guest-phone-input" />
                </div>
                <Button onClick={requestCode} disabled={loading || !phone.trim()} data-testid="guest-request-code-btn">
                  {loading ? <Loader2 size={14} className="animate-spin" /> : 'Send code'}
                </Button>
              </div>
              {err && <p className="text-sm text-red-600" data-testid="guest-lookup-error">{err}</p>}
            </CardContent>
          </Card>
        )}

        {!data && codeSent && (
          <Card>
            <CardContent className="p-5 space-y-3">
              <p className="text-sm text-slate-500">Enter the 6-digit code we texted to {phone}.</p>
              <div className="flex gap-2">
                <Input className="tracking-widest" placeholder="000000" maxLength={6} value={code}
                  onChange={e => setCode(e.target.value.replace(/\D/g, ''))}
                  onKeyDown={e => e.key === 'Enter' && lookup()}
                  data-testid="guest-code-input" />
                <Button onClick={lookup} disabled={loading || code.length !== 6} data-testid="guest-lookup-btn">
                  {loading ? <Loader2 size={14} className="animate-spin" /> : 'Check'}
                </Button>
              </div>
              {err && <p className="text-sm text-red-600" data-testid="guest-lookup-error">{err}</p>}
              <div className="flex justify-between text-xs">
                <button className="text-slate-400 hover:text-slate-600" onClick={startOver}>← Wrong number?</button>
                <button className="text-slate-400 hover:text-slate-600" onClick={requestCode} disabled={loading}>Resend code</button>
              </div>
            </CardContent>
          </Card>
        )}

        {data && (
          <>
            <Card>
              <CardContent className="p-5 space-y-3" data-testid="guest-progress-card">
                <div className="flex items-center justify-between">
                  <p className="text-xl font-bold">Hi {data.firstName}!</p>
                  <Button variant="outline" size="sm" onClick={startOver} data-testid="guest-lookup-again-btn">
                    Not you?
                  </Button>
                </div>

                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-xs uppercase tracking-wider text-slate-400">Tier</p>
                    <h2 className="text-2xl font-bold mt-1" style={{ color: TIER_COLOR[data.tier] || '#334155' }} data-testid="guest-tier-name">
                      {data.tier || 'Bronze'}
                    </h2>
                    <p className="text-sm text-slate-500 mt-1">{data.points} points</p>
                  </div>
                  {data.tierProgress?.next && (
                    <div className="text-right">
                      <p className="text-xs uppercase tracking-wider text-slate-400">Next tier</p>
                      <p className="font-semibold" style={{ color: TIER_COLOR[data.tierProgress.next] || '#334155' }}>
                        {data.tierProgress.next}
                      </p>
                      <p className="text-xs text-slate-400">{data.tierProgress.pointsNeeded} pts to go</p>
                    </div>
                  )}
                </div>

                {data.tierProgress && (
                  <div>
                    <div className="w-full h-2 rounded-full bg-slate-100 overflow-hidden">
                      <div className="h-full rounded-full transition-all"
                        style={{
                          width: `${data.tierProgress.percent}%`,
                          background: `linear-gradient(to right, ${TIER_COLOR[data.tierProgress.current]}, ${TIER_COLOR[data.tierProgress.next] || TIER_COLOR[data.tierProgress.current]})`,
                        }} />
                    </div>
                    <p className="text-[10px] text-slate-500 mt-1">{data.tierProgress.percent}% to next tier</p>
                  </div>
                )}
              </CardContent>
            </Card>

            {data.passport && (
              <Card className="border-indigo-200 bg-indigo-50/60" data-testid="guest-passport-card">
                <CardContent className="p-5 space-y-3">
                  <div className="flex items-center gap-2">
                    <MapPin size={16} className="text-indigo-600" />
                    <p className="font-semibold text-sm text-indigo-800">You're a member at {data.passport.locations.length} locations</p>
                  </div>
                  <p className="text-xs text-indigo-700/80">
                    Combined across every venue: <span className="font-bold">{data.passport.groupPoints} points</span>,{' '}
                    <span className="font-bold">{data.passport.groupTier || 'Bronze'}</span> tier.
                  </p>
                  <div className="space-y-1.5">
                    {data.passport.locations.map(l => (
                      <div key={l.customerId} className="flex items-center justify-between bg-white rounded-lg border border-indigo-100 px-3 py-2 text-sm"
                        data-testid={`guest-passport-location-${l.businessId}`}>
                        <span className="font-medium truncate">{l.businessName}</span>
                        <span className="text-slate-500 text-xs flex-shrink-0">{l.points} pts · {l.tier || 'Bronze'}</span>
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>
            )}

            {data.subscription && (
              <Card className="border-amber-200 bg-amber-50/60" data-testid="guest-subscription-card">
                <CardContent className="p-5 space-y-2">
                  <div className="flex items-center gap-2">
                    <Star size={16} className="text-amber-600" fill="currentColor" />
                    <p className="font-semibold text-sm text-amber-800">{data.subscription.planName} member</p>
                  </div>
                  {data.subscription.perks?.length > 0 && (
                    <ul className="text-xs text-amber-700/90 space-y-1 pl-1">
                      {data.subscription.perks.map((p, i) => <li key={i}>• {p}</li>)}
                    </ul>
                  )}
                </CardContent>
              </Card>
            )}

            {data.badges.length > 0 && (
              <Card><CardContent className="p-5">
                <p className="text-xs uppercase tracking-wider text-slate-400 mb-3">Badges earned</p>
                <div className="grid grid-cols-3 sm:grid-cols-5 gap-3">
                  {data.badges.map(b => {
                    const Icon = ICONS[b.icon] || Sparkles;
                    return (
                      <div key={b.id} className="text-center p-3 rounded-lg border" data-testid={`guest-badge-${b.id}`}>
                        <div className="h-12 w-12 rounded-full mx-auto flex items-center justify-center text-white mb-2" style={{ background: b.color }}>
                          <Icon size={22} />
                        </div>
                        <p className="text-[11px] font-medium">{b.name}</p>
                      </div>
                    );
                  })}
                </div>
              </CardContent></Card>
            )}

            {data.milestones?.length > 0 && (
              <Card><CardContent className="p-5">
                <p className="text-xs uppercase tracking-wider text-slate-400 mb-3">Milestones</p>
                <div className="space-y-3">
                  {data.milestones.map(m => (
                    <div key={m.id} className="p-3 rounded border" data-testid={`guest-milestone-${m.id}`}>
                      <div className="flex justify-between items-center mb-1">
                        <div className="flex items-center gap-2">
                          {m.achieved ? <CheckCircle2 size={16} className="text-emerald-500" /> : <Target size={16} className="text-slate-400" />}
                          <p className="text-sm font-medium">{m.name}</p>
                        </div>
                        {m.achieved ? (
                          <Badge className="bg-emerald-500">{m.reward?.label}</Badge>
                        ) : (
                          <Badge variant="outline" className="text-slate-400"><Lock size={10} className="mr-1" />{m.reward?.label}</Badge>
                        )}
                      </div>
                      {!m.achieved && (
                        <div className="w-full h-1.5 rounded-full bg-slate-100 overflow-hidden mt-1.5">
                          <div className="h-full rounded-full bg-violet-400" style={{ width: `${m.progressPercent}%` }} />
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </CardContent></Card>
            )}
          </>
        )}
      </div>
    </div>
  );
}
