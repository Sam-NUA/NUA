// Re-export — full inventory + accounting suite lives in InventoryAccounting.jsx.
import React, { useEffect, useMemo, useState } from 'react';
import { Beaker, AlertTriangle, Plus, Save, Download, Trash2, Edit, RefreshCw, ClipboardList } from 'lucide-react';
import { Card, CardContent } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Badge } from '../components/ui/badge';
import { useTheme } from '../contexts/ThemeContext';
import { inventoryAPI, productsAPI, aiPantryAPI, awardsAPI, staffMgmtAPI } from '../services/api';
import { useToast } from '../hooks/use-toast';
import { DialogService } from '../platform';

const BASE_UNITS = ['g', 'mL', 'ea'];
const ALL_UNITS = { g: ['g', 'kg', 'mg'], mL: ['mL', 'L', 'cl'], ea: ['ea', 'box', 'case', 'pack'] };

export default function InventoryAccounting() {
  const { theme } = useTheme();
  const [tab, setTab] = useState('ingredients');
  return (
    <div className="space-y-5" data-testid="inventory-page">
      <div>
        <h1 className="text-3xl font-bold flex items-center gap-2" style={{ color: theme.text }}>
          <Beaker className="text-emerald-600" /> Inventory & Accounting
        </h1>
        <p className="text-sm text-gray-500">Ingredients · Recipes · Stock-take · BAS / GST</p>
      </div>
      <div className="flex gap-2 overflow-x-auto pb-1">
        {[
          { k: 'ingredients', label: 'Ingredients' },
          { k: 'recipes', label: 'Recipes' },
          { k: 'invoices', label: 'Invoices → Stock' },
          { k: 'stocktake', label: 'Stock-take' },
          { k: 'bas', label: 'BAS / GST' },
          { k: 'super', label: 'Super (Awards)' },
        ].map(t => (
          <button key={t.k} onClick={() => setTab(t.k)}
            className={`px-4 py-2 rounded-full text-sm font-semibold whitespace-nowrap transition ${tab === t.k ? 'text-white shadow' : 'bg-white border hover:border-gray-400'}`}
            style={tab === t.k ? { background: theme.primary } : {}}
            data-testid={`inv-tab-${t.k}`}>{t.label}</button>
        ))}
      </div>
      {tab === 'ingredients' && <IngredientsPanel />}
      {tab === 'recipes' && <RecipesPanel />}
      {tab === 'invoices' && <InvoiceAssignmentPanel />}
      {tab === 'stocktake' && <StockTakePanel />}
      {tab === 'bas' && <BASPanel />}
      {tab === 'super' && <SuperAwardsPanel />}
    </div>
  );
}

const BLANK_ING = { name: '', category: 'Other', baseUnit: 'g', stock: 0, unitCost: 0, gstInclusive: true, reorderLevel: 0, reorderQty: 0, supplierName: '' };

function IngredientsPanel() {
  const { theme } = useTheme(); const { toast } = useToast();
  const [rows, setRows] = useState([]);
  const [low, setLow] = useState([]);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(BLANK_ING);
  const load = async () => {
    const [a, b] = await Promise.all([inventoryAPI.listIngredients(), inventoryAPI.lowStock()]);
    setRows(a.data || []); setLow(b.data || []);
  };
  useEffect(() => { load().catch(() => {}); }, []);
  const save = async () => {
    try {
      if (editing) await inventoryAPI.updateIngredient(editing.id, form);
      else await inventoryAPI.createIngredient(form);
      toast({ title: 'Saved' }); setEditing(null); setForm(BLANK_ING); load();
    } catch (e) { toast({ title: 'Failed', description: e?.response?.data?.detail, variant: 'destructive' }); }
  };
  const del = async (id) => {
    if (!await DialogService.confirm('Delete ingredient?')) return;
    try { await inventoryAPI.deleteIngredient(id); load(); }
    catch (e) { toast({ title: 'Cannot delete', description: e?.response?.data?.detail, variant: 'destructive' }); }
  };
  return (
    <div className="space-y-4">
      {low.length > 0 && (
        <Card className="border-amber-300 bg-amber-50">
          <CardContent className="p-4" data-testid="low-stock-banner">
            <p className="text-sm font-bold text-amber-800 flex items-center gap-1"><AlertTriangle size={14} /> Low stock ({low.length})</p>
            <ul className="text-xs mt-1 text-amber-700 grid grid-cols-2 gap-1">
              {low.map(l => <li key={l.id}>· {l.name}: {Number(l.stock).toFixed(1)}{l.baseUnit} (reorder ≤ {l.reorderLevel}{l.baseUnit})</li>)}
            </ul>
          </CardContent>
        </Card>
      )}
      <Card><CardContent className="p-4">
        <div className="grid grid-cols-2 md:grid-cols-7 gap-2 items-end" data-testid="ingredient-form">
          <Input placeholder="Name" value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} data-testid="ing-name" />
          <Input placeholder="Category" value={form.category} onChange={e => setForm({ ...form, category: e.target.value })} />
          <select className="p-2 border rounded text-sm" value={form.baseUnit} onChange={e => setForm({ ...form, baseUnit: e.target.value })} data-testid="ing-baseunit">
            {BASE_UNITS.map(u => <option key={u} value={u}>{u}</option>)}
          </select>
          <Input type="number" placeholder="Stock" value={form.stock} onChange={e => setForm({ ...form, stock: parseFloat(e.target.value) || 0 })} data-testid="ing-stock" />
          <Input type="number" placeholder="$/unit" step="0.01" value={form.unitCost} onChange={e => setForm({ ...form, unitCost: parseFloat(e.target.value) || 0 })} data-testid="ing-cost" />
          <Input type="number" placeholder="Reorder ≤" value={form.reorderLevel} onChange={e => setForm({ ...form, reorderLevel: parseFloat(e.target.value) || 0 })} />
          <Button onClick={save} style={{ background: theme.primary }} data-testid="save-ing-btn">
            {editing ? <><Save size={14} className="mr-1" /> Update</> : <><Plus size={14} className="mr-1" /> Add</>}
          </Button>
        </div>
      </CardContent></Card>
      <Card><CardContent className="p-0">
        <table className="w-full text-sm" data-testid="ingredients-table">
          <thead className="bg-gray-50 text-xs uppercase text-gray-500">
            <tr><th className="text-left p-2">Name</th><th>Category</th><th>Stock</th><th>$ / base</th><th>Reorder ≤</th><th>Supplier</th><th></th></tr>
          </thead>
          <tbody>
            {rows.map(r => (
              <tr key={r.id} className="border-t hover:bg-gray-50" data-testid={`ing-row-${r.id}`}>
                <td className="p-2 font-medium">{r.name}</td>
                <td className="text-center text-xs">{r.category}</td>
                <td className="text-center text-xs">{Number(r.stock || 0).toFixed(1)}{r.baseUnit}</td>
                <td className="text-center text-xs">${Number(r.unitCost || 0).toFixed(4)}</td>
                <td className="text-center text-xs">{r.reorderLevel || '—'}</td>
                <td className="text-center text-xs">{r.supplierName || '—'}</td>
                <td className="text-right p-2">
                  <Button size="sm" variant="ghost" onClick={() => { setEditing(r); setForm(r); }}><Edit size={12} /></Button>
                  <Button size="sm" variant="ghost" className="text-red-500" onClick={() => del(r.id)}><Trash2 size={12} /></Button>
                </td>
              </tr>
            ))}
            {rows.length === 0 && <tr><td colSpan="7" className="text-center text-gray-400 py-6">No ingredients yet — add one above</td></tr>}
          </tbody>
        </table>
      </CardContent></Card>
    </div>
  );
}

function RecipesPanel() {
  const { theme } = useTheme(); const { toast } = useToast();
  const [products, setProducts] = useState([]);
  const [ingredients, setIngredients] = useState([]);
  const [selected, setSelected] = useState(null);
  const [lines, setLines] = useState([]);
  const [recipeCost, setRecipeCost] = useState(0);
  useEffect(() => {
    Promise.all([productsAPI.getAll(), inventoryAPI.listIngredients()])
      .then(([p, i]) => { setProducts(p.data || []); setIngredients(i.data || []); });
  }, []);
  const openProduct = async (p) => {
    setSelected(p);
    const r = await inventoryAPI.getRecipe(p.id);
    setLines(r.data?.lines || []); setRecipeCost(r.data?.computedCost || 0);
  };
  const addLine = () => setLines(l => [...l, { ingredientId: '', qty: 0, unit: 'g' }]);
  const upd = (i, key, v) => setLines(l => l.map((x, idx) => idx === i ? { ...x, [key]: v } : x));
  const save = async () => {
    try {
      const r = await inventoryAPI.saveRecipe(selected.id, { lines });
      toast({ title: 'Recipe saved', description: `New cost $${Number(r.data.computedCost || 0).toFixed(4)}` });
      setRecipeCost(r.data.computedCost || 0);
      productsAPI.getAll().then(p => setProducts(p.data || []));
    } catch (e) { toast({ title: 'Failed', description: e?.response?.data?.detail, variant: 'destructive' }); }
  };
  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
      <Card className="lg:col-span-1"><CardContent className="p-0">
        <div className="px-4 py-3 border-b font-bold text-sm">Products ({products.length})</div>
        <div className="max-h-[60vh] overflow-y-auto">
          {products.map(p => (
            <button key={p.id} onClick={() => openProduct(p)}
              className={`w-full text-left px-4 py-2 border-b text-sm hover:bg-gray-50 ${selected?.id === p.id ? 'bg-purple-50' : ''}`}
              data-testid={`recipe-prod-${p.id}`}>
              <span className="font-medium">{p.name}</span>
              <span className="block text-[10px] text-gray-400">{p.category} · cost ${Number(p.cost || 0).toFixed(2)}</span>
            </button>
          ))}
        </div>
      </CardContent></Card>
      <Card className="lg:col-span-2"><CardContent className="p-4">
        {!selected ? <p className="text-center text-gray-400 py-12">Pick a product on the left</p> : (
          <div className="space-y-3" data-testid="recipe-editor">
            <div className="flex justify-between items-center">
              <div>
                <h3 className="font-bold">{selected.name}</h3>
                <p className="text-xs text-gray-500">Computed cost: ${Number(recipeCost || 0).toFixed(4)} · current price ${Number(selected.price).toFixed(2)}</p>
              </div>
              <Button onClick={save} style={{ background: theme.primary }} data-testid="save-recipe-btn"><Save size={14} className="mr-1" /> Save recipe</Button>
            </div>
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-xs uppercase text-gray-500"><tr><th className="text-left p-2">Ingredient</th><th>Qty</th><th>Unit</th><th></th></tr></thead>
              <tbody>
                {lines.map((l, i) => {
                  const ing = ingredients.find(x => x.id === l.ingredientId);
                  const units = ing ? ALL_UNITS[ing.baseUnit] || ['ea'] : ['g','kg','mL','L','ea'];
                  return (
                    <tr key={i} className="border-t" data-testid={`recipe-line-${i}`}>
                      <td className="p-2">
                        <select className="p-1.5 border rounded text-sm w-full" value={l.ingredientId} onChange={e => upd(i, 'ingredientId', e.target.value)} data-testid={`recipe-ing-${i}`}>
                          <option value="">Select ingredient…</option>
                          {ingredients.map(x => <option key={x.id} value={x.id}>{x.name} ({x.baseUnit})</option>)}
                        </select>
                      </td>
                      <td className="p-2"><Input type="number" step="0.01" value={l.qty} onChange={e => upd(i, 'qty', parseFloat(e.target.value) || 0)} data-testid={`recipe-qty-${i}`} /></td>
                      <td className="p-2">
                        <select className="p-1.5 border rounded text-sm" value={l.unit} onChange={e => upd(i, 'unit', e.target.value)} data-testid={`recipe-unit-${i}`}>
                          {units.map(u => <option key={u} value={u}>{u}</option>)}
                        </select>
                      </td>
                      <td className="p-2 text-right"><Button size="sm" variant="ghost" className="text-red-500" onClick={() => setLines(l => l.filter((_, idx) => idx !== i))}><Trash2 size={11} /></Button></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <Button variant="outline" onClick={addLine} data-testid="add-recipe-line-btn"><Plus size={12} className="mr-1" /> Add ingredient line</Button>
          </div>
        )}
      </CardContent></Card>
    </div>
  );
}

function InvoiceAssignmentPanel() {
  const { theme } = useTheme(); const { toast } = useToast();
  const [invoices, setInvoices] = useState([]);
  const [ingredients, setIngredients] = useState([]);
  const [opened, setOpened] = useState(null);
  const [assignments, setAssignments] = useState([]);
  const [priceReview, setPriceReview] = useState(null);
  const [priceDraft, setPriceDraft] = useState({});
  const [savingPrices, setSavingPrices] = useState(false);
  useEffect(() => {
    aiPantryAPI.listInvoices().then(r => setInvoices(r.data || []));
    inventoryAPI.listIngredients().then(r => setIngredients(r.data || []));
  }, []);
  const openInvoice = (inv) => {
    setOpened(inv);
    const initial = (inv.matches || []).map(m => ({
      ingredientId: '',
      qty: m.lineItem?.quantity || 0,
      unit: m.lineItem?.unit || 'kg',
      lineTotal: m.lineItem?.totalCost || 0,
      lineName: m.lineItem?.name,
    }));
    setAssignments(initial);
  };
  const upd = (i, key, v) => setAssignments(a => a.map((x, idx) => idx === i ? { ...x, [key]: v } : x));
  const apply = async () => {
    const filtered = assignments.filter(a => a.ingredientId);
    if (filtered.length === 0) return toast({ title: 'Pick at least one ingredient', variant: 'destructive' });
    try {
      const r = await inventoryAPI.assignInvoiceToStock(opened.id, filtered);
      toast({ title: 'Stock updated', description: `${r.data.movements.length} ingredients credited · ${r.data.recipesRolledUp} recipes re-costed` });
      aiPantryAPI.listInvoices().then(r => setInvoices(r.data || []));
      if ((r.data.priceReview || []).length > 0) {
        setPriceReview(r.data.priceReview);
        setPriceDraft(Object.fromEntries(r.data.priceReview.map(p => [p.productId, p.price])));
      } else {
        setOpened(null);
      }
    } catch (e) { toast({ title: 'Failed', description: e?.response?.data?.detail, variant: 'destructive' }); }
  };

  const savePrices = async () => {
    setSavingPrices(true);
    try {
      await Promise.all(priceReview.map(p => {
        const newPrice = parseFloat(priceDraft[p.productId]);
        return Number.isFinite(newPrice) && newPrice !== p.price
          ? productsAPI.update(p.productId, { price: newPrice })
          : Promise.resolve();
      }));
      toast({ title: 'Prices updated' });
    } catch { toast({ title: 'Some prices failed to save', variant: 'destructive' }); }
    finally {
      setSavingPrices(false);
      setPriceReview(null);
      setOpened(null);
    }
  };
  return (
    <Card><CardContent className="p-4">
      {!opened ? (
        <>
          <h3 className="font-bold mb-3">Pick an invoice to assign to ingredients</h3>
          {invoices.length === 0 ? (
            <p className="text-sm text-gray-400 text-center py-6">No invoices yet — upload one from the AI Pantry page first.</p>
          ) : (
            <div className="space-y-2" data-testid="invoice-list">
              {invoices.map(inv => (
                <button key={inv.id} onClick={() => openInvoice(inv)}
                  className="w-full text-left p-3 border rounded-lg hover:border-purple-300 hover:bg-purple-50 transition"
                  data-testid={`assign-invoice-${inv.id}`}>
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="font-medium text-sm">{inv.parsed?.supplier || 'Unknown supplier'} · {inv.parsed?.invoiceNumber || '—'}</p>
                      <p className="text-xs text-gray-500">{inv.matches?.length || 0} lines · ${inv.parsed?.total ?? '?'}</p>
                    </div>
                    {inv.stockAssignedAt && <Badge className="bg-green-100 text-green-700">Assigned</Badge>}
                  </div>
                </button>
              ))}
            </div>
          )}
        </>
      ) : priceReview ? (
        <>
          <div className="flex justify-between items-center mb-3">
            <div>
              <h3 className="font-bold">Cost changed on {priceReview.length} product{priceReview.length === 1 ? '' : 's'}</h3>
              <p className="text-xs text-gray-500">Receiving this stock moved the recipe cost — review the margin and re-price now if needed, or leave the price as-is.</p>
            </div>
            <div className="flex gap-2">
              <Button variant="outline" onClick={() => { setPriceReview(null); setOpened(null); }}>Skip</Button>
              <Button onClick={savePrices} disabled={savingPrices} style={{ background: theme.primary }} data-testid="save-prices-btn">
                <Save size={14} className="mr-1" /> {savingPrices ? 'Saving…' : 'Save Prices'}
              </Button>
            </div>
          </div>
          <table className="w-full text-sm" data-testid="price-review-table">
            <thead className="bg-gray-50 text-xs uppercase text-gray-500"><tr><th className="text-left p-2">Product</th><th>New cost</th><th>Price</th><th>Margin</th></tr></thead>
            <tbody>
              {priceReview.map(p => {
                const draftPrice = parseFloat(priceDraft[p.productId]);
                const margin = Number.isFinite(draftPrice) && draftPrice > 0 ? Math.round((draftPrice - p.cost) / draftPrice * 1000) / 10 : null;
                return (
                  <tr key={p.productId} className="border-t" data-testid={`price-review-row-${p.productId}`}>
                    <td className="p-2">{p.name}</td>
                    <td className="p-2">${p.cost.toFixed(2)}</td>
                    <td className="p-2">
                      <Input type="number" step="0.01" className="w-24" value={priceDraft[p.productId] ?? ''}
                        onChange={e => setPriceDraft(d => ({ ...d, [p.productId]: e.target.value }))}
                        data-testid={`price-review-input-${p.productId}`} />
                    </td>
                    <td className="p-2">
                      {margin === null ? '—' : (
                        <Badge className={margin < 20 ? 'bg-red-100 text-red-700' : margin < 40 ? 'bg-amber-100 text-amber-700' : 'bg-green-100 text-green-700'}>
                          {margin}%
                        </Badge>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </>
      ) : (
        <>
          <div className="flex justify-between items-center mb-3">
            <div>
              <h3 className="font-bold">Assign {opened.parsed?.supplier} · {opened.parsed?.invoiceNumber}</h3>
              <p className="text-xs text-gray-500">Pick the ingredient + unit per line. We auto-convert kg↔g, L↔mL.</p>
            </div>
            <div className="flex gap-2">
              <Button variant="outline" onClick={() => setOpened(null)}>Back</Button>
              <Button onClick={apply} style={{ background: theme.primary }} data-testid="apply-stock-assign-btn"><Save size={14} className="mr-1" /> Apply</Button>
            </div>
          </div>
          <table className="w-full text-sm" data-testid="assignment-table">
            <thead className="bg-gray-50 text-xs uppercase text-gray-500"><tr><th className="text-left p-2">Invoice line</th><th>Ingredient</th><th>Qty</th><th>Unit</th><th>$ line total</th></tr></thead>
            <tbody>
              {assignments.map((a, i) => (
                <tr key={i} className="border-t" data-testid={`assign-row-${i}`}>
                  <td className="p-2">{a.lineName}</td>
                  <td className="p-2">
                    <select className="p-1.5 border rounded text-sm w-full" value={a.ingredientId} onChange={e => upd(i, 'ingredientId', e.target.value)} data-testid={`assign-ing-${i}`}>
                      <option value="">— skip —</option>
                      {ingredients.map(x => <option key={x.id} value={x.id}>{x.name} ({x.baseUnit})</option>)}
                    </select>
                  </td>
                  <td className="p-2"><Input type="number" step="0.01" value={a.qty} onChange={e => upd(i, 'qty', parseFloat(e.target.value) || 0)} /></td>
                  <td className="p-2">
                    <select className="p-1.5 border rounded text-sm" value={a.unit} onChange={e => upd(i, 'unit', e.target.value)}>
                      {['kg','g','L','mL','ea','box','case','pack'].map(u => <option key={u} value={u}>{u}</option>)}
                    </select>
                  </td>
                  <td className="p-2"><Input type="number" step="0.01" value={a.lineTotal} onChange={e => upd(i, 'lineTotal', parseFloat(e.target.value) || 0)} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </CardContent></Card>
  );
}

function StockTakePanel() {
  const { theme } = useTheme(); const { toast } = useToast();
  const [ingredients, setIngredients] = useState([]);
  const [counts, setCounts] = useState({});
  const [history, setHistory] = useState([]);
  const [notes, setNotes] = useState('');
  useEffect(() => {
    inventoryAPI.listIngredients().then(r => setIngredients(r.data || []));
    inventoryAPI.listStockTakes().then(r => setHistory(r.data || []));
  }, []);
  const save = async () => {
    const rows = Object.entries(counts)
      .filter(([_, v]) => v !== '' && v !== null && v !== undefined)
      .map(([ingredientId, countedBase]) => ({ ingredientId, countedBase: parseFloat(countedBase) || 0 }));
    if (rows.length === 0) return toast({ title: 'Enter at least one count', variant: 'destructive' });
    try {
      const r = await inventoryAPI.createStockTake({ counts: rows, notes });
      toast({ title: 'Stock-take recorded', description: `Shrinkage $${r.data.totalShrinkageValue}` });
      setCounts({}); setNotes('');
      inventoryAPI.listIngredients().then(r => setIngredients(r.data || []));
      inventoryAPI.listStockTakes().then(r => setHistory(r.data || []));
    } catch { toast({ title: 'Failed', variant: 'destructive' }); }
  };
  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
      <Card className="lg:col-span-2"><CardContent className="p-4">
        <h3 className="font-bold mb-2 flex items-center gap-2"><ClipboardList size={16} /> Physical count</h3>
        <p className="text-xs text-gray-500 mb-3">Enter the actual quantity in base units (g, mL, ea). Empty rows are skipped.</p>
        <table className="w-full text-sm" data-testid="stocktake-table">
          <thead className="bg-gray-50 text-xs uppercase text-gray-500"><tr><th className="text-left p-2">Ingredient</th><th>Expected</th><th>Counted</th><th>Δ</th></tr></thead>
          <tbody>
            {ingredients.map(ing => {
              const counted = counts[ing.id];
              const delta = counted != null && counted !== '' ? parseFloat(counted) - ing.stock : null;
              return (
                <tr key={ing.id} className="border-t" data-testid={`stocktake-row-${ing.id}`}>
                  <td className="p-2 font-medium">{ing.name}</td>
                  <td className="p-2 text-center text-xs">{Number(ing.stock || 0).toFixed(1)} {ing.baseUnit}</td>
                  <td className="p-2"><Input type="number" step="0.1" value={counts[ing.id] ?? ''} onChange={e => setCounts({ ...counts, [ing.id]: e.target.value })} placeholder="—" data-testid={`stocktake-count-${ing.id}`} /></td>
                  <td className={`p-2 text-center font-mono text-xs ${delta === null ? '' : delta < 0 ? 'text-red-600' : 'text-green-600'}`}>{delta === null ? '—' : delta.toFixed(1)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <Input className="mt-3" placeholder="Notes (e.g. weekly count)" value={notes} onChange={e => setNotes(e.target.value)} />
        <Button onClick={save} className="mt-2 w-full" style={{ background: theme.primary }} data-testid="save-stocktake-btn"><Save size={14} className="mr-1" /> Save stock-take</Button>
      </CardContent></Card>
      <Card><CardContent className="p-4">
        <h3 className="font-bold mb-2">History</h3>
        {history.length === 0 ? <p className="text-xs text-gray-400">No stock-takes yet</p> :
          history.map(h => (
            <div key={h.id} className="text-xs border-b py-2" data-testid={`stocktake-history-${h.id}`}>
              <p className="font-medium">{new Date(h.performedAt).toLocaleString()}</p>
              <p className="text-gray-500">{h.variances.length} items · shrinkage <span className="text-red-600 font-bold">${h.totalShrinkageValue}</span></p>
            </div>
          ))
        }
      </CardContent></Card>
    </div>
  );
}

function BASPanel() {
  const { theme } = useTheme(); const { toast } = useToast();
  const today = new Date();
  const [fy, setFy] = useState(today.getMonth() >= 6 ? today.getFullYear() + 1 : today.getFullYear());
  const [quarter, setQuarter] = useState('Q3');
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(false);
  const load = async () => {
    setLoading(true);
    try { const r = await inventoryAPI.bas({ fy, quarter }); setReport(r.data); }
    catch (e) { toast({ title: 'Failed', description: e?.response?.data?.detail, variant: 'destructive' }); }
    setLoading(false);
  };
  useEffect(() => { load(); }, []);  // eslint-disable-line
  const dl = async () => {
    try {
      const r = await inventoryAPI.basCsv({ fy, quarter });
      const url = window.URL.createObjectURL(new Blob([r.data]));
      const a = document.createElement('a'); a.href = url; a.download = `BAS-FY${fy}-${quarter}.csv`; a.click();
    } catch { /* download failed silently */ }
  };
  return (
    <div className="space-y-4">
      <Card><CardContent className="p-4 flex items-center gap-2 flex-wrap" data-testid="bas-controls">
        <span className="text-sm font-semibold">Financial year</span>
        <Input type="number" value={fy} onChange={e => setFy(parseInt(e.target.value) || fy)} className="w-24" data-testid="bas-fy" />
        <span className="text-sm font-semibold ml-2">Quarter</span>
        <select className="p-2 border rounded text-sm" value={quarter} onChange={e => setQuarter(e.target.value)} data-testid="bas-quarter">
          <option value="Q1">Q1 (Jul-Sep)</option><option value="Q2">Q2 (Oct-Dec)</option>
          <option value="Q3">Q3 (Jan-Mar)</option><option value="Q4">Q4 (Apr-Jun)</option>
        </select>
        <Button onClick={load} style={{ background: theme.primary }} data-testid="run-bas-btn"><RefreshCw size={12} className="mr-1" /> Generate</Button>
        <Button variant="outline" onClick={dl} disabled={!report} data-testid="download-bas-btn"><Download size={12} className="mr-1" /> CSV</Button>
      </CardContent></Card>
      {loading && <p className="text-center text-gray-400">Loading…</p>}
      {report && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3" data-testid="bas-report">
          {[
            { l: 'G1 Total sales', v: report.g1TotalSales, color: theme.primary },
            { l: '1A GST collected', v: report.oneA_gstOnSales, color: '#10b981' },
            { l: 'G11 Purchases', v: report.g11TotalPurchases, color: '#6366f1' },
            { l: '1B GST credits', v: report.oneB_gstCredits, color: '#f59e0b' },
            { l: 'Net GST payable', v: report.netGstPayable, color: report.netGstPayable >= 0 ? '#dc2626' : '#10b981', big: true },
            { l: 'Sales count', v: report.salesCount, raw: true },
            { l: 'Stock on hand', v: report.stockOnHandValue },
            { l: 'Stock received', v: report.stockReceivedInPeriod },
          ].map((t, i) => (
            <Card key={i}><CardContent className="p-4" data-testid={`bas-tile-${i}`}>
              <p className="text-xs uppercase font-bold text-gray-500 tracking-wider">{t.l}</p>
              <p className={`mt-1 font-bold ${t.big ? 'text-3xl' : 'text-2xl'}`} style={{ color: t.color }}>
                {t.raw ? t.v : `$${Number(t.v || 0).toFixed(2)}`}
              </p>
            </CardContent></Card>
          ))}
          <Card className="col-span-2 md:col-span-4 bg-gray-50"><CardContent className="p-4 text-sm">
            <p className="font-bold mb-1">{report.period}</p>
            <p className="text-xs text-gray-500">From {report.windowStart} to {report.windowEnd}. Australian standard formula: GST = total (incl) / 11. Lodge via ATO Business Portal.</p>
          </CardContent></Card>
        </div>
      )}
    </div>
  );
}

// ============================================================================
// Super (Awards) Panel — computes superannuation per staff from payruns using
// installed Award rates (Fair Work Australia + multi-country catalogue).
// ============================================================================
function SuperAwardsPanel() {
  const { theme } = useTheme();
  const { toast } = useToast();
  const [catalogue, setCatalogue] = useState([]);
  const [country, setCountry] = useState('AU');
  const [payrun, setPayrun] = useState(null);
  const [period, setPeriod] = useState('week');
  const [globalAward, setGlobalAward] = useState('');
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);

  const refresh = async () => {
    try {
      const c = await awardsAPI.catalogue(country);
      setCatalogue(c.data || []);
    } catch { /* no awards available yet */ toast({ title: 'Could not load awards', variant: 'destructive' }); }
  };

  useEffect(() => { refresh(); /* eslint-disable-next-line */ }, [country]);

  const install = async (code) => {
    try { await awardsAPI.install(code); toast({ title: 'Award installed' }); refresh(); }
    catch (e) { toast({ title: 'Failed', description: e?.response?.data?.detail, variant: 'destructive' }); }
  };
  const uninstall = async (code) => {
    if (!await DialogService.confirm('Uninstall this award? Any payruns referencing it will fall back to 11.5%.')) return;
    try { await awardsAPI.uninstall(code); toast({ title: 'Uninstalled' }); refresh(); }
    catch { toast({ title: 'Failed', variant: 'destructive' }); }
  };

  const loadPayrun = async () => {
    try {
      const r = await staffMgmtAPI.calculatePayrun({ period });
      setPayrun(r.data);
    } catch { toast({ title: 'No payrun data', description: 'Make sure timesheets / shifts have been logged.' }); }
  };

  const compute = async () => {
    if (!payrun?.staffPayroll?.length) { return toast({ title: 'Load a payrun first', variant: 'destructive' }); }
    setBusy(true);
    try {
      const r = await awardsAPI.superByAward({ awardCode: globalAward || null, payrun });
      setResult(r.data);
      toast({ title: 'Super computed', description: `Total: $${r.data.totalSuper.toFixed(2)}` });
    } catch (e) { toast({ title: 'Failed', description: e?.response?.data?.detail, variant: 'destructive' }); }
    finally { setBusy(false); }
  };

  return (
    <div className="space-y-4 mt-4" data-testid="super-awards-panel">
      <Card><CardContent className="p-5 space-y-3">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <div>
            <h2 className="font-bold text-lg">Award Catalogue</h2>
            <p className="text-xs text-gray-500">Install awards from Fair Work Australia (or country regulator). Each award carries its base hourly, loadings and super rate.</p>
          </div>
          <select className="border rounded p-2 text-sm" value={country} onChange={e => setCountry(e.target.value)} data-testid="award-country">
            <option value="AU">Australia</option>
            <option value="NZ">New Zealand</option>
            <option value="UK">United Kingdom</option>
            <option value="US">United States</option>
          </select>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm" data-testid="award-catalogue-table">
            <thead className="bg-gray-50 text-xs uppercase text-gray-500">
              <tr>
                <th className="text-left px-3 py-2">Code</th>
                <th className="text-left px-3 py-2">Name</th>
                <th className="text-left px-3 py-2">Industry</th>
                <th className="text-right px-3 py-2">Super %</th>
                <th className="text-right px-3 py-2">Classifications</th>
                <th className="text-right px-3 py-2">Status</th>
              </tr>
            </thead>
            <tbody>
              {catalogue.map(a => (
                <tr key={a.code} className="border-t" data-testid={`award-row-${a.code}`}>
                  <td className="px-3 py-2 font-mono text-xs">{a.code}</td>
                  <td className="px-3 py-2 font-medium">{a.name}</td>
                  <td className="px-3 py-2 text-xs text-gray-600">{a.industry}</td>
                  <td className="px-3 py-2 text-right font-bold">{a.superRate}%</td>
                  <td className="px-3 py-2 text-right text-xs">{(a.classifications || []).length}</td>
                  <td className="px-3 py-2 text-right">
                    {a.installed ? (
                      <Button size="sm" variant="outline" className="text-red-600" onClick={() => uninstall(a.code)} data-testid={`uninstall-${a.code}`}>Uninstall</Button>
                    ) : (
                      <Button size="sm" onClick={() => install(a.code)} style={{ background: theme.primary }} className="text-white" data-testid={`install-${a.code}`}>Install</Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent></Card>

      <Card><CardContent className="p-5 space-y-3" data-testid="super-payrun-card">
        <h2 className="font-bold text-lg">Compute Super from a Payrun</h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <div>
            <label className="text-xs uppercase text-gray-500 mb-1 block">Period</label>
            <select className="w-full border rounded p-2 text-sm" value={period} onChange={e => setPeriod(e.target.value)}>
              <option value="week">Week</option>
              <option value="fortnight">Fortnight</option>
              <option value="month">Month</option>
            </select>
          </div>
          <div>
            <label className="text-xs uppercase text-gray-500 mb-1 block">Default Award (applied to staff without one)</label>
            <select className="w-full border rounded p-2 text-sm" value={globalAward} onChange={e => setGlobalAward(e.target.value)} data-testid="default-award">
              <option value="">— Fall back to 11.5% —</option>
              {catalogue.filter(a => a.installed).map(a => (
                <option key={a.code} value={a.code}>{a.name} ({a.superRate}%)</option>
              ))}
            </select>
          </div>
          <div className="flex items-end gap-2">
            <Button onClick={loadPayrun} variant="outline" data-testid="load-payrun">Load Payrun</Button>
            <Button onClick={compute} disabled={busy} style={{ background: theme.primary }} className="text-white" data-testid="compute-super">{busy ? 'Computing…' : 'Compute Super'}</Button>
          </div>
        </div>
        {payrun && (
          <p className="text-xs text-gray-500">Loaded payrun · {payrun?.staffPayroll?.length || 0} staff · gross ${payrun?.totals?.grossPay || 0}</p>
        )}
        {result && (
          <div className="space-y-2 pt-2 border-t" data-testid="super-result">
            <p className="text-sm">Total super: <span className="text-2xl font-bold" style={{ color: theme.primary }}>${result.totalSuper.toFixed(2)}</span></p>
            {result.unresolvedAwards && result.unresolvedAwards.length > 0 && (
              <div className="bg-amber-50 border border-amber-200 rounded p-2 text-xs" data-testid="unresolved-awards">
                <p className="font-medium text-amber-800 mb-1">⚠ Some staff reference awards that aren’t installed — they fell back to 11.5%:</p>
                <p className="text-amber-700">{result.unresolvedAwards.join(', ')}</p>
                <p className="text-amber-600 mt-1">Install them above to apply the correct super rate.</p>
              </div>
            )}
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 text-xs uppercase text-gray-500">
                  <tr>
                    <th className="text-left px-3 py-2">Staff</th>
                    <th className="text-left px-3 py-2">Role</th>
                    <th className="text-left px-3 py-2">Award</th>
                    <th className="text-right px-3 py-2">Gross</th>
                    <th className="text-right px-3 py-2">Rate</th>
                    <th className="text-right px-3 py-2">Super</th>
                  </tr>
                </thead>
                <tbody>
                  {result.staffSuper.map((s, i) => (
                    <tr key={i} className="border-t">
                      <td className="px-3 py-2 font-medium">{s.name || s.staffName}</td>
                      <td className="px-3 py-2 text-xs text-gray-600">{s.role}</td>
                      <td className="px-3 py-2 text-xs">{s.awardName || s.awardCode || <span className="text-gray-400">— default —</span>}</td>
                      <td className="px-3 py-2 text-right font-mono">${(s.grossPay || 0).toFixed(2)}</td>
                      <td className="px-3 py-2 text-right">{s.superRate}%</td>
                      <td className="px-3 py-2 text-right font-bold">${s.superContribution.toFixed(2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="text-xs text-gray-400">Super is calculated on Ordinary Time Earnings (OTE). Pay via SuperStream-compliant clearing house once approved.</p>
          </div>
        )}
      </CardContent></Card>
    </div>
  );
}

