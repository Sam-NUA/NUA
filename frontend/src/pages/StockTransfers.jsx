import React, { useEffect, useMemo, useState } from 'react';
import { ArrowLeftRight, Truck, Check, X, Plus } from 'lucide-react';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Card, CardContent } from '../components/ui/card';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '../components/ui/dialog';
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from '../components/ui/select';
import { Badge } from '../components/ui/badge';
import { useTheme } from '../contexts/ThemeContext';
import { productsAPI, locationsAPI, stockTransfersAPI } from '../services/api';
import { toast } from 'sonner';
import { DialogService } from '../platform';

const BLANK_FORM = { productId: '', fromLocation: '', toLocation: '', quantity: '', notes: '' };

export default function StockTransfers() {
  const { theme } = useTheme();
  const [transfers, setTransfers] = useState([]);
  const [products, setProducts] = useState([]);
  const [locations, setLocations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState('in_transit');
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState(BLANK_FORM);
  const [saving, setSaving] = useState(false);
  const [busyId, setBusyId] = useState(null);

  const load = () => {
    setLoading(true);
    Promise.all([
      stockTransfersAPI.list(statusFilter === 'all' ? {} : { status: statusFilter }),
      productsAPI.getAll(),
      locationsAPI.getAll(),
    ]).then(([t, p, l]) => {
      setTransfers(t.data || []);
      setProducts(p.data || []);
      setLocations(l.data || []);
    }).catch(() => toast.error('Failed to load stock transfers')).finally(() => setLoading(false));
  };
  useEffect(load, [statusFilter]);  

  // Every place a product is actually stocked — its own `locations` list
  // plus whatever it already has a stockByLocation entry for (a location
  // it was zero-stocked at initially still needs to be a valid transfer
  // source/destination once stock has moved through it before).
  const selectedProduct = products.find(p => p.id === form.productId);
  const locationOptions = useMemo(() => {
    const names = new Set(locations.map(l => l.name));
    if (selectedProduct) {
      (selectedProduct.locations || []).forEach(n => names.add(n));
      Object.keys(selectedProduct.stockByLocation || {}).forEach(n => names.add(n));
    }
    return Array.from(names);
  }, [locations, selectedProduct]);

  const stockAtFrom = selectedProduct && form.fromLocation
    ? (selectedProduct.stockByLocation || {})[form.fromLocation] || 0
    : null;

  const createTransfer = async () => {
    if (!form.productId || !form.fromLocation || !form.toLocation || !form.quantity) {
      toast.error('Fill in product, both locations, and a quantity'); return;
    }
    if (form.fromLocation === form.toLocation) { toast.error('Source and destination must differ'); return; }
    setSaving(true);
    try {
      await stockTransfersAPI.create({ ...form, quantity: parseInt(form.quantity) });
      toast.success('Transfer created — stock is now in transit');
      setShowCreate(false);
      setForm(BLANK_FORM);
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Failed to create transfer');
    } finally { setSaving(false); }
  };

  const receiveTransfer = async (t) => {
    setBusyId(t.id);
    try {
      await stockTransfersAPI.receive(t.id);
      toast.success(`${t.quantity}× ${t.productName} received at ${t.toLocation}`);
      load();
    } catch (e) { toast.error(e.response?.data?.detail || 'Failed to receive transfer'); }
    finally { setBusyId(null); }
  };

  const cancelTransfer = async (t) => {
    if (!await DialogService.confirm(`Cancel this transfer and return stock to ${t.fromLocation}?`)) return;
    setBusyId(t.id);
    try {
      await stockTransfersAPI.cancel(t.id);
      toast.success('Transfer cancelled');
      load();
    } catch (e) { toast.error(e.response?.data?.detail || 'Failed to cancel transfer'); }
    finally { setBusyId(null); }
  };

  const statusBadge = (status) => {
    if (status === 'in_transit') return <Badge className="bg-amber-100 text-amber-700 hover:bg-amber-100">In Transit</Badge>;
    if (status === 'received') return <Badge className="bg-emerald-100 text-emerald-700 hover:bg-emerald-100">Received</Badge>;
    return <Badge variant="secondary">Cancelled</Badge>;
  };

  return (
    <div className="space-y-6" data-testid="stock-transfers-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2" style={{ color: theme.text }}>
            <ArrowLeftRight size={24} /> Stock Transfers
          </h1>
          <p className="text-sm text-gray-500">Move stock between locations — a transfer stays "in transit" until confirmed received.</p>
        </div>
        <Button onClick={() => { setForm(BLANK_FORM); setShowCreate(true); }} data-testid="new-transfer-btn">
          <Plus size={14} className="mr-1.5" /> New Transfer
        </Button>
      </div>

      <div className="flex gap-1.5">
        {['in_transit', 'received', 'cancelled', 'all'].map(s => (
          <button key={s} onClick={() => setStatusFilter(s)}
            className={`px-3 py-1.5 text-xs font-medium rounded-full ${statusFilter === s ? 'text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'}`}
            style={statusFilter === s ? { backgroundColor: theme.primary } : {}}
            data-testid={`filter-${s}`}>
            {s === 'in_transit' ? 'In Transit' : s === 'all' ? 'All' : s[0].toUpperCase() + s.slice(1)}
          </button>
        ))}
      </div>

      {loading ? (
        <p className="text-sm text-gray-400 text-center py-12">Loading…</p>
      ) : transfers.length === 0 ? (
        <Card><CardContent className="p-12 text-center text-gray-400">
          No {statusFilter === 'all' ? '' : statusFilter.replace('_', ' ')} transfers.
        </CardContent></Card>
      ) : (
        <div className="space-y-2">
          {transfers.map(t => (
            <Card key={t.id} data-testid={`transfer-row-${t.id}`}>
              <CardContent className="p-4 flex items-center justify-between gap-4">
                <div className="flex items-center gap-3">
                  <Truck size={18} className="text-gray-400" />
                  <div>
                    <p className="font-medium text-sm">{t.quantity}× {t.productName}</p>
                    <p className="text-xs text-gray-500">{t.fromLocation} → {t.toLocation} · requested by {t.requestedByName || '—'}</p>
                    {t.notes && <p className="text-xs text-gray-400 italic mt-0.5">{t.notes}</p>}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {statusBadge(t.status)}
                  {t.status === 'in_transit' && (
                    <>
                      <Button size="sm" variant="outline" disabled={busyId === t.id} onClick={() => receiveTransfer(t)} data-testid={`receive-transfer-${t.id}`}>
                        <Check size={13} className="mr-1" /> Receive
                      </Button>
                      <Button size="sm" variant="ghost" disabled={busyId === t.id} onClick={() => cancelTransfer(t)} data-testid={`cancel-transfer-${t.id}`}>
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

      <Dialog open={showCreate} onOpenChange={setShowCreate}>
        <DialogContent data-testid="create-transfer-dialog">
          <DialogHeader><DialogTitle>New Stock Transfer</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div>
              <label className="text-xs font-medium text-gray-500 mb-1 block">Product</label>
              <Select value={form.productId} onValueChange={v => setForm({ ...form, productId: v, fromLocation: '', toLocation: '' })}>
                <SelectTrigger data-testid="transfer-product-select"><SelectValue placeholder="Choose a product…" /></SelectTrigger>
                <SelectContent>
                  {products.filter(p => !p.hasVariants).map(p => <SelectItem key={p.id} value={p.id}>{p.name}{p.sku ? ` (${p.sku})` : ''}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs font-medium text-gray-500 mb-1 block">From</label>
                <Select value={form.fromLocation} onValueChange={v => setForm({ ...form, fromLocation: v })} disabled={!form.productId}>
                  <SelectTrigger data-testid="transfer-from-select"><SelectValue placeholder="Source" /></SelectTrigger>
                  <SelectContent>
                    {locationOptions.map(n => <SelectItem key={n} value={n}>{n}</SelectItem>)}
                  </SelectContent>
                </Select>
                {stockAtFrom !== null && <p className="text-[11px] text-gray-400 mt-1">{stockAtFrom} in stock there</p>}
              </div>
              <div>
                <label className="text-xs font-medium text-gray-500 mb-1 block">To</label>
                <Select value={form.toLocation} onValueChange={v => setForm({ ...form, toLocation: v })} disabled={!form.productId}>
                  <SelectTrigger data-testid="transfer-to-select"><SelectValue placeholder="Destination" /></SelectTrigger>
                  <SelectContent>
                    {locationOptions.map(n => <SelectItem key={n} value={n}>{n}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <Input type="number" placeholder="Quantity" value={form.quantity} onChange={e => setForm({ ...form, quantity: e.target.value })} data-testid="transfer-quantity-input" />
            <Input placeholder="Notes (optional)" value={form.notes} onChange={e => setForm({ ...form, notes: e.target.value })} data-testid="transfer-notes-input" />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowCreate(false)}>Cancel</Button>
            <Button onClick={createTransfer} disabled={saving} data-testid="save-transfer-btn">{saving ? 'Creating…' : 'Create Transfer'}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
