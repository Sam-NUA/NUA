import React, { useEffect, useState, useCallback, useMemo } from 'react';
import axios from 'axios';
import { Card, CardContent } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Input } from '../components/ui/input';
import { Textarea } from '../components/ui/textarea';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogTrigger,
} from '../components/ui/dialog';
import { toast } from 'sonner';
import {
  Beaker, Wine, RefreshCw, Plus, Package, Droplet, AlertTriangle, ClipboardCheck, Trash2,
} from 'lucide-react';
import { SecureStorageService } from '../platform';

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const H = async () => ({ Authorization: `Bearer ${await SecureStorageService.getToken()}` });

const UOM_OPTIONS = ['ml', 'l', 'g', 'kg', 'ea'];
const WASTE_REASONS = ['spillage', 'corked', 'over_pour', 'kicked', 'expired', 'other'];

const percent = (r, t) => (t > 0 ? Math.max(0, Math.min(100, (r / t) * 100)) : 0);

export default function MeasuredStock() {
  const [containers, setContainers] = useState([]);
  const [products, setProducts] = useState([]);
  const [refreshing, setRefreshing] = useState(false);

  // Setup dialog state (link a product to measured stock)
  const [setupOpen, setSetupOpen] = useState(false);
  const [selectedProductId, setSelectedProductId] = useState('');
  const [summary, setSummary] = useState(null);
  const [newSU, setNewSU] = useState({ uom: 'ml', totalMeasure: 750, costPerUnit: 20, label: '' });
  const [newSV, setNewSV] = useState({ stockUnitId: '', uom: 'ml', deductAmount: 150, label: '' });

  // Wastage modal
  const [wastageOpen, setWastageOpen] = useState(false);
  const [wastageTarget, setWastageTarget] = useState(null);
  const [wastageForm, setWastageForm] = useState({ amount: 0, uom: 'ml', reason: 'over_pour', note: '' });

  // Reconcile modal
  const [reconcileOpen, setReconcileOpen] = useState(false);
  const [reconcileTarget, setReconcileTarget] = useState(null);
  const [reconcileForm, setReconcileForm] = useState({ countedRemaining: 0, uom: 'ml' });
  const [reconcileResult, setReconcileResult] = useState(null);

  const loadContainers = useCallback(async () => {
    setRefreshing(true);
    try {
      const r = await axios.get(`${API}/measured-inventory/open-containers/all`, { headers: await H() });
      setContainers(r.data);
    } catch { toast.error('Failed to load open containers'); }
    finally { setRefreshing(false); }
  }, []);

  const loadProducts = useCallback(async () => {
    try {
      const r = await axios.get(`${API}/products`, { headers: await H() });
      setProducts(r.data);
    } catch { /* ignore */ }
  }, []);

  useEffect(() => { loadContainers(); loadProducts(); }, [loadContainers, loadProducts]);

  const loadSummary = useCallback(async (pid) => {
    if (!pid) return setSummary(null);
    try {
      const r = await axios.get(`${API}/measured-inventory/product/${pid}/summary`, { headers: await H() });
      setSummary(r.data);
    } catch { toast.error('Failed to load product summary'); }
  }, []);

  useEffect(() => { loadSummary(selectedProductId); }, [selectedProductId, loadSummary]);

  const addStockUnit = async () => {
    if (!selectedProductId) return;
    try {
      await axios.post(`${API}/measured-inventory/stock-units`, {
        productId: selectedProductId,
        uom: newSU.uom, totalMeasure: parseFloat(newSU.totalMeasure),
        costPerUnit: parseFloat(newSU.costPerUnit), label: newSU.label || null,
      }, { headers: await H() });
      toast.success('Stock unit added');
      setNewSU({ uom: 'ml', totalMeasure: 750, costPerUnit: 20, label: '' });
      loadSummary(selectedProductId);
    } catch { toast.error('Failed to save stock unit'); }
  };

  const addSellVariant = async () => {
    if (!selectedProductId || !newSV.stockUnitId) { toast.error('Pick a stock unit'); return; }
    try {
      await axios.post(`${API}/measured-inventory/sell-variants`, {
        productId: selectedProductId,
        stockUnitId: newSV.stockUnitId, uom: newSV.uom,
        deductAmount: parseFloat(newSV.deductAmount), label: newSV.label || null,
      }, { headers: await H() });
      toast.success('Sell variant added');
      setNewSV({ stockUnitId: '', uom: 'ml', deductAmount: 150, label: '' });
      loadSummary(selectedProductId);
    } catch { toast.error('Failed to save sell variant'); }
  };

  const openContainer = async (stockUnitId) => {
    try {
      await axios.post(`${API}/measured-inventory/stock-units/${stockUnitId}/open`, {}, { headers: await H() });
      toast.success('Opened new container');
      loadContainers();
      loadSummary(selectedProductId);
    } catch { toast.error('Failed to open container'); }
  };

  const submitWastage = async () => {
    if (!wastageTarget || !wastageForm.amount) return;
    try {
      await axios.post(`${API}/measured-inventory/wastage`, {
        openContainerId: wastageTarget.id,
        stockUnitId: wastageTarget.stockUnitId,
        amount: parseFloat(wastageForm.amount),
        uom: wastageForm.uom,
        reason: wastageForm.reason,
        note: wastageForm.note || null,
      }, { headers: await H() });
      toast.success('Wastage logged');
      setWastageOpen(false);
      setWastageForm({ amount: 0, uom: 'ml', reason: 'over_pour', note: '' });
      loadContainers();
    } catch { toast.error('Failed to log wastage'); }
  };

  const submitReconcile = async () => {
    if (!reconcileTarget) return;
    try {
      const r = await axios.post(
        `${API}/measured-inventory/stocktake/${reconcileTarget.stockUnitId}/reconcile`,
        { countedRemaining: parseFloat(reconcileForm.countedRemaining), uom: reconcileForm.uom },
        { headers: await H() },
      );
      setReconcileResult(r.data);
      loadContainers();
    } catch { toast.error('Reconcile failed'); }
  };

  const openWastage = (c) => { setWastageTarget(c); setWastageForm(f => ({ ...f, uom: c.stockUnit?.uom || 'ml' })); setWastageOpen(true); };
  const openReconcile = (c) => { setReconcileTarget(c); setReconcileForm({ countedRemaining: c.remainingMeasure || 0, uom: c.stockUnit?.uom || 'ml' }); setReconcileResult(null); setReconcileOpen(true); };

  const grouped = useMemo(() => {
    const g = {};
    for (const c of containers) {
      const st = c.stationId || 'Unassigned';
      g[st] = g[st] || [];
      g[st].push(c);
    }
    return g;
  }, [containers]);

  const productList = useMemo(() => products
    .filter(p => (p.name || '').length > 0)
    .sort((a, b) => (a.name || '').localeCompare(b.name || '')), [products]);

  return (
    <div className="space-y-6" data-testid="measured-stock-page">
      <div className="flex justify-between items-center flex-wrap gap-3">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-2">
            <Beaker className="text-indigo-600" /> Measured Stock
          </h1>
          <p className="text-sm text-slate-500 mt-1">
            Buy in bottles / kegs / wheels, sell in glasses / schooners / portions. Live per-container remaining, wastage, and reconcile.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={loadContainers} disabled={refreshing} data-testid="ms-refresh-btn">
            <RefreshCw size={14} className={`mr-1.5 ${refreshing ? 'animate-spin' : ''}`} /> Refresh
          </Button>
          <Dialog open={setupOpen} onOpenChange={setSetupOpen}>
            <DialogTrigger asChild>
              <Button data-testid="ms-setup-btn"><Plus size={14} className="mr-1" /> Setup product</Button>
            </DialogTrigger>
            <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto">
              <DialogHeader><DialogTitle>Set up measured stock for a product</DialogTitle></DialogHeader>
              <div className="space-y-4">
                <div>
                  <label className="text-xs text-slate-500">Product</label>
                  <Select value={selectedProductId} onValueChange={setSelectedProductId}>
                    <SelectTrigger data-testid="ms-product-select"><SelectValue placeholder="Choose a product…" /></SelectTrigger>
                    <SelectContent className="max-h-64">
                      {productList.map(p => <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </div>

                {selectedProductId && (
                  <>
                    {/* Stock units section */}
                    <div className="border rounded-lg p-4">
                      <div className="flex justify-between items-center mb-2">
                        <h3 className="font-semibold text-sm">Stock units (what you buy)</h3>
                        <Badge variant="outline">{summary?.stockUnits?.length || 0}</Badge>
                      </div>
                      {(summary?.stockUnits || []).map(su => (
                        <div key={su.id} className="flex justify-between items-center text-xs py-1 border-b last:border-b-0" data-testid={`su-row-${su.id}`}>
                          <span>{su.label || `${su.totalMeasure}${su.uom}`} @ ${su.costPerUnit}</span>
                          <Button size="sm" variant="outline" className="h-6 text-[10px]" onClick={() => openContainer(su.id)} data-testid={`open-su-${su.id}`}>
                            Open new
                          </Button>
                        </div>
                      ))}
                      <div className="grid grid-cols-5 gap-2 mt-3">
                        <Input placeholder="Label" value={newSU.label} onChange={e => setNewSU(f => ({ ...f, label: e.target.value }))} data-testid="ms-su-label" />
                        <Input type="number" placeholder="Total" value={newSU.totalMeasure} onChange={e => setNewSU(f => ({ ...f, totalMeasure: e.target.value }))} data-testid="ms-su-total" />
                        <Select value={newSU.uom} onValueChange={v => setNewSU(f => ({ ...f, uom: v }))}>
                          <SelectTrigger data-testid="ms-su-uom"><SelectValue /></SelectTrigger>
                          <SelectContent>{UOM_OPTIONS.map(u => <SelectItem key={u} value={u}>{u}</SelectItem>)}</SelectContent>
                        </Select>
                        <Input type="number" placeholder="Cost" value={newSU.costPerUnit} onChange={e => setNewSU(f => ({ ...f, costPerUnit: e.target.value }))} data-testid="ms-su-cost" />
                        <Button size="sm" onClick={addStockUnit} data-testid="ms-add-su"><Plus size={12} /></Button>
                      </div>
                    </div>

                    {/* Sell variants section */}
                    <div className="border rounded-lg p-4">
                      <div className="flex justify-between items-center mb-2">
                        <h3 className="font-semibold text-sm">Sell variants (how you sell it)</h3>
                        <Badge variant="outline">{summary?.sellVariants?.length || 0}</Badge>
                      </div>
                      {(summary?.sellVariants || []).map(sv => (
                        <div key={sv.id} className="text-xs py-1 border-b last:border-b-0" data-testid={`sv-row-${sv.id}`}>
                          {sv.label || `${sv.deductAmount}${sv.uom}`} → deducts from {(summary.stockUnits.find(s => s.id === sv.stockUnitId) || {}).label || 'stock'}
                        </div>
                      ))}
                      <div className="grid grid-cols-5 gap-2 mt-3">
                        <Input placeholder="Label" value={newSV.label} onChange={e => setNewSV(f => ({ ...f, label: e.target.value }))} data-testid="ms-sv-label" />
                        <Input type="number" placeholder="Deduct" value={newSV.deductAmount} onChange={e => setNewSV(f => ({ ...f, deductAmount: e.target.value }))} data-testid="ms-sv-amount" />
                        <Select value={newSV.uom} onValueChange={v => setNewSV(f => ({ ...f, uom: v }))}>
                          <SelectTrigger data-testid="ms-sv-uom"><SelectValue /></SelectTrigger>
                          <SelectContent>{UOM_OPTIONS.map(u => <SelectItem key={u} value={u}>{u}</SelectItem>)}</SelectContent>
                        </Select>
                        <Select value={newSV.stockUnitId} onValueChange={v => setNewSV(f => ({ ...f, stockUnitId: v }))}>
                          <SelectTrigger data-testid="ms-sv-su"><SelectValue placeholder="Stock unit" /></SelectTrigger>
                          <SelectContent>
                            {(summary?.stockUnits || []).map(su => <SelectItem key={su.id} value={su.id}>{su.label || `${su.totalMeasure}${su.uom}`}</SelectItem>)}
                          </SelectContent>
                        </Select>
                        <Button size="sm" onClick={addSellVariant} data-testid="ms-add-sv"><Plus size={12} /></Button>
                      </div>
                    </div>

                    {summary?.reorderAvailable?.measured && (
                      <div className="text-xs bg-indigo-50 border border-indigo-100 rounded p-2">
                        Available for reorder logic: <b>{summary.reorderAvailable.equivalent}</b> equivalent units
                        &nbsp;(sealed {summary.reorderAvailable.sealed}, open {summary.reorderAvailable.partial}).
                      </div>
                    )}
                  </>
                )}
              </div>
              <DialogFooter>
                <Button variant="outline" onClick={() => setSetupOpen(false)}>Done</Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </div>
      </div>

      {/* Live open containers */}
      {containers.length === 0 && (
        <Card><CardContent className="p-12 text-center text-sm text-slate-500">
          <Wine className="mx-auto mb-2 opacity-40" size={28} />
          No open containers yet. Set up a product to link stock units and sell variants, then open your first bottle / keg / tub.
        </CardContent></Card>
      )}

      {Object.entries(grouped).map(([station, list]) => (
        <div key={station}>
          <p className="text-xs uppercase tracking-wider text-slate-400 mb-2">{station}</p>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {list.map(c => {
              const total = c.stockUnit?.totalMeasure || 0;
              const remaining = c.remainingMeasure || 0;
              const p = percent(remaining, total);
              const tone = p < 15 ? 'bg-rose-500' : p < 35 ? 'bg-amber-500' : 'bg-emerald-500';
              return (
                <Card key={c.id} data-testid={`container-${c.id}`}>
                  <CardContent className="p-4">
                    <div className="flex justify-between items-start gap-2 mb-2">
                      <div>
                        <p className="font-semibold text-sm">{c.product?.name || 'Unknown product'}</p>
                        <p className="text-[10px] text-slate-500">{c.stockUnit?.label || `${total}${c.stockUnit?.uom || ''}`}</p>
                      </div>
                      <Badge variant="outline" className="text-[10px]">
                        <Package size={10} className="mr-1" /> {c.stationId || 'no station'}
                      </Badge>
                    </div>
                    <div className="mt-3">
                      <div className="flex justify-between text-xs mb-1">
                        <span className="font-mono">{remaining.toFixed(1)}{c.stockUnit?.uom} left</span>
                        {c.estimatedServes && (
                          <span className="text-slate-500">
                            <Droplet size={10} className="inline mr-0.5" />
                            {c.estimatedServes.count}× {c.estimatedServes.label}
                          </span>
                        )}
                      </div>
                      <div className="h-2 bg-slate-100 rounded-full overflow-hidden">
                        <div className={`h-full transition-all ${tone}`} style={{ width: `${p}%` }} />
                      </div>
                      <p className="text-[10px] text-slate-400 mt-1">{p.toFixed(0)}% remaining · opened {new Date(c.openedAt).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })} by {c.openedBy}</p>
                    </div>
                    <div className="flex gap-1.5 mt-3 pt-2 border-t">
                      <Button size="sm" variant="outline" className="h-7 text-[11px]" onClick={() => openContainer(c.stockUnitId)} data-testid={`open-new-${c.id}`}>
                        <Plus size={12} className="mr-1" /> Open new
                      </Button>
                      <Button size="sm" variant="outline" className="h-7 text-[11px] text-orange-600" onClick={() => openWastage(c)} data-testid={`waste-${c.id}`}>
                        <Trash2 size={12} className="mr-1" /> Wastage
                      </Button>
                      <Button size="sm" variant="outline" className="h-7 text-[11px]" onClick={() => openReconcile(c)} data-testid={`reconcile-${c.id}`}>
                        <ClipboardCheck size={12} className="mr-1" /> Count
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              );
            })}
          </div>
        </div>
      ))}

      {/* Wastage modal */}
      <Dialog open={wastageOpen} onOpenChange={setWastageOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>Log wastage</DialogTitle></DialogHeader>
          {wastageTarget && (
            <div className="space-y-3 text-sm">
              <p className="text-xs text-slate-500">
                Container: {wastageTarget.product?.name} · {wastageTarget.remainingMeasure?.toFixed(1)}{wastageTarget.stockUnit?.uom} remaining
              </p>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs text-slate-500">Amount</label>
                  <Input type="number" value={wastageForm.amount} onChange={e => setWastageForm(f => ({ ...f, amount: e.target.value }))} data-testid="waste-amount" />
                </div>
                <div>
                  <label className="text-xs text-slate-500">UoM</label>
                  <Select value={wastageForm.uom} onValueChange={v => setWastageForm(f => ({ ...f, uom: v }))}>
                    <SelectTrigger data-testid="waste-uom"><SelectValue /></SelectTrigger>
                    <SelectContent>{UOM_OPTIONS.map(u => <SelectItem key={u} value={u}>{u}</SelectItem>)}</SelectContent>
                  </Select>
                </div>
              </div>
              <div>
                <label className="text-xs text-slate-500">Reason</label>
                <Select value={wastageForm.reason} onValueChange={v => setWastageForm(f => ({ ...f, reason: v }))}>
                  <SelectTrigger data-testid="waste-reason"><SelectValue /></SelectTrigger>
                  <SelectContent>{WASTE_REASONS.map(r => <SelectItem key={r} value={r}>{r.replace('_', ' ')}</SelectItem>)}</SelectContent>
                </Select>
              </div>
              <div>
                <label className="text-xs text-slate-500">Note (optional)</label>
                <Textarea rows={2} value={wastageForm.note} onChange={e => setWastageForm(f => ({ ...f, note: e.target.value }))} data-testid="waste-note" />
              </div>
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setWastageOpen(false)}>Cancel</Button>
            <Button onClick={submitWastage} data-testid="save-wastage">Log wastage</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Reconcile modal */}
      <Dialog open={reconcileOpen} onOpenChange={setReconcileOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>Stocktake — Reconcile</DialogTitle></DialogHeader>
          {reconcileTarget && (
            <div className="space-y-3 text-sm">
              <p className="text-xs text-slate-500">
                Product: {reconcileTarget.product?.name} · System says {reconcileTarget.remainingMeasure?.toFixed(1)}{reconcileTarget.stockUnit?.uom} remaining
              </p>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs text-slate-500">Counted</label>
                  <Input type="number" value={reconcileForm.countedRemaining} onChange={e => setReconcileForm(f => ({ ...f, countedRemaining: e.target.value }))} data-testid="reconcile-counted" />
                </div>
                <div>
                  <label className="text-xs text-slate-500">UoM</label>
                  <Select value={reconcileForm.uom} onValueChange={v => setReconcileForm(f => ({ ...f, uom: v }))}>
                    <SelectTrigger data-testid="reconcile-uom"><SelectValue /></SelectTrigger>
                    <SelectContent>{UOM_OPTIONS.map(u => <SelectItem key={u} value={u}>{u}</SelectItem>)}</SelectContent>
                  </Select>
                </div>
              </div>
              {reconcileResult && (
                <div className={`p-3 rounded border text-xs ${reconcileResult.flagged ? 'bg-rose-50 border-rose-200' : 'bg-emerald-50 border-emerald-200'}`} data-testid="reconcile-result">
                  <div className="flex items-center gap-2 mb-1">
                    {reconcileResult.flagged
                      ? <AlertTriangle size={14} className="text-rose-600" />
                      : <ClipboardCheck size={14} className="text-emerald-600" />}
                    <b>{reconcileResult.flagged ? 'Variance flagged' : 'Within tolerance'}</b>
                  </div>
                  Theoretical {reconcileResult.theoretical}{reconcileResult.uom} — Counted {reconcileResult.counted}{reconcileResult.uom} · Variance {reconcileResult.variance}{reconcileResult.uom} ({(reconcileResult.variancePct * 100).toFixed(1)}%)
                </div>
              )}
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setReconcileOpen(false)}>Close</Button>
            <Button onClick={submitReconcile} data-testid="save-reconcile">Reconcile</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
