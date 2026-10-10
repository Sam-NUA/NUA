import React, { useState, useEffect, useMemo } from 'react';
import { Package, AlertTriangle, TrendingDown, Search, Plus, Minus, ArrowUp, ArrowDown, ArrowUpDown, FileSpreadsheet, FileText } from 'lucide-react';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Card, CardContent } from '../components/ui/card';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '../components/ui/dialog';
import { useTheme } from '../contexts/ThemeContext';
import { productsAPI } from '../services/api';
import { toast } from 'sonner';

const Inventory = () => {
  const { theme } = useTheme();
  const [searchTerm, setSearchTerm] = useState('');
  const [products, setProducts] = useState([]);
  const [showAdjust, setShowAdjust] = useState(false);
  const [adjustProduct, setAdjustProduct] = useState(null);
  const [adjustment, setAdjustment] = useState('');
  const [reason, setReason] = useState('Manual count');
  const [sortBy, setSortBy] = useState('name');
  const [sortDir, setSortDir] = useState('asc');

  useEffect(() => { fetchProducts(); }, []);

  const fetchProducts = async () => {
    try { const r = await productsAPI.getAll(); setProducts(r.data); } catch { toast.error('Failed to load products'); }
  };

  const openAdjust = (product) => { setAdjustProduct(product); setAdjustment(''); setReason('Manual count'); setShowAdjust(true); };

  const handleAdjust = async () => {
    if (!adjustment || parseInt(adjustment) === 0) { toast.error('Enter a non-zero adjustment'); return; }
    try {
      await productsAPI.adjustStock(adjustProduct.id, { adjustment: parseInt(adjustment), reason });
      toast.success(`Stock adjusted for ${adjustProduct.name}`);
      setShowAdjust(false);
      fetchProducts();
    } catch (e) { toast.error(e.response?.data?.detail || 'Failed to adjust stock'); }
  };

  // Same threshold the backend's low-stock PDF/Excel exports and NUA's own
  // alerts use (lowStockThreshold, falling back to parLevel, then 5) — this
  // used to be a hardcoded "< 100" here, which flagged almost every product
  // as low stock and had nothing to do with what got exported.
  const isLowStock = (p) => p.stock <= (p.lowStockThreshold ?? p.parLevel ?? 5);
  const lowStockProducts = products.filter(isLowStock);
  const totalValue = products.reduce((sum, p) => sum + (p.cost * p.stock), 0);
  const totalUnits = products.reduce((sum, p) => sum + p.stock, 0);

  const toggleSort = (column) => {
    if (sortBy === column) setSortDir(sortDir === 'asc' ? 'desc' : 'asc');
    else { setSortBy(column); setSortDir('asc'); }
  };
  const SortIcon = ({ column }) => {
    if (sortBy !== column) return <ArrowUpDown size={12} className="opacity-30" />;
    return sortDir === 'asc' ? <ArrowUp size={12} /> : <ArrowDown size={12} />;
  };

  const filteredProducts = useMemo(() => {
    const filtered = products.filter(p =>
      p.name.toLowerCase().includes(searchTerm.toLowerCase()) || (p.sku && p.sku.toLowerCase().includes(searchTerm.toLowerCase()))
    );
    const dir = sortDir === 'asc' ? 1 : -1;
    return [...filtered].sort((a, b) => {
      if (sortBy === 'stock') return (a.stock - b.stock) * dir;
      if (sortBy === 'category') return (a.category || '').localeCompare(b.category || '') * dir || a.name.localeCompare(b.name);
      return a.name.localeCompare(b.name) * dir;
    });
  }, [products, searchTerm, sortBy, sortDir]);

  return (
    <div className="space-y-6" data-testid="inventory-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold" style={{ color: theme.text }}>Inventory Management</h1>
          <p className="text-gray-500 mt-1">Track stock levels and adjust inventory</p>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
        <Card><CardContent className="p-6"><p className="text-sm text-gray-500">Total Items</p><p className="text-3xl font-bold" style={{ color: theme.primary }}>{products.length}</p></CardContent></Card>
        <Card><CardContent className="p-6"><p className="text-sm text-gray-500">Inventory Value</p><p className="text-3xl font-bold" style={{ color: theme.text }}>${totalValue.toFixed(2)}</p></CardContent></Card>
        <Card><CardContent className="p-6"><p className="text-sm text-gray-500">Low Stock</p><p className="text-3xl font-bold text-[#8a4a00]">{lowStockProducts.length}</p></CardContent></Card>
        <Card><CardContent className="p-6"><p className="text-sm text-gray-500">Total Units</p><p className="text-3xl font-bold" style={{ color: theme.text }}>{totalUnits}</p></CardContent></Card>
      </div>

      {lowStockProducts.length > 0 && (
        <Card className="border-[#d97706]/40 bg-[rgba(245,140,20,0.14)]"><CardContent className="p-4">
          <div className="flex items-center gap-2 mb-1">
            <AlertTriangle size={20} className="text-[#8a4a00]" />
            <h3 className="font-semibold text-[#8a4a00]">Low Stock Alert</h3>
            <div className="ml-auto flex items-center gap-3">
              <a
                href={`${process.env.REACT_APP_BACKEND_URL}/api/inventory/low-stock/pdf`}
                target="_blank"
                rel="noreferrer"
                className="flex items-center gap-1 text-xs text-blue-600 underline hover:no-underline"
                data-testid="low-stock-pdf-btn"
              >
                <FileText size={12} /> PDF
              </a>
              <a
                href={`${process.env.REACT_APP_BACKEND_URL}/api/inventory/low-stock/xlsx`}
                target="_blank"
                rel="noreferrer"
                className="flex items-center gap-1 text-xs text-blue-600 underline hover:no-underline"
                data-testid="low-stock-xlsx-btn"
              >
                <FileSpreadsheet size={12} /> Excel
              </a>
            </div>
          </div>
          <details className="text-sm text-amber-900 dark:text-amber-200 mt-2">
            <summary className="cursor-pointer py-2">{lowStockProducts.length} items need restocking — view items</summary>
            <ul className="mt-2 max-h-48 overflow-y-auto space-y-1 list-disc pl-5">
              {lowStockProducts.map(p => <li key={p.id}>{p.name}{p.sku ? ` · ${p.sku}` : ''}</li>)}
            </ul>
          </details>
        </CardContent></Card>
      )}

      <div className="relative">
        <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400" size={20} />
        <Input placeholder="Search by product name or SKU..." className="pl-10" value={searchTerm} onChange={e => setSearchTerm(e.target.value)} data-testid="inventory-search" />
      </div>

      <Card><CardContent className="p-0"><div className="overflow-x-auto">
        <table className="w-full" data-testid="inventory-table">
          <thead className="bg-gray-50"><tr>
            <th className="text-left p-4 text-sm font-medium text-gray-500">
              <button className="flex items-center gap-1 hover:text-gray-800" onClick={() => toggleSort('name')} data-testid="sort-product">
                Product <SortIcon column="name" />
              </button>
            </th>
            <th className="text-left p-4 text-sm font-medium text-gray-500">SKU</th>
            <th className="text-left p-4 text-sm font-medium text-gray-500">
              <button className="flex items-center gap-1 hover:text-gray-800" onClick={() => toggleSort('category')} data-testid="sort-category">
                Category <SortIcon column="category" />
              </button>
            </th>
            <th className="text-right p-4 text-sm font-medium text-gray-500">
              <button className="flex items-center gap-1 ml-auto hover:text-gray-800" onClick={() => toggleSort('stock')} data-testid="sort-stock">
                Stock <SortIcon column="stock" />
              </button>
            </th>
            <th className="text-right p-4 text-sm font-medium text-gray-500">Cost</th>
            <th className="text-right p-4 text-sm font-medium text-gray-500">Value</th>
            <th className="text-center p-4 text-sm font-medium text-gray-500">Status</th>
            <th className="text-center p-4 text-sm font-medium text-gray-500">Actions</th>
          </tr></thead>
          <tbody>
            {filteredProducts.map(product => {
              const stockValue = product.cost * product.stock;
              const isLow = isLowStock(product);
              return (
                <tr key={product.id} className="border-t hover:bg-gray-50" data-testid={`inventory-row-${product.id}`}>
                  <td className="p-4"><div className="flex items-center gap-3">
                    <img src={product.image || 'https://placehold.co/40x40/e5e7eb/9ca3af?text=NUA'} alt={product.name} className="w-10 h-10 rounded object-cover" />
                    <span className="font-medium">{product.name}</span>
                  </div></td>
                  <td className="p-4 font-mono text-sm text-gray-600">{product.sku}</td>
                  <td className="p-4 text-sm">{product.category}</td>
                  <td className="p-4 text-right font-bold" style={{ color: product.stock <= 0 ? '#B01B1B' : isLow ? '#8a4a00' : '#046C4E' }}>{product.stock}</td>
                  <td className="p-4 text-right text-sm">${Number(product.cost).toFixed(2)}</td>
                  <td className="p-4 text-right font-medium" style={{ color: theme.primary }}>${stockValue.toFixed(2)}</td>
                  <td className="p-4 text-center">
                    {/* Stock level colours per NUA_POS_DESIGN_TOKENS.md §6. */}
                    <span className={`px-2 py-1 rounded-full text-xs font-medium ${
                      product.stock <= 0 ? 'bg-[rgba(176,27,27,0.10)] text-[#B01B1B]'
                      : isLow ? 'bg-[rgba(245,140,20,0.14)] text-[#8a4a00]'
                      : 'bg-[rgba(16,185,129,0.12)] text-[#046C4E]'}`}>
                      {product.stock <= 0 ? 'Out of Stock' : isLow ? 'Low Stock' : 'In Stock'}
                    </span>
                  </td>
                  <td className="p-4 text-center">
                    <Button variant="outline" size="sm" onClick={() => openAdjust(product)} data-testid={`adjust-stock-${product.id}`}>
                      Adjust
                    </Button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div></CardContent></Card>

      {/* Stock Adjustment Dialog */}
      <Dialog open={showAdjust} onOpenChange={setShowAdjust}>
        <DialogContent className="max-w-sm" data-testid="stock-adjust-dialog">
          <DialogHeader><DialogTitle>Adjust Stock — {adjustProduct?.name}</DialogTitle></DialogHeader>
          <div className="space-y-3 py-2">
            <p className="text-sm text-gray-500">Current stock: <span className="font-bold">{adjustProduct?.stock}</span></p>
            <Input type="number" placeholder="Adjustment (+/- quantity)" value={adjustment} onChange={e => setAdjustment(e.target.value)} data-testid="adjust-qty-input" />
            <select className="w-full p-2 border rounded-md text-sm" value={reason} onChange={e => setReason(e.target.value)} data-testid="adjust-reason">
              <option>Manual count</option><option>Received shipment</option><option>Damaged / waste</option><option>Returned to supplier</option><option>Other</option>
            </select>
            {adjustment && (
              <p className="text-sm">New stock: <span className="font-bold" style={{ color: theme.primary }}>{adjustProduct?.stock + parseInt(adjustment || 0)}</span></p>
            )}
            <Button className="w-full" style={{ backgroundColor: theme.primary }} onClick={handleAdjust} data-testid="confirm-adjust-btn">Apply Adjustment</Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default Inventory;
