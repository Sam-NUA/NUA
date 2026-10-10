import React, { useState, useEffect, useMemo } from 'react';
import { Plus, Edit, Trash2, Tag, Package, ImageIcon, Sparkles } from 'lucide-react';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Textarea } from '../components/ui/textarea';
import { Card, CardContent } from '../components/ui/card';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '../components/ui/dialog';
import { useTheme } from '../contexts/ThemeContext';
import { productsAPI, promotionsAPI, categoriesAPI, modifiersAPI, aiPantryAPI, productsBulkAPI } from '../services/api';
import { LANGUAGES } from '../i18n/translations';
import ImageLibrary from '../components/ImageLibrary';
import { ProductsToolbar } from '../components/products/ProductsToolbar';
import { ProductTable } from '../components/products/ProductTable';
import { BulkEditDialog } from '../components/products/BulkEditDialog';
import { RecentlyEditedSidebar } from '../components/products/RecentlyEditedSidebar';
import { ProductVariants } from '../components/products/ProductVariants';
import { PromotionDialog } from '../components/products/PromotionDialog';
import { ItemsKpiStrip } from '../components/products/ItemsKpiStrip';
import { toast } from 'sonner';

const makeEmptyProduct = () => ({
  name: '', category: '', categoryId: '', price: '', cost: '', stock: '', sku: '', barcode: '',
  image: '', gstRate: 10, locations: ['Main'], onlineChannels: [],
  seoDescription: '', description: '', modifierIds: [],
});
const makeEmptyPromo = () => ({
  name: '', type: 'category',
  pricingMode: 'percentage',
  discount: '', bundlePrice: '',
  minQuantity: null, maxQuantity: null, stackable: false,
  schedule: '', active: true,
  category: '', categories: [], products: [],
  startDate: '', endDate: '',
  activeDays: [], startTime: '', endTime: '',
  channels: [],
});
const emptyBulkPatch = () => ({
  image: '', addModifierIds: [], removeModifierIds: [],
});

const Products = () => {
  const { theme } = useTheme();
  const [searchTerm, setSearchTerm] = useState('');
  const [view, setView] = useState('products');
  const [products, setProducts] = useState([]);
  const [promotions, setPromotions] = useState([]);
  const [categories, setCategories] = useState([]);
  const [modifiers, setModifiers] = useState([]);
  const [insights, setInsights] = useState({});
  const [showProductDialog, setShowProductDialog] = useState(false);
  const [showPromoDialog, setShowPromoDialog] = useState(false);
  const [showTranslateDialog, setShowTranslateDialog] = useState(false);
  const [translatingProduct, setTranslatingProduct] = useState(null);
  const [translationForm, setTranslationForm] = useState({});
  const [autoTranslating, setAutoTranslating] = useState(false);
  const [bulkTranslating, setBulkTranslating] = useState(false);
  const [editingProduct, setEditingProduct] = useState(null);
  const [editingPromo, setEditingPromo] = useState(null);
  const [productForm, setProductForm] = useState(makeEmptyProduct);
  const [promoForm, setPromoForm] = useState(makeEmptyPromo);

  // Filter / sort / bulk / library state
  const [filterCats, setFilterCats] = useState([]);
  const [filterStatus, setFilterStatus] = useState('all');
  const [sortKey, setSortKey] = useState('name');
  const [sortDir, setSortDir] = useState('asc');
  const [selected, setSelected] = useState(new Set());
  const [bulkOpen, setBulkOpen] = useState(false);
  const [layoutMode, setLayoutMode] = useState('grid');
  const [imageLibraryOpen, setImageLibraryOpen] = useState(false);
  const [bulkImageLibraryOpen, setBulkImageLibraryOpen] = useState(false);
  const [bulkPatch, setBulkPatch] = useState(emptyBulkPatch);
  // One editable row per selected product — each item's price/cost/GST/category/
  // status is tweaked independently rather than one shared value stomping all of them.
  const [bulkRows, setBulkRows] = useState([]);
  const [inlineEditCell, setInlineEditCell] = useState(null);
  const [inlineValue, setInlineValue] = useState('');
  // Optimistic edit-time map: product id -> ISO timestamp the client touched
  // it. Lets the Recently Edited sidebar reflect edits IMMEDIATELY instead of
  // waiting for the backend round-trip + a fresh GET.
  const [touchTimes, setTouchTimes] = useState({});
  const markTouched = (id) => setTouchTimes(prev => ({ ...prev, [id]: new Date().toISOString() }));

  useEffect(() => { fetchData(); fetchInsights(); }, []);

  const fetchInsights = async () => {
    try {
      const r = await aiPantryAPI.productInsights();
      const map = {};
      (r.data || []).forEach(i => { map[i.productId] = i; });
      setInsights(map);
    } catch { /* ignore — insights are optional */ }
  };

  const fetchData = async () => {
    try {
      const [productsRes, promotionsRes, categoriesRes, modifiersRes] = await Promise.all([
        productsAPI.getAll(), promotionsAPI.getAll(), categoriesAPI.getAll(), modifiersAPI.getAll(),
      ]);
      setProducts(productsRes.data);
      setPromotions(promotionsRes.data);
      const activeCats = (categoriesRes.data || []).filter(c => c.active !== false);
      const sortedCats = Array.from(activeCats).sort((a, b) => (a.sortOrder || 0) - (b.sortOrder || 0));
      setCategories(sortedCats);
      setModifiers(modifiersRes.data || []);
    } catch { toast.error('Failed to load data'); }
  };

  // === Product CRUD ===
  function openAddProduct() {
    const firstCat = categories[0];
    setEditingProduct(null);
    setProductForm({
      name: '', category: firstCat?.name || '', categoryId: firstCat?.id || '',
      price: '', cost: '', stock: '', sku: '', barcode: '', image: '', gstRate: 10,
      locations: ['Main'], onlineChannels: [], seoDescription: '', description: '',
      modifierIds: [],
    });
    setShowProductDialog(true);
  }
  const openEditProduct = (p) => {
    setEditingProduct(p);
    setProductForm({
      name: p.name, category: p.category, categoryId: p.categoryId || '',
      price: p.price, cost: p.cost, stock: p.stock, sku: p.sku, barcode: p.barcode || '', image: p.image,
      gstRate: p.gstRate, locations: p.locations || ['Main'], onlineChannels: p.onlineChannels || [],
      seoDescription: p.seoDescription || '', description: p.description || '',
      modifierIds: p.modifierIds || [],
    });
    setShowProductDialog(true);
  };
  const saveProduct = async () => {
    const data = {
      ...productForm,
      price: parseFloat(productForm.price), cost: parseFloat(productForm.cost),
      stock: parseInt(productForm.stock), gstRate: parseFloat(productForm.gstRate),
    };
    try {
      if (editingProduct) {
        await productsAPI.update(editingProduct.id, data);
        markTouched(editingProduct.id);
        toast.success('Product updated');
      } else {
        const r = await productsAPI.create(data);
        if (r?.data?.id) markTouched(r.data.id);
        toast.success('Product created');
      }
      setShowProductDialog(false); fetchData();
    } catch (e) { toast.error(e.response?.data?.detail || 'Failed to save product'); }
  };
  const deleteProduct = async (id) => {
    if (!window.confirm('Delete this product?')) return;
    try { await productsAPI.delete(id); toast.success('Product deleted'); fetchData(); } catch { toast.error('Failed to delete'); }
  };

  const openTranslateProduct = (p) => {
    setTranslatingProduct(p);
    setTranslationForm(p.translations || {});
    setShowTranslateDialog(true);
  };
  const setTranslationField = (langCode, field, value) => {
    setTranslationForm(prev => ({ ...prev, [langCode]: { ...prev[langCode], [field]: value } }));
  };
  const saveTranslations = async () => {
    // Drop languages left fully blank so we don't store empty overrides.
    const cleaned = Object.fromEntries(
      Object.entries(translationForm).filter(([, v]) => v?.name?.trim() || v?.description?.trim())
    );
    try {
      await productsAPI.update(translatingProduct.id, { translations: cleaned });
      toast.success('Translations saved');
      setShowTranslateDialog(false);
      fetchData();
    } catch (e) { toast.error(e.response?.data?.detail || 'Failed to save translations'); }
  };
  const autoTranslateProduct = async () => {
    if (!translatingProduct) return;
    setAutoTranslating(true);
    try {
      const res = await productsAPI.autoTranslate(translatingProduct.id);
      // Merge into the form rather than replace, so any language a staff
      // member already hand-edited in this session isn't clobbered.
      setTranslationForm(prev => ({ ...prev, ...res.data.translations }));
      toast.success('AI draft ready — review before saving');
    } catch (e) { toast.error(e.response?.data?.detail || 'Auto-translate failed'); }
    finally { setAutoTranslating(false); }
  };
  const bulkAutoTranslateMenu = async () => {
    setBulkTranslating(true);
    try {
      const res = await productsAPI.bulkAutoTranslate(true);
      const { translated, failed, skipped, total } = res.data;
      if (total === 0) {
        toast.info('Every product already has translations — nothing to do');
      } else {
        toast.success(
          `Translated ${translated} of ${total} product${total === 1 ? '' : 's'}`
          + (failed || skipped ? ` (${failed + skipped} skipped)` : '')
        );
      }
      fetchData();
    } catch (e) { toast.error(e.response?.data?.detail || 'Bulk translate failed'); }
    finally { setBulkTranslating(false); }
  };

  const toggleModifierForProduct = (mid) => {
    const arr = productForm.modifierIds || [];
    setProductForm({
      ...productForm,
      modifierIds: arr.includes(mid) ? arr.filter(x => x !== mid) : [...arr, mid],
    });
  };

  const handleCategoryChange = (catId) => {
    const c = categories.find(x => x.id === catId);
    setProductForm({ ...productForm, categoryId: catId, category: c?.name || '' });
  };

  // === Promotion CRUD ===
  const openAddPromo = () => { setEditingPromo(null); setPromoForm(makeEmptyPromo()); setShowPromoDialog(true); };
  const openEditPromo = (p) => {
    setEditingPromo(p);
    setPromoForm({
      name: p.name, type: p.type,
      pricingMode: p.pricingMode || 'percentage',
      discount: p.discount ?? '', bundlePrice: p.bundlePrice ?? '',
      minQuantity: p.minQuantity ?? null, maxQuantity: p.maxQuantity ?? null,
      stackable: !!p.stackable,
      schedule: p.schedule,
      active: p.active,
      category: p.category || '',
      categories: p.categories || (p.category ? [p.category] : []),
      products: p.products || [],
      startDate: p.startDate || '', endDate: p.endDate || '',
      activeDays: p.activeDays || [], startTime: p.startTime || '', endTime: p.endTime || '',
      channels: p.channels || [],
    });
    setShowPromoDialog(true);
  };
  const savePromo = async () => {
    const data = {
      ...promoForm,
      discount: parseFloat(promoForm.discount) || 0,
      bundlePrice: promoForm.bundlePrice === '' || promoForm.bundlePrice == null
        ? null : parseFloat(promoForm.bundlePrice),
    };
    try {
      if (editingPromo) { await promotionsAPI.update(editingPromo.id, data); toast.success('Promotion updated'); }
      else { await promotionsAPI.create(data); toast.success('Promotion created'); }
      setShowPromoDialog(false); fetchData();
    } catch (e) { toast.error(e.response?.data?.detail || 'Failed to save promotion'); }
  };
  const deletePromo = async (id) => {
    if (!window.confirm('Delete this promotion?')) return;
    try { await promotionsAPI.delete(id); toast.success('Promotion deleted'); fetchData(); } catch { toast.error('Failed to delete'); }
  };

  const filteredProducts = useMemo(() => {
    const term = searchTerm.toLowerCase();
    let list = products.filter(p => {
      if (term && !(p.name?.toLowerCase().includes(term) || p.sku?.toLowerCase().includes(term) || p.category?.toLowerCase().includes(term))) return false;
      if (filterCats.length > 0) {
        const matchById = p.categoryId && filterCats.includes(p.categoryId);
        const matchByName = !p.categoryId && filterCats.some(fc => {
          const c = categories.find(x => x.id === fc);
          return c && c.name === p.category;
        });
        if (!matchById && !matchByName) return false;
      }
      if (filterStatus === 'active' && p.eightySixed) return false;
      if (filterStatus === '86' && !p.eightySixed) return false;
      if (filterStatus === 'lowStock') {
        const s = Number(p.stock ?? 0);
        const threshold = Number(p.lowStockThreshold ?? 5);
        if (!(s > 0 && s <= threshold)) return false;
      }
      if (filterStatus === 'outOfStock' && !(Number(p.stock ?? 0) <= 0)) return false;
      return true;
    });
    const dir = sortDir === 'asc' ? 1 : -1;
    list = [...list].sort((a, b) => {
      let av, bv;
      if (sortKey === 'name') { av = (a.name || '').toLowerCase(); bv = (b.name || '').toLowerCase(); }
      else if (sortKey === 'price') { av = Number(a.price || 0); bv = Number(b.price || 0); }
      else if (sortKey === 'stock') { av = Number(a.stock || 0); bv = Number(b.stock || 0); }
      else if (sortKey === 'margin') {
        const am = insights[a.id]?.marginPct ?? (a.price && a.cost ? ((a.price - a.cost) / a.price * 100) : 0);
        const bm = insights[b.id]?.marginPct ?? (b.price && b.cost ? ((b.price - b.cost) / b.price * 100) : 0);
        av = am; bv = bm;
      } else if (sortKey === 'recent') {
        av = a.updatedAt || a.createdAt || ''; bv = b.updatedAt || b.createdAt || '';
      } else if (sortKey === 'category') {
        av = (a.category || ''); bv = (b.category || '');
      }
      if (av < bv) return -1 * dir;
      if (av > bv) return 1 * dir;
      return 0;
    });
    return list;
  }, [products, searchTerm, filterCats, filterStatus, sortKey, sortDir, insights, categories]);

  // -------- Bulk + inline operations --------
  const toggleSelect = (id) => {
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };
  const selectAllVisible = () => setSelected(new Set(filteredProducts.map(p => p.id)));
  const clearSelection = () => setSelected(new Set());
  const allVisibleSelected = filteredProducts.length > 0 && filteredProducts.every(p => selected.has(p.id));

  const openBulkEdit = () => {
    const rows = Array.from(selected).map(id => {
      const p = products.find(x => x.id === id) || {};
      return {
        id, name: p.name || id, sku: p.sku || '',
        categoryId: p.categoryId || '', category: p.category || '',
        price: p.price ?? 0, cost: p.cost ?? 0, gstRate: p.gstRate ?? 10,
        eightySixed: !!p.eightySixed,
      };
    });
    setBulkRows(rows);
    setBulkOpen(true);
  };
  const updateBulkRow = (id, field, value) => {
    setBulkRows(rows => rows.map(r => r.id === id ? { ...r, [field]: value } : r));
  };
  // Convenience fill-down — copies one value into every row so the owner
  // isn't retyping the same price/cost/GST for 20 items, while still leaving
  // every row individually editable afterward (unlike the old shared-patch flow).
  const fillBulkRows = (field, value) => {
    setBulkRows(rows => rows.map(r => ({ ...r, [field]: value })));
  };

  const applyBulk = async () => {
    if (selected.size === 0) return toast.error('Pick at least one product');
    const productIds = Array.from(selected);
    const requests = [];

    // Modifiers/image are genuinely bulk actions (assign the same modifier or
    // photo to every selected item), so those still go through one call.
    if (bulkPatch.image || bulkPatch.addModifierIds.length > 0 || bulkPatch.removeModifierIds.length > 0) {
      const bulkOnlyPayload = { productIds };
      if (bulkPatch.image) bulkOnlyPayload.image = bulkPatch.image;
      if (bulkPatch.addModifierIds.length > 0) bulkOnlyPayload.addModifierIds = bulkPatch.addModifierIds;
      if (bulkPatch.removeModifierIds.length > 0) bulkOnlyPayload.removeModifierIds = bulkPatch.removeModifierIds;
      requests.push(productsBulkAPI.bulkEdit(bulkOnlyPayload));
    }

    // Price/cost/GST/category/status are per-row — only push the fields that
    // actually changed from that item's own original value.
    let changedRows = 0;
    for (const row of bulkRows) {
      const original = products.find(p => p.id === row.id);
      if (!original) continue;
      const patch = {};
      if (row.categoryId && row.categoryId !== (original.categoryId || '')) {
        patch.categoryId = row.categoryId;
        patch.category = categories.find(c => c.id === row.categoryId)?.name;
      }
      if (Number(row.price) !== Number(original.price ?? 0)) patch.price = Number(row.price);
      if (Number(row.cost) !== Number(original.cost ?? 0)) patch.cost = Number(row.cost);
      if (Number(row.gstRate) !== Number(original.gstRate ?? 10)) patch.gstRate = Number(row.gstRate);
      if (!!row.eightySixed !== !!original.eightySixed) patch.eightySixed = !!row.eightySixed;
      if (Object.keys(patch).length > 0) {
        changedRows += 1;
        requests.push(productsAPI.update(row.id, patch));
      }
    }

    if (requests.length === 0) {
      toast.error('No changes to apply');
      return;
    }

    try {
      await Promise.all(requests);
      productIds.forEach(markTouched);
      const parts = [];
      if (changedRows > 0) parts.push(`${changedRows} item${changedRows !== 1 ? 's' : ''} individually`);
      if (bulkPatch.image || bulkPatch.addModifierIds.length > 0 || bulkPatch.removeModifierIds.length > 0) {
        parts.push(`modifiers/image on ${productIds.length}`);
      }
      toast.success(`Updated ${parts.join(' + ')}`);
      setBulkOpen(false);
      setBulkPatch(emptyBulkPatch());
      setBulkRows([]);
      clearSelection();
      fetchData();
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Bulk update failed');
    }
  };

  const bulkDelete = async () => {
    if (selected.size === 0) return;
    if (!window.confirm(`Delete ${selected.size} products? This cannot be undone.`)) return;
    let ok = 0, fail = 0;
    for (const id of selected) {
      try { await productsAPI.delete(id); ok++; } catch { fail++; }
    }
    toast.success(`Deleted ${ok}${fail > 0 ? ` · ${fail} failed` : ''}`);
    clearSelection(); fetchData();
  };

  const toggleEightySix = async (p) => {
    try {
      await productsBulkAPI.bulkEdit({ productIds: [p.id], eightySixed: !p.eightySixed });
      markTouched(p.id);
      toast.success(p.eightySixed ? 'Un-86\'d' : 'Marked as 86 (out of stock)');
      fetchData();
    } catch { toast.error('Failed'); }
  };

  const startInlineEdit = (id, field, currentValue) => {
    setInlineEditCell({ id, field });
    setInlineValue(currentValue?.toString() ?? '');
  };
  const commitInlineEdit = async () => {
    if (!inlineEditCell) return;
    const { id, field } = inlineEditCell;
    let value = inlineValue;
    if (field === 'price' || field === 'cost') value = parseFloat(value) || 0;
    if (field === 'stock') value = parseInt(value, 10) || 0;
    if ((field === 'price' || field === 'cost') && value < 0) {
      toast.error('Value cannot be negative');
      setInlineEditCell(null);
      return;
    }
    try {
      await productsAPI.update(id, { [field]: value });
      markTouched(id);
      toast.success(`${field} updated`);
      fetchData();
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Failed — refreshing');
      fetchData();
    }
    setInlineEditCell(null);
  };

  const exportCsv = () => {
    const headers = ['id', 'name', 'sku', 'category', 'price', 'cost', 'stock', 'gstRate', 'eightySixed', 'modifiersCount'];
    const rows = filteredProducts.map(p => [
      p.id, p.name, p.sku, p.category, p.price, p.cost, p.stock, p.gstRate,
      p.eightySixed ? 'Y' : 'N', (p.modifierIds || []).length,
    ]);
    const escape = (v) => `"${String(v ?? '').replace(/"/g, '""')}"`;
    const csv = [headers.join(','), ...rows.map(r => r.map(escape).join(','))].join('\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = `products-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click(); URL.revokeObjectURL(url);
  };

  const onCsvImport = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    // Accept anything the user picked — some OSes report .csv as text/plain
    // or application/vnd.ms-excel, so we don't gate on file.type here.
    const text = await file.text();
    const lines = text.split(/\r?\n/).filter(l => l.trim());
    if (lines.length < 2) {
      toast.error('CSV needs a header row + at least one data row');
      e.target.value = '';
      return;
    }
    // Split respecting quoted commas
    const splitLine = (l) => {
      const out = []; let cur = ''; let inQ = false;
      for (let i = 0; i < l.length; i++) {
        const ch = l[i];
        if (ch === '"') { if (inQ && l[i+1] === '"') { cur += '"'; i++; } else { inQ = !inQ; } }
        else if (ch === ',' && !inQ) { out.push(cur); cur = ''; }
        else cur += ch;
      }
      out.push(cur);
      return out;
    };
    const headers = splitLine(lines[0]).map(h => h.trim().toLowerCase());
    if (!headers.includes('name')) {
      toast.error('CSV must include a "name" column');
      e.target.value = '';
      return;
    }
    const rows = lines.slice(1).map(l => {
      const cells = splitLine(l);
      const obj = {};
      headers.forEach((h, i) => obj[h] = (cells[i] || '').trim());
      return obj;
    });
    const loadingId = toast.loading(`Importing ${rows.length} product${rows.length === 1 ? '' : 's'}…`);
    try {
      const r = await fetch(`${process.env.REACT_APP_BACKEND_URL}/api/items/bulk-import`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${localStorage.getItem('nua_token')}` },
        body: JSON.stringify({ rows }),
      });
      if (!r.ok) {
        const detail = await r.text().catch(() => '');
        toast.dismiss(loadingId);
        toast.error(`Import failed (${r.status}) ${detail.slice(0, 120)}`);
        return;
      }
      const d = await r.json();
      toast.dismiss(loadingId);
      toast.success(`Imported ${d.imported ?? 0} of ${rows.length} product${rows.length === 1 ? '' : 's'}`);
      fetchData();
    } catch (err) {
      toast.dismiss(loadingId);
      toast.error(`Import failed: ${err?.message || 'network error'}`);
    } finally {
      e.target.value = '';
    }
  };

  return (
    <div className="space-y-6" data-testid="products-page">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-3xl font-bold" style={{ color: theme.text }}>Products & Promotions</h1>
          <p className="text-gray-500 mt-1">Manage your catalog, pricing, and special offers</p>
        </div>
        {view === 'products' ? (
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" className="gap-2" onClick={bulkAutoTranslateMenu} disabled={bulkTranslating} data-testid="bulk-translate-btn">
              <Sparkles className="w-4 h-4" style={{ color: '#8b5cf6' }} />
              {bulkTranslating ? 'Translating menu…' : 'Translate menu with AI'}
            </Button>
            <Button variant="outline" onClick={() => document.getElementById('csv-import-input')?.click()} data-testid="csv-import-btn">
              CSV Import
            </Button>
            <input
              id="csv-import-input"
              type="file"
              accept=".csv,text/csv,application/vnd.ms-excel,text/plain"
              className="hidden"
              onChange={onCsvImport}
              data-testid="csv-import-input"
            />
            <Button style={{ backgroundColor: theme.primary }} onClick={openAddProduct} data-testid="add-product-btn">
              <Plus className="mr-2" size={18} /> Add Product
            </Button>
          </div>
        ) : (
          <Button style={{ backgroundColor: theme.primary }} onClick={openAddPromo} data-testid="add-promo-btn">
            <Plus className="mr-2" size={18} /> Create Promotion
          </Button>
        )}
      </div>

      <div className="flex flex-wrap gap-2">
        <Button
          variant={view === 'products' ? 'default' : 'outline'}
          onClick={() => setView('products')}
          style={{ backgroundColor: view === 'products' ? theme.primary : 'transparent', color: view === 'products' ? 'white' : theme.text }}
        >
          <Package className="mr-2" size={18} /> Products ({products.length})
        </Button>
        <Button
          variant={view === 'promotions' ? 'default' : 'outline'}
          onClick={() => setView('promotions')}
          style={{ backgroundColor: view === 'promotions' ? theme.primary : 'transparent', color: view === 'promotions' ? 'white' : theme.text }}
        >
          <Tag className="mr-2" size={18} /> Promotions ({promotions.length})
        </Button>
      </div>

      {view === 'products' && (
        <>
          <ItemsKpiStrip
            theme={theme}
            products={products}
            filterStatus={filterStatus}
            setFilterStatus={setFilterStatus}
          />
          <ProductsToolbar
            theme={theme}
            searchTerm={searchTerm} setSearchTerm={setSearchTerm}
            sortKey={sortKey} setSortKey={setSortKey}
            sortDir={sortDir} setSortDir={setSortDir}
            filterStatus={filterStatus} setFilterStatus={setFilterStatus}
            layoutMode={layoutMode} setLayoutMode={setLayoutMode}
            exportCsv={exportCsv}
            filterCats={filterCats} setFilterCats={setFilterCats}
            categories={categories}
            selected={selected}
            clearSelection={clearSelection}
            allVisibleSelected={allVisibleSelected}
            selectAllVisible={selectAllVisible}
            filteredProducts={filteredProducts}
            onBulkEditOpen={openBulkEdit}
            onBulkDelete={bulkDelete}
          />

          <div className="flex gap-4 items-start" data-testid="products-layout">
            {layoutMode === 'grid' && (
              <RecentlyEditedSidebar
                theme={theme}
                products={products}
                touchTimes={touchTimes}
                onEdit={openEditProduct}
              />
            )}
            <div className="flex-1 min-w-0">
              <ProductTable
                theme={theme}
                layoutMode={layoutMode}
                filteredProducts={filteredProducts}
                insights={insights}
                selected={selected}
                toggleSelect={toggleSelect}
                setSelected={setSelected}
                allVisibleSelected={allVisibleSelected}
                selectAllVisible={selectAllVisible}
                clearSelection={clearSelection}
                inlineEditCell={inlineEditCell}
                inlineValue={inlineValue}
                setInlineValue={setInlineValue}
                setInlineEditCell={setInlineEditCell}
                startInlineEdit={startInlineEdit}
                commitInlineEdit={commitInlineEdit}
                toggleEightySix={toggleEightySix}
                openEditProduct={openEditProduct}
                deleteProduct={deleteProduct}
                openTranslateProduct={openTranslateProduct}
              />
            </div>
          </div>
        </>
      )}

      {view === 'promotions' && (
        <div className="space-y-4">
          {promotions.map(promo => {
            const isFixed = promo.pricingMode === 'fixed_price';
            const cats = promo.categories || (promo.category ? [promo.category] : []);
            const itemCount = (promo.products || []).length;
            return (
              <Card key={promo.id} data-testid={`promo-card-${promo.id}`}>
                <CardContent className="p-6">
                  <div className="flex items-start justify-between">
                    <div className="flex-1">
                      <div className="flex items-center gap-3 mb-3 flex-wrap">
                        <h3 className="text-xl font-bold" style={{ color: theme.text }}>{promo.name}</h3>
                        <span className={`px-3 py-1 rounded-full text-xs font-medium ${promo.active ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'}`}>
                          {promo.active ? 'Active' : 'Inactive'}
                        </span>
                        <span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-gray-100 text-gray-600 capitalize">
                          {promo.type}
                        </span>
                        {promo.stackable && (
                          <span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-blue-100 text-blue-700">
                            Stackable
                          </span>
                        )}
                      </div>
                      <div className="grid grid-cols-4 gap-4 text-sm">
                        <div>
                          <p className="text-gray-500 text-xs">Pricing</p>
                          {isFixed ? (
                            <p className="font-bold text-lg" style={{ color: theme.accent }} data-testid={`promo-price-${promo.id}`}>
                              ${(promo.bundlePrice || 0).toFixed(2)}
                              {promo.minQuantity && <span className="text-xs font-normal text-gray-500 ml-1">for {promo.minQuantity}+</span>}
                            </p>
                          ) : (
                            <p className="font-bold text-lg" style={{ color: theme.accent }} data-testid={`promo-price-${promo.id}`}>
                              {promo.discount}% OFF
                            </p>
                          )}
                        </div>
                        <div>
                          <p className="text-gray-500 text-xs">Categories</p>
                          <p className="font-medium truncate" title={cats.join(', ')}>
                            {cats.length === 0 ? '—' : cats.length === 1 ? cats[0] : `${cats.length} categories`}
                          </p>
                        </div>
                        <div>
                          <p className="text-gray-500 text-xs">Items</p>
                          <p className="font-medium">{itemCount > 0 ? `${itemCount} item${itemCount === 1 ? '' : 's'}` : '—'}</p>
                        </div>
                        <div>
                          <p className="text-gray-500 text-xs">Schedule</p>
                          <p className="font-medium truncate" title={promo.schedule}>{promo.schedule || 'Always'}</p>
                        </div>
                      </div>
                      {(promo.startDate || promo.endDate || (promo.activeDays || []).length > 0) && (
                        <div className="mt-2 text-xs text-gray-500 flex items-center gap-3 flex-wrap">
                          {promo.startDate && <span>From {promo.startDate}</span>}
                          {promo.endDate && <span>→ {promo.endDate}</span>}
                          {(promo.activeDays || []).length > 0 && (
                            <span>{promo.activeDays.map(d => d.slice(0, 3)).join(' · ')}</span>
                          )}
                          {(promo.startTime || promo.endTime) && (
                            <span>{promo.startTime || '00:00'}–{promo.endTime || '23:59'}</span>
                          )}
                        </div>
                      )}
                      {(promo.channels || []).length > 0 && (
                        <div className="mt-1 text-xs">
                          <span className="px-2 py-0.5 rounded-full bg-amber-100 text-amber-700 font-medium">
                            {promo.channels.map(c => c === 'dine-in' ? 'Dine-in' : 'Takeaway').join(' + ')} only
                          </span>
                        </div>
                      )}
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <Button variant="outline" size="sm" onClick={() => openEditPromo(promo)} data-testid={`edit-promo-${promo.id}`}><Edit size={14} /></Button>
                      <Button variant="outline" size="sm" className="text-red-500" onClick={() => deletePromo(promo.id)} data-testid={`delete-promo-${promo.id}`}><Trash2 size={14} /></Button>
                    </div>
                  </div>
                </CardContent>
              </Card>
            );
          })}
          {promotions.length === 0 && (
            <Card className="border-dashed"><CardContent className="p-12 text-center"><Tag size={40} className="mx-auto mb-3 text-gray-300" /><p className="text-gray-500">No promotions yet</p></CardContent></Card>
          )}
        </div>
      )}

      {/* Product Dialog */}
      <Dialog open={showProductDialog} onOpenChange={setShowProductDialog}>
        <DialogContent className="max-w-md" data-testid="product-dialog">
          <DialogHeader><DialogTitle>{editingProduct ? 'Edit Product' : 'Add Product'}</DialogTitle></DialogHeader>
          <div className="space-y-3 py-2 max-h-[60vh] overflow-y-auto">
            <Input placeholder="Product name" value={productForm.name} onChange={e => setProductForm({ ...productForm, name: e.target.value })} data-testid="product-name-input" />
            <div>
              <label className="text-xs font-medium text-gray-500 mb-1 block">Category</label>
              <select className="w-full p-2 border rounded-md text-sm" value={productForm.categoryId} onChange={e => handleCategoryChange(e.target.value)} data-testid="product-category-select">
                <option value="">— Select a category —</option>
                {categories.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <Input type="number" step="0.01" placeholder="Price" value={productForm.price} onChange={e => setProductForm({ ...productForm, price: e.target.value })} data-testid="product-price-input" />
              <Input type="number" step="0.01" placeholder="Cost" value={productForm.cost} onChange={e => setProductForm({ ...productForm, cost: e.target.value })} data-testid="product-cost-input" />
            </div>
            <div className="grid grid-cols-2 gap-2">
              <Input type="number" placeholder="Stock" value={productForm.stock} onChange={e => setProductForm({ ...productForm, stock: e.target.value })} data-testid="product-stock-input" />
              <Input placeholder="SKU" value={productForm.sku} onChange={e => setProductForm({ ...productForm, sku: e.target.value })} data-testid="product-sku-input" />
            </div>
            <Input placeholder="Barcode (UPC/EAN) — scan or type" value={productForm.barcode} onChange={e => setProductForm({ ...productForm, barcode: e.target.value })} data-testid="product-barcode-input" />
            {editingProduct && (
              <ProductVariants product={editingProduct} onChanged={fetchData} />
            )}
            <div>
              <label className="text-xs font-medium text-gray-500 mb-1 block">Image</label>
              {productForm.image && <img src={productForm.image} alt="" className="w-full h-32 object-cover rounded mb-2 border" />}
              <div className="flex flex-wrap gap-2">
                <Input placeholder="Image URL or pick from library →" value={productForm.image} onChange={e => setProductForm({ ...productForm, image: e.target.value })} data-testid="product-image-input" />
                <Button type="button" variant="outline" onClick={() => setImageLibraryOpen(true)} data-testid="open-image-library">
                  <ImageIcon size={14} className="mr-1.5" /> Library
                </Button>
              </div>
            </div>
            <Input type="number" step="0.1" placeholder="GST Rate %" value={productForm.gstRate} onChange={e => setProductForm({ ...productForm, gstRate: e.target.value })} />
            <textarea className="w-full min-h-[60px] p-2 border rounded-md text-sm resize-none" placeholder="Item description..." value={productForm.description} onChange={e => setProductForm({ ...productForm, description: e.target.value })} data-testid="product-desc" />
            <textarea className="w-full min-h-[40px] p-2 border rounded-md text-sm resize-none" placeholder="SEO description (for online channels)..." value={productForm.seoDescription} onChange={e => setProductForm({ ...productForm, seoDescription: e.target.value })} data-testid="product-seo" />
            <div>
              <label className="text-xs font-medium text-gray-500 mb-1 block">Locations</label>
              <Input placeholder="Comma-separated: Main, Branch 1" value={(productForm.locations || []).join(', ')} onChange={e => setProductForm({ ...productForm, locations: e.target.value.split(',').map(s => s.trim()).filter(Boolean) })} data-testid="product-locations" />
            </div>
            <div>
              <label className="text-xs font-medium text-gray-500 mb-1 block">Online Channels</label>
              <div className="flex flex-wrap gap-1.5">
                {['Website', 'Uber Eats', 'DoorDash', 'Menulog', 'Deliveroo', 'Google Food'].map(ch => (
                  <button key={ch} type="button" onClick={() => {
                    const chs = (productForm.onlineChannels || []).includes(ch) ? productForm.onlineChannels.filter(c => c !== ch) : [...(productForm.onlineChannels || []), ch];
                    setProductForm({ ...productForm, onlineChannels: chs });
                  }} className={`px-2 py-1 text-xs rounded-full font-medium ${(productForm.onlineChannels || []).includes(ch) ? 'bg-gray-900 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'}`}>
                    {ch}
                  </button>
                ))}
              </div>
            </div>
            <div>
              <label className="text-xs font-medium text-gray-500 mb-1 block">Modifiers (select multiple)</label>
              {modifiers.length === 0 ? (
                <p className="text-xs text-gray-400 italic">No modifiers defined yet. Create some at <span className="font-mono">/modifiers</span> to use them here.</p>
              ) : (
                <div className="flex flex-wrap gap-1.5 max-h-32 overflow-y-auto p-2 border rounded-md bg-gray-50" data-testid="product-modifiers-picker">
                  {modifiers.map(m => {
                    const on = (productForm.modifierIds || []).includes(m.id);
                    return (
                      <button key={m.id} type="button" onClick={() => toggleModifierForProduct(m.id)}
                        className={`px-2.5 py-1 text-xs rounded-full font-medium transition-colors border ${on ? 'text-white border-transparent' : 'bg-white text-gray-700 border-gray-200 hover:border-gray-400'}`}
                        style={on ? { background: theme.primary } : {}}
                        data-testid={`mod-toggle-${m.id}`}
                        title={`${m.options?.length || 0} options${m.mandatory ? ' · required' : ''}`}
                      >
                        {m.name}
                        {m.mandatory ? <span className="ml-1 opacity-70">*</span> : null}
                        {m.multiSelect ? <span className="ml-1 opacity-70">+</span> : null}
                      </button>
                    );
                  })}
                </div>
              )}
              {(productForm.modifierIds || []).length > 0 && (
                <p className="text-[10px] text-gray-500 mt-1">{productForm.modifierIds.length} selected · tap a chip to toggle</p>
              )}
            </div>
            <Button className="w-full" style={{ backgroundColor: theme.primary }} onClick={saveProduct} data-testid="save-product-btn">
              {editingProduct ? 'Update Product' : 'Create Product'}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Menu Translations Dialog — per-language name/description overrides shown
          on the kiosk, QR table order, and online storefront customer surfaces. */}
      <Dialog open={showTranslateDialog} onOpenChange={setShowTranslateDialog}>
        <DialogContent className="max-w-lg max-h-[85vh] overflow-y-auto" data-testid="translate-dialog">
          <DialogHeader>
            <DialogTitle>Menu Translations{translatingProduct ? ` — ${translatingProduct.name}` : ''}</DialogTitle>
          </DialogHeader>
          <p className="text-xs text-gray-500 -mt-2">
            Leave a language blank to show the English name/description on customer-facing menus.
          </p>
          <Button
            variant="outline"
            className="w-full gap-2"
            onClick={autoTranslateProduct}
            disabled={autoTranslating}
            data-testid="auto-translate-btn"
          >
            <Sparkles className="w-4 h-4" style={{ color: '#8b5cf6' }} />
            {autoTranslating ? 'Drafting translations…' : 'Draft all languages with AI'}
          </Button>
          <div className="space-y-4">
            {LANGUAGES.filter(l => l.code !== 'en').map(l => (
              <div key={l.code} className="border rounded-lg p-3 space-y-2">
                <p className="text-xs font-semibold text-gray-500">{l.label}</p>
                <Input
                  placeholder={translatingProduct?.name || 'Name'}
                  value={translationForm[l.code]?.name || ''}
                  onChange={e => setTranslationField(l.code, 'name', e.target.value)}
                  dir={l.dir}
                  data-testid={`translate-name-${l.code}`}
                />
                <Textarea
                  rows={2}
                  placeholder={translatingProduct?.description || 'Description'}
                  value={translationForm[l.code]?.description || ''}
                  onChange={e => setTranslationField(l.code, 'description', e.target.value)}
                  dir={l.dir}
                  data-testid={`translate-desc-${l.code}`}
                />
              </div>
            ))}
          </div>
          <Button className="w-full mt-2" style={{ backgroundColor: theme.primary }} onClick={saveTranslations} data-testid="save-translations-btn">
            Save Translations
          </Button>
        </DialogContent>
      </Dialog>

      {/* Promotion Dialog */}
      {/* Promotion Dialog */}
      <PromotionDialog
        open={showPromoDialog}
        onClose={() => setShowPromoDialog(false)}
        theme={theme}
        editingPromo={editingPromo}
        promoForm={promoForm}
        setPromoForm={setPromoForm}
        onSave={savePromo}
        categories={categories}
        products={products}
      />

      {/* Image Library — for the single-product dialog */}
      <ImageLibrary
        open={imageLibraryOpen}
        onClose={() => setImageLibraryOpen(false)}
        onPick={(dataUrl) => setProductForm(prev => ({ ...prev, image: dataUrl }))}
        themeColor={theme.primary}
      />

      {/* Image Library — for bulk apply */}
      <ImageLibrary
        open={bulkImageLibraryOpen}
        onClose={() => setBulkImageLibraryOpen(false)}
        onPick={(dataUrl) => setBulkPatch(prev => ({ ...prev, image: dataUrl }))}
        themeColor={theme.primary}
      />

      <BulkEditDialog
        open={bulkOpen}
        onClose={() => setBulkOpen(false)}
        theme={theme}
        selectedCount={selected.size}
        bulkPatch={bulkPatch}
        setBulkPatch={setBulkPatch}
        bulkRows={bulkRows}
        updateBulkRow={updateBulkRow}
        fillBulkRows={fillBulkRows}
        categories={categories}
        modifiers={modifiers}
        onApply={applyBulk}
        onOpenImageLibrary={() => setBulkImageLibraryOpen(true)}
      />
    </div>
  );
};

export default Products;
