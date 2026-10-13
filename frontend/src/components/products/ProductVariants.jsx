import React, { useEffect, useState } from 'react';
import { Plus, Trash2 } from 'lucide-react';
import { Button } from '../ui/button';
import { Input } from '../ui/input';
import { productsAPI } from '../../services/api';
import { toast } from 'sonner';
import { DialogService } from '../../platform';

const BLANK_VARIANT = { label: '', sku: '', barcode: '', price: '', stock: '' };

// Each variant (e.g. "Size: M, Color: Red") is its own full Product row,
// linked back to the parent via parentId — same CRUD, same stock tracking,
// same POS search as any other product, just grouped under this one in the
// edit UI. Only rendered for an already-saved product (a variant needs a
// real parentId to point at).
export function ProductVariants({ product, onChanged }) {
  const [variants, setVariants] = useState([]);
  const [loading, setLoading] = useState(true);
  const [form, setForm] = useState(BLANK_VARIANT);
  const [adding, setAdding] = useState(false);

  const load = () => {
    setLoading(true);
    productsAPI.variants(product.id).then(r => setVariants(r.data || [])).catch(() => {}).finally(() => setLoading(false));
  };
  useEffect(load, [product.id]); // eslint-disable-line

  const addVariant = async () => {
    if (!form.label.trim()) { toast.error('Give this variant a label, e.g. "Medium / Red"'); return; }
    setAdding(true);
    try {
      await productsAPI.create({
        name: `${product.name} — ${form.label.trim()}`,
        category: product.category, categoryId: product.categoryId || null,
        price: form.price !== '' ? parseFloat(form.price) : product.price,
        cost: product.cost || 0,
        stock: form.stock !== '' ? parseInt(form.stock) : 0,
        sku: form.sku.trim(), barcode: form.barcode.trim(),
        parentId: product.id,
        variantAttributes: { label: form.label.trim() },
        gstRate: product.gstRate, image: product.image,
      });
      // The grouping row itself isn't sold — flag it so POS search skips it
      // once it has at least one real variant to sell instead.
      if (!product.hasVariants) await productsAPI.update(product.id, { hasVariants: true });
      setForm(BLANK_VARIANT);
      load();
      onChanged?.();
      toast.success('Variant added');
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Failed to add variant');
    } finally { setAdding(false); }
  };

  const deleteVariant = async (id) => {
    if (!await DialogService.confirm('Delete this variant?')) return;
    try {
      await productsAPI.delete(id);
      load();
      onChanged?.();
    } catch { toast.error('Failed to delete variant'); }
  };

  return (
    <div className="border rounded-md p-3 bg-gray-50 space-y-2" data-testid="product-variants-section">
      <label className="text-xs font-medium text-gray-500 block">
        Variants {variants.length > 0 && <span className="text-gray-400">({variants.length})</span>}
      </label>
      <p className="text-[11px] text-gray-400">
        Sizes, colors, or other options — each gets its own SKU, barcode, price, and stock count.
      </p>
      {!loading && variants.length > 0 && (
        <div className="space-y-1">
          {variants.map(v => (
            <div key={v.id} className="flex items-center justify-between text-xs bg-white border rounded px-2 py-1.5" data-testid={`variant-row-${v.id}`}>
              <div>
                <span className="font-medium">{v.variantAttributes?.label || v.name}</span>
                <span className="text-gray-400 ml-2">${Number(v.price || 0).toFixed(2)} · stock {v.stock}{v.sku ? ` · ${v.sku}` : ''}</span>
              </div>
              <button onClick={() => deleteVariant(v.id)} className="text-gray-400 hover:text-red-500" data-testid={`delete-variant-${v.id}`}>
                <Trash2 size={13} />
              </button>
            </div>
          ))}
        </div>
      )}
      <div className="grid grid-cols-2 gap-1.5 pt-1">
        <Input className="h-8 text-xs" placeholder="Label (e.g. Medium / Red)" value={form.label} onChange={e => setForm({ ...form, label: e.target.value })} data-testid="variant-label-input" />
        <Input className="h-8 text-xs" placeholder="SKU" value={form.sku} onChange={e => setForm({ ...form, sku: e.target.value })} data-testid="variant-sku-input" />
        <Input className="h-8 text-xs" placeholder="Barcode" value={form.barcode} onChange={e => setForm({ ...form, barcode: e.target.value })} data-testid="variant-barcode-input" />
        <Input className="h-8 text-xs" type="number" placeholder={`Price (default $${product.price})`} value={form.price} onChange={e => setForm({ ...form, price: e.target.value })} data-testid="variant-price-input" />
        <Input className="h-8 text-xs col-span-2" type="number" placeholder="Stock" value={form.stock} onChange={e => setForm({ ...form, stock: e.target.value })} data-testid="variant-stock-input" />
      </div>
      <Button type="button" size="sm" variant="outline" className="w-full h-7 text-xs" disabled={adding} onClick={addVariant} data-testid="add-variant-btn">
        <Plus size={12} className="mr-1" /> Add Variant
      </Button>
    </div>
  );
}
