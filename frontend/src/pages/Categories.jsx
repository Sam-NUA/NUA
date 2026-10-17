import React, { useState, useEffect, useMemo } from 'react';
import {
  Plus, Edit, Trash2, GripVertical, GitMerge, CornerDownRight, BarChart3,
  // Icon options users can choose from
  Coffee, UtensilsCrossed, Beef, Cake, Soup, Croissant, Wine, Pizza,
  IceCream, Salad, Sandwich, Cookie, EggFried, Fish, Beer, GlassWater,
  Apple, Carrot, Drumstick, Tag, Sparkles
} from 'lucide-react';
import { Card, CardContent } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Badge } from '../components/ui/badge';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '../components/ui/dialog';
import { useTheme } from '../contexts/ThemeContext';
import { itemsSystemAPI, productsAPI } from '../services/api';
import { toast } from 'sonner';
import { DialogService } from '../platform';

// Whitelist of icons the owner can pick (kept lean so bundle stays small).
export const CATEGORY_ICON_MAP = {
  Coffee, UtensilsCrossed, Beef, Cake, Soup, Croissant, Wine, Pizza,
  IceCream, Salad, Sandwich, Cookie, EggFried, Fish, Beer, GlassWater,
  Apple, Carrot, Drumstick, Tag, Sparkles,
};

export function CategoryIcon({ name, size = 18, className = '', style = {} }) {
  const Icon = CATEGORY_ICON_MAP[name] || Tag;
  return <Icon size={size} className={className} style={style} />;
}

const COLOR_SWATCHES = [
  '#92400e', '#dc2626', '#16a34a', '#db2777', '#ea580c',
  '#0ea5e9', '#8b5cf6', '#f59e0b', '#10b981', '#ef4444',
  '#6366f1', '#14b8a6', '#a855f7', '#84cc16', '#475569',
];

const BLANK = {
  name: '', sortOrder: 0, active: true, icon: 'Tag', color: '#6366f1', prepTime: 8,
  channels: ['dine-in', 'pickup', 'delivery'], parentId: '', reportsUnderId: '',
};
const CHANNELS = [
  { key: 'dine-in', label: 'Dine-in' },
  { key: 'pickup', label: 'Pickup' },
  { key: 'delivery', label: 'Delivery' },
];

// Every id reachable by walking `field` (parentId/reportsUnderId) downward from
// `rootId` — used to keep a category from being nested under / reporting
// under its own descendant (the backend re-checks this; this just keeps the
// dropdown from offering an invalid choice in the first place).
function descendantIds(rootId, categories, field) {
  const children = categories.filter(c => c[field] === rootId).map(c => c.id);
  return children.reduce((acc, id) => [...acc, ...descendantIds(id, categories, field)], children);
}

export default function Categories() {
  const { theme } = useTheme();
  const [categories, setCategories] = useState([]);
  const [products, setProducts] = useState([]);
  const [showDialog, setShowDialog] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(BLANK);
  const [cleaning, setCleaning] = useState(false);
  // Drag-and-drop state
  const [dragId, setDragId] = useState(null);
  const [overId, setOverId] = useState(null);
  const [dropAction, setDropAction] = useState(null); // { source, target }
  const [merging, setMerging] = useState(false);

  useEffect(() => { fetchData(); }, []);
  const fetchData = async () => {
    const [catsRes, prodsRes] = await Promise.allSettled([
      itemsSystemAPI.getCategories(),
      productsAPI.getAll(),
    ]);
    if (catsRes.status === 'fulfilled') setCategories(catsRes.value.data);
    if (prodsRes.status === 'fulfilled') setProducts(prodsRes.value.data || []);
  };

  const countByCategory = useMemo(() => {
    const counts = {};
    for (const p of products) {
      const key = p.categoryId || p.category;
      if (key) counts[key] = (counts[key] || 0) + 1;
    }
    return counts;
  }, [products]);

  const itemCount = (cat) => (countByCategory[cat.id] || 0) + (countByCategory[cat.name] || 0);

  const byId = useMemo(() => Object.fromEntries(categories.map(c => [c.id, c])), [categories]);

  // Tree: root categories (no parent) with their children nested beneath,
  // each level sorted by sortOrder.
  const tree = useMemo(() => {
    const byParent = {};
    for (const c of categories) {
      const key = c.parentId || '__root__';
      (byParent[key] = byParent[key] || []).push(c);
    }
    Object.values(byParent).forEach(list => list.sort((a, b) => (a.sortOrder ?? 0) - (b.sortOrder ?? 0)));
    const build = (parentKey, depth) => (byParent[parentKey] || []).flatMap(c => [
      { ...c, depth }, ...build(c.id, depth + 1),
    ]);
    return build('__root__', 0);
  }, [categories]);

  const openAdd = () => { setEditing(null); setForm({ ...BLANK, sortOrder: categories.length }); setShowDialog(true); };
  const openEdit = (c) => {
    setEditing(c);
    setForm({
      name: c.name, sortOrder: c.sortOrder, active: c.active,
      icon: c.icon || 'Tag', color: c.color || '#6366f1',
      prepTime: c.prepTime ?? 8,
      channels: c.channels || ['dine-in', 'pickup', 'delivery'],
      parentId: c.parentId || '', reportsUnderId: c.reportsUnderId || '',
    });
    setShowDialog(true);
  };

  const handleSave = async () => {
    if (!form.name) { toast.error('Name required'); return; }
    const payload = { ...form, parentId: form.parentId || null, reportsUnderId: form.reportsUnderId || null };
    try {
      if (editing) { await itemsSystemAPI.updateCategory(editing.id, payload); toast.success('Category updated'); }
      else { await itemsSystemAPI.createCategory(payload); toast.success('Category created'); }
      setShowDialog(false); fetchData();
    } catch (e) { toast.error(e?.response?.data?.detail || 'Failed'); }
  };

  const handleDelete = async (id) => {
    if (!await DialogService.confirm('Delete this category? Items in it will become uncategorized.')) return;
    try { await itemsSystemAPI.deleteCategory(id); toast.success('Deleted'); fetchData(); } catch {}
  };

  const handleCleanup = async () => {
    if (!await DialogService.confirm('Remove demo categories (Beverages/Food/Bakery/Alcohol/Desserts) that have no products?')) return;
    setCleaning(true);
    try {
      const r = await itemsSystemAPI.cleanupLegacyCategories();
      toast.success(`Removed ${r.data.removed.length} demo categor${r.data.removed.length === 1 ? 'y' : 'ies'}`);
      if (r.data.keptWithProducts?.length) {
        toast.message(`Kept ${r.data.keptWithProducts.length} (still has products)`);
      }
      fetchData();
    } catch (e) { toast.error(e?.response?.data?.detail || 'Failed'); }
    finally { setCleaning(false); }
  };

  const toggleChannel = (key) => setForm(f => ({
    ...f,
    channels: f.channels.includes(key) ? f.channels.filter(c => c !== key) : [...f.channels, key],
  }));

  // ----- Drag and drop -----
  const onDragStart = (e, cat) => { setDragId(cat.id); e.dataTransfer.effectAllowed = 'move'; };
  const onDragOver = (e, cat) => {
    if (cat.id === dragId) return;
    e.preventDefault();
    setOverId(cat.id);
  };
  const onDrop = (e, targetCat) => {
    e.preventDefault();
    setOverId(null);
    if (!dragId || dragId === targetCat.id) return;
    const source = byId[dragId];
    if (!source) return;
    setDropAction({ source, target: targetCat });
    setDragId(null);
  };

  const confirmMerge = async () => {
    if (!dropAction) return;
    setMerging(true);
    try {
      const r = await itemsSystemAPI.mergeCategory(dropAction.source.id, dropAction.target.id);
      toast.success(r.data.message, { description: `${r.data.productsMoved} item(s) moved` });
      setDropAction(null);
      fetchData();
    } catch (e) { toast.error(e?.response?.data?.detail || 'Merge failed'); }
    finally { setMerging(false); }
  };

  const confirmNest = async () => {
    if (!dropAction) return;
    try {
      await itemsSystemAPI.updateCategory(dropAction.source.id, { parentId: dropAction.target.id });
      toast.success(`${dropAction.source.name} is now a sub-category of ${dropAction.target.name}`);
      setDropAction(null);
      fetchData();
    } catch (e) { toast.error(e?.response?.data?.detail || 'Could not nest category'); }
  };

  // Options for the "Sub-category of" / "Reports under" pickers — exclude
  // self and any descendant (would create a cycle the backend would reject).
  const parentOptions = editing
    ? categories.filter(c => c.id !== editing.id && !descendantIds(editing.id, categories, 'parentId').includes(c.id))
    : categories;
  const reportOptions = editing
    ? categories.filter(c => c.id !== editing.id && !descendantIds(editing.id, categories, 'reportsUnderId').includes(c.id))
    : categories;

  return (
    <div className="space-y-6" data-testid="categories-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold" style={{ color: theme.text }}>Categories</h1>
          <p className="text-sm text-gray-500">
            Drag one category onto another to merge or nest it as a sub-category.
          </p>
        </div>
        <Button style={{ backgroundColor: theme.primary }} onClick={openAdd} data-testid="add-category-btn">
          <Plus size={16} className="mr-1" /> New Category
        </Button>
      </div>

      <div className="flex justify-end -mt-2">
        <Button variant="outline" size="sm" onClick={handleCleanup} disabled={cleaning} data-testid="cleanup-legacy-btn">
          {cleaning ? 'Cleaning…' : 'Remove demo categories'}
        </Button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
        {tree.map((cat) => {
          const parent = cat.parentId ? byId[cat.parentId] : null;
          const reportsAs = cat.reportsUnderId ? byId[cat.reportsUnderId] : null;
          const isOver = overId === cat.id && dragId && dragId !== cat.id;
          return (
            <Card key={cat.id} data-testid={`cat-${cat.id}`}
              draggable
              onDragStart={(e) => onDragStart(e, cat)}
              onDragOver={(e) => onDragOver(e, cat)}
              onDragLeave={() => setOverId(o => (o === cat.id ? null : o))}
              onDrop={(e) => onDrop(e, cat)}
              style={{ marginLeft: cat.depth * 28, ...(isOver ? { '--tw-ring-color': theme.primary } : {}) }}
              className={`transition-shadow cursor-grab active:cursor-grabbing ${isOver ? 'ring-2 ring-offset-1' : 'hover:shadow-md'}`}>
              <CardContent className="p-4 flex items-center justify-between">
                <div className="flex items-center gap-3 min-w-0">
                  {cat.depth > 0 && <CornerDownRight size={14} className="text-gray-300 flex-shrink-0" />}
                  <GripVertical size={16} className="text-gray-300 flex-shrink-0" />
                  <div className="w-10 h-10 rounded-xl flex items-center justify-center text-white shadow-sm flex-shrink-0"
                    style={{ background: cat.color || '#6366f1' }}>
                    <CategoryIcon name={cat.icon} size={20} />
                  </div>
                  <div className="min-w-0">
                    <h3 className="font-medium truncate">{cat.name}</h3>
                    <p className="text-xs text-gray-400 truncate">
                      Sort {cat.sortOrder} · {itemCount(cat)} item{itemCount(cat) === 1 ? '' : 's'} · ⏱ {cat.prepTime ?? '—'} min
                    </p>
                    <div className="flex flex-wrap gap-1 mt-1">
                      {parent && (
                        <span className="text-[9px] font-bold uppercase px-1.5 py-0.5 rounded bg-indigo-50 text-indigo-600" title={`Nested under ${parent.name}`}>
                          ↳ {parent.name}
                        </span>
                      )}
                      {reportsAs && (
                        <span className="text-[9px] font-bold uppercase px-1.5 py-0.5 rounded bg-amber-50 text-amber-700 flex items-center gap-0.5" title={`Sales report as ${reportsAs.name}`}>
                          <BarChart3 size={9} /> reports as {reportsAs.name}
                        </span>
                      )}
                      {(cat.channels && cat.channels.length > 0) && cat.channels.map(ch => (
                        <span key={ch} className="text-[9px] font-bold uppercase px-1.5 py-0.5 rounded bg-gray-100 text-gray-600">{ch}</span>
                      ))}
                    </div>
                  </div>
                  <Badge className={cat.active ? 'bg-green-100 text-green-700 flex-shrink-0' : 'bg-red-100 text-red-700 flex-shrink-0'}>
                    {cat.active ? 'Active' : 'Inactive'}
                  </Badge>
                </div>
                <div className="flex gap-2 flex-shrink-0">
                  <Button variant="outline" size="sm" onClick={() => openEdit(cat)} data-testid={`edit-cat-${cat.id}`}><Edit size={14} /></Button>
                  <Button variant="outline" size="sm" className="text-red-500" onClick={() => handleDelete(cat.id)}><Trash2 size={14} /></Button>
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>

      {/* Drop confirmation — merge (destructive) vs nest (safe) */}
      <Dialog open={!!dropAction} onOpenChange={(open) => !open && setDropAction(null)}>
        <DialogContent className="max-w-md" data-testid="drop-action-dialog">
          <DialogHeader>
            <DialogTitle>{dropAction?.source.name} → {dropAction?.target.name}</DialogTitle>
            <DialogDescription>Choose what dropping "{dropAction?.source.name}" onto "{dropAction?.target.name}" should do.</DialogDescription>
          </DialogHeader>
          <div className="space-y-3 py-2">
            <button onClick={confirmNest}
              className="w-full text-left p-3 rounded-lg border hover:border-gray-400 transition flex items-start gap-3"
              data-testid="drop-action-nest">
              <CornerDownRight size={18} className="mt-0.5 text-indigo-600 flex-shrink-0" />
              <div>
                <p className="font-medium text-sm">Nest as sub-category</p>
                <p className="text-xs text-gray-500 mt-0.5">
                  "{dropAction?.source.name}" stays a distinct category but is organised under "{dropAction?.target.name}" in this list. Nothing is deleted.
                </p>
              </div>
            </button>
            <button onClick={confirmMerge} disabled={merging}
              className="w-full text-left p-3 rounded-lg border border-red-200 hover:border-red-400 transition flex items-start gap-3 disabled:opacity-50"
              data-testid="drop-action-merge">
              <GitMerge size={18} className="mt-0.5 text-red-600 flex-shrink-0" />
              <div>
                <p className="font-medium text-sm text-red-700">{merging ? 'Merging…' : 'Merge categories'}</p>
                <p className="text-xs text-gray-500 mt-0.5">
                  All {dropAction ? itemCount(dropAction.source) : 0} item(s) in "{dropAction?.source.name}" move into
                  "{dropAction?.target.name}", then "{dropAction?.source.name}" is deleted. This can't be undone.
                </p>
              </div>
            </button>
            <Button variant="ghost" className="w-full" onClick={() => setDropAction(null)}>Cancel</Button>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={showDialog} onOpenChange={setShowDialog}>
        <DialogContent className="max-w-md" data-testid="category-dialog">
          <DialogHeader>
            <DialogTitle>{editing ? 'Edit Category' : 'New Category'}</DialogTitle>
            <DialogDescription>Choose a name, icon, and tile colour to use on the POS dashboard.</DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div className="flex items-center gap-3 p-3 rounded-lg border bg-gray-50">
              <div className="w-12 h-12 rounded-xl flex items-center justify-center text-white shadow"
                style={{ background: form.color }}>
                <CategoryIcon name={form.icon} size={22} />
              </div>
              <div className="flex-1">
                <p className="text-xs uppercase text-gray-500 font-bold tracking-widest">Preview</p>
                <p className="font-medium">{form.name || 'Category name'}</p>
              </div>
            </div>
            <div>
              <label className="text-xs uppercase text-gray-500 font-bold">Name</label>
              <Input placeholder="e.g. Coffee" value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} data-testid="cat-name-input" />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs uppercase text-gray-500 font-bold">Sort order</label>
                <Input type="number" value={form.sortOrder} onChange={e => setForm({ ...form, sortOrder: parseInt(e.target.value) || 0 })} />
              </div>
              <div className="flex items-end">
                <label className="flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={form.active} onChange={e => setForm({ ...form, active: e.target.checked })} />
                  Active
                </label>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs uppercase text-gray-500 font-bold flex items-center gap-1">
                  <CornerDownRight size={11} /> Sub-category of
                </label>
                <select value={form.parentId} onChange={e => setForm({ ...form, parentId: e.target.value })}
                  className="w-full h-9 px-2 rounded-md border text-sm mt-1" data-testid="cat-parent-select">
                  <option value="">None — top level</option>
                  {parentOptions.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
              </div>
              <div>
                <label className="text-xs uppercase text-gray-500 font-bold flex items-center gap-1">
                  <BarChart3 size={11} /> Reports under
                </label>
                <select value={form.reportsUnderId} onChange={e => setForm({ ...form, reportsUnderId: e.target.value })}
                  className="w-full h-9 px-2 rounded-md border text-sm mt-1" data-testid="cat-reports-select">
                  <option value="">None — reports as itself</option>
                  {reportOptions.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
                <p className="text-[10px] text-gray-400 mt-1">Sales revenue reports show this category's sales under the selected one.</p>
              </div>
            </div>
            <div>
              <label className="text-xs uppercase text-gray-500 font-bold">Icon</label>
              <div className="grid grid-cols-7 gap-2 mt-1" data-testid="cat-icon-grid">
                {Object.keys(CATEGORY_ICON_MAP).map(key => (
                  <button key={key} type="button"
                    onClick={() => setForm({ ...form, icon: key })}
                    className={`w-10 h-10 rounded-lg border flex items-center justify-center transition ${form.icon === key ? 'border-2 shadow-sm' : 'border-gray-200 hover:border-gray-400'}`}
                    style={form.icon === key ? { borderColor: form.color, background: `${form.color}15` } : {}}
                    title={key}
                    data-testid={`cat-icon-${key}`}>
                    <CategoryIcon name={key} size={18} style={form.icon === key ? { color: form.color } : {}} />
                  </button>
                ))}
              </div>
            </div>
            <div>
              <label className="text-xs uppercase text-gray-500 font-bold">Colour</label>
              <div className="flex gap-2 flex-wrap mt-1" data-testid="cat-color-row">
                {COLOR_SWATCHES.map(c => (
                  <button key={c} type="button"
                    onClick={() => setForm({ ...form, color: c })}
                    className={`w-8 h-8 rounded-full border-2 transition ${form.color === c ? 'border-gray-900 scale-110' : 'border-white shadow'}`}
                    style={{ background: c }}
                    data-testid={`cat-color-${c.replace('#','')}`} />
                ))}
                <input type="color" value={form.color}
                  onChange={e => setForm({ ...form, color: e.target.value })}
                  className="w-8 h-8 rounded-full border-0 cursor-pointer" />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs uppercase text-gray-500 font-bold">Prep time (min)</label>
                <Input type="number" min="0" max="120" value={form.prepTime}
                  onChange={e => setForm({ ...form, prepTime: parseInt(e.target.value) || 0 })}
                  data-testid="cat-prep-time" />
                <p className="text-[10px] text-gray-400 mt-1">Used for ETA calc on online orders</p>
              </div>
              <div>
                <label className="text-xs uppercase text-gray-500 font-bold">Channels</label>
                <div className="flex flex-wrap gap-1 mt-1" data-testid="cat-channels-row">
                  {CHANNELS.map(ch => {
                    const on = form.channels.includes(ch.key);
                    return (
                      <button key={ch.key} type="button" onClick={() => toggleChannel(ch.key)}
                        className={`px-2 py-1 text-xs rounded-full transition ${on ? 'text-white' : 'bg-gray-100 text-gray-500 hover:bg-gray-200'}`}
                        style={on ? { background: form.color } : {}}
                        data-testid={`cat-channel-${ch.key}`}>
                        {ch.label}
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>
            <Button className="w-full" style={{ backgroundColor: theme.primary }} onClick={handleSave} data-testid="save-cat-btn">
              {editing ? 'Update' : 'Create'}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
