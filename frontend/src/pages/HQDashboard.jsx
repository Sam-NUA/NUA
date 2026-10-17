import React, { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import { Card, CardContent } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Building2, Trophy, TrendingUp } from 'lucide-react';
import { toast } from 'sonner';
import { SecureStorageService } from '../platform';

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const H = async () => ({ Authorization: `Bearer ${await SecureStorageService.getToken()}` });

export default function HQDashboard() {
  const [rollup, setRollup] = useState(null);
  const [leaderboard, setLeaderboard] = useState([]);
  const [brands, setBrands] = useState([]);
  const [days, setDays] = useState(7);

  const load = useCallback(async () => {
    try {
      const [r, l, b] = await Promise.all([
        axios.get(`${API}/hq/kpi-roll-up?days=${days}`, { headers: await H() }),
        axios.get(`${API}/hq/leaderboard`, { headers: await H() }),
        axios.get(`${API}/hq/brands`, { headers: await H() }),
      ]);
      setRollup(r.data); setLeaderboard(l.data); setBrands(b.data);
    } catch { toast.error('Failed to load HQ dashboard'); }
  }, [days]);
  useEffect(() => { load(); }, [load]);

  const FMT = (n) => n?.toLocaleString('en-AU', { style: 'currency', currency: 'AUD', minimumFractionDigits: 0 });

  return (
    <div className="space-y-6" data-testid="hq-dashboard">
      <div>
        <h1 className="text-3xl font-bold flex items-center gap-2"><Building2 className="text-indigo-600" /> HQ — Franchise Command</h1>
        <p className="text-sm text-slate-500 mt-1">Roll-up across every location in the network.</p>
      </div>

      <div className="flex gap-2">
        {[7, 30, 90].map(d => (
          <Button key={d} size="sm" variant={days === d ? 'default' : 'outline'} onClick={() => setDays(d)} data-testid={`range-${d}`}>
            Last {d}d
          </Button>
        ))}
      </div>

      {rollup && (
        <Card><CardContent className="p-6">
          <div className="flex justify-between items-center mb-4">
            <div>
              <p className="text-xs uppercase tracking-wider text-slate-500">Network Revenue · Last {rollup.days}d</p>
              <p className="text-4xl font-bold text-emerald-600 mt-1">{FMT(rollup.totalRevenue)}</p>
            </div>
            <TrendingUp size={40} className="text-emerald-600 opacity-30" />
          </div>
          <div className="space-y-2">
            {rollup.locations.map((l, idx) => (
              <div key={l.location} className="flex justify-between items-center p-2 border rounded" data-testid={`loc-${idx}`}>
                <div>
                  <p className="font-medium">{l.location}</p>
                  <p className="text-xs text-slate-500">{l.covers} covers · GST {FMT(l.gst)}</p>
                </div>
                <p className="text-xl font-semibold">{FMT(l.revenue)}</p>
              </div>
            ))}
            {rollup.locations.length === 0 && <p className="text-slate-400 text-center py-4">No transactions in the selected range.</p>}
          </div>
        </CardContent></Card>
      )}

      <Card><CardContent className="p-6">
        <div className="flex items-center gap-2 mb-4"><Trophy className="text-amber-500" /> <h3 className="font-semibold">Location Leaderboard (30-day revenue)</h3></div>
        <div className="space-y-2">
          {leaderboard.map(l => (
            <div key={l.rank} className="flex justify-between items-center p-2 border rounded" data-testid={`leader-${l.rank}`}>
              <div className="flex items-center gap-3">
                <Badge className={l.rank === 1 ? 'bg-amber-500' : l.rank === 2 ? 'bg-slate-300' : l.rank === 3 ? 'bg-orange-400' : 'bg-slate-200'}>#{l.rank}</Badge>
                <span className="font-medium">{l.location}</span>
              </div>
              <span className="font-semibold">{FMT(l.revenue)}</span>
            </div>
          ))}
          {leaderboard.length === 0 && <p className="text-slate-400 text-center py-4">No locations reporting yet.</p>}
        </div>
      </CardContent></Card>

      {brands.length > 0 && (
        <Card><CardContent className="p-6">
          <h3 className="font-semibold mb-3">Brand Groups</h3>
          {brands.map(b => (
            <div key={b.id || b.name} className="p-2 border rounded mb-2">
              <p className="font-medium">{b.name}</p>
              <p className="text-xs text-slate-500">{b.type || 'brand'} · id {(b.id || '?').slice(0, 8)}</p>
            </div>
          ))}
        </CardContent></Card>
      )}
    </div>
  );
}
