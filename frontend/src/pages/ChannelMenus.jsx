import React, { useEffect, useMemo, useState } from 'react';
import { Card, CardContent } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Badge } from '../components/ui/badge';
import { useToast } from '../hooks/use-toast';
import { useTheme } from '../contexts/ThemeContext';
import { channelMenusAPI } from '../services/api';
import ChannelPauseControl from '../components/channel/ChannelPauseControl';
import {
  Globe, Bike, Truck, Smartphone, QrCode, Phone, ChefHat,
  TrendingDown, Flame, Save, Search, Sparkles
} from 'lucide-react';

const CHANNEL_ICON = {
  website: Globe,
  uber_eats: Bike,
  doordash: Truck,
  menulog: Bike,
  deliveroo: Bike,
  qr_order: QrCode,
  kiosk: Smartphone,
  phone: Phone,
};

export default function ChannelMenus() {
  const { theme } = useTheme();
  const { toast } = useToast();
  const [channels, setChannels] = useState([]);
  const [active, setActive] = useState('website');
  const [rows, setRows] = useState([]);
  const [search, setSearch] = useState('');
  const [busy, setBusy] = useState(false);
  const [bulk, setBulk] = useState({ deltaPercent: '', deltaDollars: '', applyToModifiers: false, roundingMode: 'nearest_5c' });
  const [discount, setDiscount] = useState({ discountPercent: 15, bottomN: 5, daysWindow: 7 });

  // Load supported channels once
  useEffect(() => { channelMenusAPI.channels().then(r => setChannels(r.data || [])); }, []);
  // Load rows whenever active channel changes
  useEffect(() => { loadRows();   }, [active]);

  const loadRows = async () => {
    try {
      const r = await channelMenusAPI.list(active);
      setRows(r.data || []);
    } catch { toast({ title: 'Failed to load channel menu', variant: 'destructive' }); }
  };

  const patchRow = async (productId, patch) => {
    try {
      await channelMenusAPI.patch(active, { productId, ...patch });
      toast({ title: 'Saved' });
      loadRows();
    } catch (e) { toast({ title: 'Failed', description: e?.response?.data?.detail, variant: 'destructive' }); }
  };

  const applyBulk = async () => {
    if (bulk.deltaPercent === '' && bulk.deltaDollars === '') {
      return toast({ title: 'Set a delta first', variant: 'destructive' });
    }
    setBusy(true);
    try {
      const body = {
        deltaPercent: bulk.deltaPercent !== '' ? parseFloat(bulk.deltaPercent) : undefined,
        deltaDollars: bulk.deltaDollars !== '' ? parseFloat(bulk.deltaDollars) : undefined,
        applyToModifiers: bulk.applyToModifiers,
        roundingMode: bulk.roundingMode,
      };
      const r = await channelMenusAPI.bulkPrice(active, body);
      toast({ title: 'Bulk applied', description: `${r.data.updated} products` });
      loadRows();
    } catch (e) { toast({ title: 'Failed', description: e?.response?.data?.detail, variant: 'destructive' }); }
    finally { setBusy(false); }
  };

  const aiPrep = async () => {
    setBusy(true);
    try {
      const r = await channelMenusAPI.aiPrepTimes(active);
      toast({ title: 'Prep times synced', description: `Heat: ${r.data.heat} · ×${r.data.multiplier} · ${r.data.activeTickets} active tickets` });
      loadRows();
    } catch (e) { toast({ title: 'Failed', description: e?.response?.data?.detail, variant: 'destructive' }); }
    finally { setBusy(false); }
  };

  const aiDiscount = async () => {
    setBusy(true);
    try {
      const r = await channelMenusAPI.aiDiscountSlow(active, discount);
      toast({ title: `Discounted ${r.data.applied.length} slow-movers`, description: `−${r.data.discountPercent}%` });
      loadRows();
    } catch (e) { toast({ title: 'Failed', description: e?.response?.data?.detail, variant: 'destructive' }); }
    finally { setBusy(false); }
  };

  const filtered = useMemo(() => {
    const term = search.toLowerCase();
    return rows.filter(r => !term || (r.productName || '').toLowerCase().includes(term));
  }, [rows, search]);

  return (
    <div className="space-y-4" data-testid="channel-menus-page">
      <div>
        <h1 className="text-3xl font-bold flex items-center gap-2" style={{ color: theme.text }}>
          <ChefHat style={{ color: theme.primary }} /> Channel Menus
        </h1>
        <p className="text-sm text-gray-500">One menu — priced and timed per channel. Toggle availability, ± price by % or $ with rounding, sync prep times to kitchen heat, and let AI mark down your slowest sellers.</p>
      </div>

      {/* Channel chips */}
      <div className="flex flex-wrap gap-1.5" data-testid="channel-chips">
        {channels.map(c => {
          const Icon = CHANNEL_ICON[c.slug] || Globe;
          const on = active === c.slug;
          return (
            <button key={c.slug} onClick={() => setActive(c.slug)}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-full font-medium transition-colors ${on ? 'text-white' : 'bg-gray-100 text-gray-700 hover:bg-gray-200'}`}
              style={on ? { background: theme.primary } : {}}
              data-testid={`channel-${c.slug}`}>
              <Icon size={12} /> {c.label}
            </button>
          );
        })}
      </div>

      {/* Per-channel pause / resume / schedule for the active channel */}
      <ChannelPauseControl channel={active} theme={theme} />

      {/* Action bar */}
      <Card><CardContent className="p-4 space-y-3" data-testid="channel-action-bar">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {/* Bulk price */}
          <div className="border rounded p-3 bg-amber-50/30">
            <p className="text-xs font-bold uppercase tracking-widest text-gray-500 mb-2">Bulk Price Adjust</p>
            <div className="grid grid-cols-2 gap-2 mb-2">
              <Input type="number" step="0.5" placeholder="±%" value={bulk.deltaPercent} onChange={e => setBulk({ ...bulk, deltaPercent: e.target.value })} data-testid="bulk-pct" />
              <Input type="number" step="0.5" placeholder="±$" value={bulk.deltaDollars} onChange={e => setBulk({ ...bulk, deltaDollars: e.target.value })} data-testid="bulk-dollars" />
            </div>
            <div className="flex items-center justify-between gap-2 text-xs">
              <label className="flex items-center gap-1">
                <input type="checkbox" checked={bulk.applyToModifiers} onChange={e => setBulk({ ...bulk, applyToModifiers: e.target.checked })} data-testid="bulk-apply-mods" />
                Apply to modifiers
              </label>
              <select className="border rounded p-1 text-xs" value={bulk.roundingMode} onChange={e => setBulk({ ...bulk, roundingMode: e.target.value })} data-testid="bulk-rounding">
                <option value="nearest_5c">Round to 5¢</option>
                <option value="nearest_10c">Round to 10¢</option>
                <option value="psychological_99">.99 pricing</option>
                <option value="none">No rounding</option>
              </select>
              <Button size="sm" onClick={applyBulk} disabled={busy} style={{ background: theme.primary }} className="text-white" data-testid="bulk-apply-btn">Apply</Button>
            </div>
          </div>

          {/* AI tools */}
          <div className="border rounded p-3 bg-purple-50/30">
            <p className="text-xs font-bold uppercase tracking-widest text-gray-500 mb-2 flex items-center gap-1"><Sparkles size={12} style={{ color: theme.secondary }} /> AI Tools</p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              <Button size="sm" variant="outline" onClick={aiPrep} disabled={busy} className="border-amber-300" data-testid="ai-prep-btn">
                <Flame size={12} className="mr-1 text-amber-600" /> Sync Prep ⇆ Kitchen Heat
              </Button>
              <div className="flex items-center gap-1">
                <Input type="number" className="h-8 w-14 text-xs" value={discount.discountPercent} onChange={e => setDiscount({ ...discount, discountPercent: parseFloat(e.target.value) || 0 })} data-testid="discount-pct" />
                <span className="text-[10px] text-gray-500">% × bottom</span>
                <Input type="number" className="h-8 w-12 text-xs" value={discount.bottomN} onChange={e => setDiscount({ ...discount, bottomN: parseInt(e.target.value) || 0 })} data-testid="discount-n" />
                <Button size="sm" variant="outline" onClick={aiDiscount} disabled={busy} className="border-pink-300 ml-1" data-testid="ai-discount-btn">
                  <TrendingDown size={12} className="mr-1 text-pink-600" /> Discount slow-movers
                </Button>
              </div>
            </div>
            <p className="text-[10px] text-gray-500 mt-2">AI looks at the last {discount.daysWindow} days of sales and marks down the bottom {discount.bottomN} performers by {discount.discountPercent}%.</p>
          </div>
        </div>

        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={14} />
          <Input className="pl-8 h-9" placeholder="Filter items…" value={search} onChange={e => setSearch(e.target.value)} data-testid="channel-search" />
        </div>
      </CardContent></Card>

      {/* Table */}
      <Card><CardContent className="p-0 overflow-x-auto">
        <table className="w-full text-sm" data-testid="channel-table">
          <thead className="bg-gray-50 text-xs uppercase text-gray-500">
            <tr>
              <th className="px-3 py-2 text-left">Item</th>
              <th className="px-3 py-2 text-left">Category</th>
              <th className="px-3 py-2 text-right">Base</th>
              <th className="px-3 py-2 text-right">Channel Price</th>
              <th className="px-3 py-2 text-right">Mod ×</th>
              <th className="px-3 py-2 text-right">Prep (min)</th>
              <th className="px-3 py-2 text-center">On menu</th>
              <th className="px-3 py-2 text-left">AI notes</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 ? (
              <tr><td colSpan={8} className="text-center py-12 text-gray-400">No items</td></tr>
            ) : filtered.map(r => (
              <tr key={r.productId} className={`border-t hover:bg-amber-50/30 ${r.available === false ? 'opacity-60' : ''}`} data-testid={`row-${r.productId}`}>
                <td className="px-3 py-2 font-medium">{r.productName}</td>
                <td className="px-3 py-2 text-xs text-gray-600">{r.category}</td>
                <td className="px-3 py-2 text-right font-mono text-xs text-gray-500">${Number(r.basePrice || 0).toFixed(2)}</td>
                <td className="px-3 py-2 text-right">
                  <PriceCell value={r.priceOverride} placeholder={`$${Number(r.basePrice || 0).toFixed(2)}`}
                    onSave={(v) => patchRow(r.productId, { priceOverride: v })} testid={`price-${r.productId}`} />
                </td>
                <td className="px-3 py-2 text-right">
                  <NumberCell value={r.modifierPriceMultiplier} step="0.05" suffix="×"
                    onSave={(v) => patchRow(r.productId, { modifierPriceMultiplier: parseFloat(v) || 1 })} testid={`modmult-${r.productId}`} />
                </td>
                <td className="px-3 py-2 text-right">
                  <NumberCell value={r.prepTimeMin} step="1" suffix=" m" placeholder={`${r.basePrepTime}`}
                    onSave={(v) => patchRow(r.productId, { prepTimeMin: parseInt(v, 10) || 0 })} testid={`prep-${r.productId}`} />
                </td>
                <td className="px-3 py-2 text-center">
                  <button
                    onClick={() => patchRow(r.productId, { available: !r.available })}
                    className={`px-2 py-0.5 rounded text-[10px] font-bold ${r.available ? 'bg-emerald-100 text-emerald-700' : 'bg-red-100 text-red-700'}`}
                    data-testid={`avail-${r.productId}`}
                  >
                    {r.available ? 'ON' : 'OFF'}
                  </button>
                </td>
                <td className="px-3 py-2 text-xs text-gray-500 max-w-xs truncate" title={r.aiNotes || ''}>
                  {r.aiNotes && <span><Sparkles size={10} className="inline mr-1" style={{ color: theme.secondary }} />{r.aiNotes}</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent></Card>
    </div>
  );
}

function PriceCell({ value, placeholder, onSave, testid }) {
  const [editing, setEditing] = useState(false);
  const [v, setV] = useState(value ?? '');
  useEffect(() => { setV(value ?? ''); }, [value]);
  if (editing) {
    return (
      <input autoFocus type="number" step="0.05" value={v} onChange={e => setV(e.target.value)}
        onBlur={() => { setEditing(false); if (v !== '' && parseFloat(v) !== value) onSave(parseFloat(v)); }}
        onKeyDown={e => { if (e.key === 'Enter') e.target.blur(); if (e.key === 'Escape') setEditing(false); }}
        className="w-20 px-2 py-0.5 border rounded text-right font-mono text-sm"
        data-testid={testid} />
    );
  }
  return (
    <button onClick={() => setEditing(true)} className="font-mono hover:bg-amber-100 rounded px-1.5 py-0.5" data-testid={testid}>
      {value != null ? `$${Number(value).toFixed(2)}` : <span className="text-gray-400">{placeholder}</span>}
    </button>
  );
}

function NumberCell({ value, step = '1', suffix = '', placeholder, onSave, testid }) {
  const [editing, setEditing] = useState(false);
  const [v, setV] = useState(value ?? '');
  useEffect(() => { setV(value ?? ''); }, [value]);
  if (editing) {
    return (
      <input autoFocus type="number" step={step} value={v} onChange={e => setV(e.target.value)}
        onBlur={() => { setEditing(false); if (v !== '' && parseFloat(v) !== value) onSave(v); }}
        onKeyDown={e => { if (e.key === 'Enter') e.target.blur(); if (e.key === 'Escape') setEditing(false); }}
        className="w-16 px-2 py-0.5 border rounded text-right font-mono text-sm"
        data-testid={testid} />
    );
  }
  return (
    <button onClick={() => setEditing(true)} className="hover:bg-amber-100 rounded px-1.5 py-0.5 font-mono" data-testid={testid}>
      {value != null ? `${value}${suffix}` : <span className="text-gray-400">{placeholder || '—'}</span>}
    </button>
  );
}
