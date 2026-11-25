import React, { useState, useEffect } from 'react';
import {
  Star, TrendingUp, TrendingDown, HelpCircle, XCircle, DollarSign,
  Percent, BarChart3, ArrowUpRight, ArrowDownRight, Upload, Loader2, Sliders
} from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '../components/ui/dialog';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs';
import { useTheme } from '../contexts/ThemeContext';
import { analyticsAPI, menuFeaturesAPI } from '../services/api';
import { toast } from 'sonner';
import AIMenuImportReview from '../components/menu/AIMenuImportReview';

const CLASS_CONFIG = {
  star: { label: 'Star', icon: Star, color: '#F59E0B', bg: '#FFFBEB', desc: 'High popularity, high profit' },
  puzzle: { label: 'Puzzle', icon: HelpCircle, color: '#8B5CF6', bg: '#F5F3FF', desc: 'Low popularity, high profit - promote more' },
  horse: { label: 'Workhorse', icon: TrendingUp, color: '#3B82F6', bg: '#EFF6FF', desc: 'High popularity, low profit - improve margin' },
  dog: { label: 'Dog', icon: XCircle, color: '#EF4444', bg: '#FEF2F2', desc: 'Low both - consider removing' },
};

export default function MenuEngineering() {
  const { theme } = useTheme();
  const [data, setData] = useState(null);
  const [matrixError, setMatrixError] = useState(false);
  const [tab, setTab] = useState('matrix');
  const [showImport, setShowImport] = useState(false);
  const [showPriceAdjust, setShowPriceAdjust] = useState(false);
  const [priceForm, setPriceForm] = useState({ category: '', type: 'percentage', amount: '', direction: 'increase' });

  const reloadMatrix = () => {
    setMatrixError(false);
    analyticsAPI.getMenuEngineering().then(r => setData(r.data))
      .catch(() => setMatrixError(true));
  };
  useEffect(() => { reloadMatrix(); }, []);

  const onCommitted = () => {
    analyticsAPI.getMenuEngineering().then(r => setData(r.data)).catch(() => {});
  };

  const handlePriceAdjust = async () => {
    if (!priceForm.amount) { toast.error('Enter an amount'); return; }
    try {
      const res = await menuFeaturesAPI.bulkPriceAdjust({
        category: priceForm.category || null,
        type: priceForm.type, amount: parseFloat(priceForm.amount), direction: priceForm.direction,
      });
      toast.success(res.data.message);
      setShowPriceAdjust(false);
      analyticsAPI.getMenuEngineering().then(r => setData(r.data)).catch(() => {});
    } catch { toast.error('Failed'); }
  };

  // Import is intentionally accessible when analytics is unavailable or
  // this venue has not generated sales yet: import is how the menu gets started.
  if (!data) return (
    <div className="space-y-4" data-testid="menu-engineering-page">
      <div className="flex flex-wrap justify-between items-center gap-3">
        <h1 className="text-2xl font-bold" style={{ color: theme.text }}>Menu Matrix</h1>
        <Button onClick={() => setShowImport(true)} data-testid="ai-import-btn">
          <Upload size={16} className="mr-1" /> Import menu
        </Button>
      </div>
      <p role={matrixError ? 'alert' : 'status'} className="text-sm text-gray-600">
        {matrixError ? 'Menu performance is unavailable. You can still import items below.' : 'Analyzing menu performance…'}
      </p>
      {matrixError && <Button variant="outline" onClick={reloadMatrix}>Retry analysis</Button>}
      <AIMenuImportReview open={showImport} onOpenChange={setShowImport} onCommitted={onCommitted} />
    </div>
  );

  const { items, categories, summary } = data;
  const totalRevenue = items.reduce((s, i) => s + i.revenue, 0);

  return (
    <div className="space-y-6" data-testid="menu-engineering-page">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold" style={{ color: theme.text }}>Menu Engineering</h1>
          <p className="text-sm text-gray-500 mt-1">Profit optimization, AI menu import & price management</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => setShowPriceAdjust(true)} data-testid="price-adjust-btn">
            <Sliders size={16} className="mr-1" /> Adjust Prices
          </Button>
          <Button style={{ backgroundColor: theme.primary }} onClick={() => setShowImport(true)} data-testid="ai-import-btn">
            <Upload size={16} className="mr-1" /> AI Menu Import
          </Button>
        </div>
      </div>

      {/* Matrix Summary */}
      <div className="grid grid-cols-4 gap-3">
        {Object.entries(CLASS_CONFIG).map(([key, config]) => {
          const Icon = config.icon;
          return (
            <Card key={key} className="border-0 shadow-sm cursor-pointer hover:shadow-md transition-shadow">
              <CardContent className="p-4">
                <div className="flex items-center gap-2 mb-2">
                  <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ background: config.bg }}>
                    <Icon size={16} style={{ color: config.color }} />
                  </div>
                  <span className="text-sm font-semibold" style={{ color: config.color }}>{config.label}s</span>
                </div>
                <p className="text-3xl font-bold" style={{ color: theme.text }}>{summary[key + 's'] || 0}</p>
                <p className="text-[10px] text-gray-500 mt-1">{config.desc}</p>
              </CardContent>
            </Card>
          );
        })}
      </div>

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="matrix" data-testid="tab-matrix">Performance Matrix</TabsTrigger>
          <TabsTrigger value="categories" data-testid="tab-categories">By Category</TabsTrigger>
        </TabsList>

        <TabsContent value="matrix" className="mt-4">
          <Card className="border-0 shadow-sm">
            <CardContent className="p-0">
              <div className="overflow-x-auto">
                <table className="w-full text-sm" data-testid="menu-items-table">
                  <thead>
                    <tr className="border-b bg-gray-50/80">
                      <th className="text-left px-4 py-3 font-medium text-gray-500">Item</th>
                      <th className="text-left px-4 py-3 font-medium text-gray-500">Category</th>
                      <th className="text-right px-4 py-3 font-medium text-gray-500">Price</th>
                      <th className="text-right px-4 py-3 font-medium text-gray-500">Cost</th>
                      <th className="text-right px-4 py-3 font-medium text-gray-500">Margin</th>
                      <th className="text-right px-4 py-3 font-medium text-gray-500">Qty Sold</th>
                      <th className="text-right px-4 py-3 font-medium text-gray-500">Revenue</th>
                      <th className="text-right px-4 py-3 font-medium text-gray-500">Profit</th>
                      <th className="text-center px-4 py-3 font-medium text-gray-500">Class</th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((item, i) => {
                      const cls = CLASS_CONFIG[item.classification] || CLASS_CONFIG.dog;
                      const Icon = cls.icon;
                      const revPct = totalRevenue > 0 ? (item.revenue / totalRevenue * 100) : 0;
                      return (
                        <tr key={i} className="border-b hover:bg-gray-50/50 transition-colors">
                          <td className="px-4 py-3">
                            <div className="flex items-center gap-2">
                              <span className="font-medium" style={{ color: theme.text }}>{item.name}</span>
                              {revPct > 15 && <ArrowUpRight size={12} className="text-green-500" />}
                              {revPct < 3 && item.quantity > 0 && <ArrowDownRight size={12} className="text-red-400" />}
                            </div>
                          </td>
                          <td className="px-4 py-3 text-xs text-gray-500">{item.category}</td>
                          <td className="px-4 py-3 text-right font-mono">${item.price.toFixed(2)}</td>
                          <td className="px-4 py-3 text-right font-mono text-gray-500">${item.cost.toFixed(2)}</td>
                          <td className="px-4 py-3 text-right">
                            <span className={`font-bold ${item.margin >= 50 ? 'text-green-600' : item.margin >= 30 ? 'text-amber-600' : 'text-red-600'}`}>
                              {item.margin.toFixed(0)}%
                            </span>
                          </td>
                          <td className="px-4 py-3 text-right font-mono">{item.quantity}</td>
                          <td className="px-4 py-3 text-right font-mono font-medium">${item.revenue.toFixed(0)}</td>
                          <td className="px-4 py-3 text-right font-mono" style={{ color: item.profit >= 0 ? '#10B981' : '#EF4444' }}>
                            ${item.profit.toFixed(0)}
                          </td>
                          <td className="px-4 py-3 text-center">
                            <Badge style={{ background: cls.bg, color: cls.color, border: `1px solid ${cls.color}30` }} className="text-[10px]">
                              <Icon size={10} className="mr-1 inline" />{cls.label}
                            </Badge>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="categories" className="mt-4">
          <div className="grid grid-cols-2 gap-4">
            {categories.map((cat, i) => (
              <Card key={i} className="border-0 shadow-sm">
                <CardContent className="p-5">
                  <div className="flex items-center justify-between mb-3">
                    <h3 className="font-semibold" style={{ color: theme.text }}>{cat.name}</h3>
                    <Badge variant="outline" className="text-xs">{cat.items} items</Badge>
                  </div>
                  <div className="grid grid-cols-3 gap-3">
                    <div>
                      <p className="text-[10px] text-gray-500">Revenue</p>
                      <p className="text-lg font-bold" style={{ color: theme.primary }}>${cat.revenue.toFixed(0)}</p>
                    </div>
                    <div>
                      <p className="text-[10px] text-gray-500">Profit</p>
                      <p className="text-lg font-bold" style={{ color: cat.profit >= 0 ? '#10B981' : '#EF4444' }}>${cat.profit.toFixed(0)}</p>
                    </div>
                    <div>
                      <p className="text-[10px] text-gray-500">Margin</p>
                      <p className="text-lg font-bold" style={{ color: cat.margin >= 50 ? '#10B981' : cat.margin >= 30 ? '#F59E0B' : '#EF4444' }}>{cat.margin.toFixed(0)}%</p>
                    </div>
                  </div>
                  <div className="mt-3">
                    <div className="w-full h-2 bg-gray-200 rounded-full">
                      <div className="h-full rounded-full" style={{
                        width: `${Math.min(100, cat.margin)}%`,
                        background: cat.margin >= 50 ? '#10B981' : cat.margin >= 30 ? '#F59E0B' : '#EF4444'
                      }} />
                    </div>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </TabsContent>
      </Tabs>

      {/* AI Import — two-step review flow */}
      <AIMenuImportReview open={showImport} onOpenChange={setShowImport} onCommitted={onCommitted} />

      {/* Price Adjustment Dialog */}
      <Dialog open={showPriceAdjust} onOpenChange={setShowPriceAdjust}>
        <DialogContent className="max-w-sm" data-testid="price-adjust-dialog">
          <DialogHeader><DialogTitle>Bulk Price Adjustment</DialogTitle></DialogHeader>
          <div className="space-y-3 py-2">
            <p className="text-sm text-gray-500">Adjust prices across categories — ideal for inflation updates.</p>
            <select className="w-full p-2 border rounded-md text-sm" value={priceForm.category} onChange={e => setPriceForm({ ...priceForm, category: e.target.value })} data-testid="adjust-category">
              <option value="">All Categories</option>
              <option value="Beverages">Beverages</option><option value="Food">Food</option><option value="Bakery">Bakery</option><option value="Alcohol">Alcohol</option><option value="Desserts">Desserts</option><option value="Mains">Mains</option>
            </select>
            <div className="grid grid-cols-2 gap-2">
              <select className="p-2 border rounded-md text-sm" value={priceForm.type} onChange={e => setPriceForm({ ...priceForm, type: e.target.value })} data-testid="adjust-type">
                <option value="percentage">Percentage (%)</option><option value="fixed">Fixed ($)</option>
              </select>
              <select className="p-2 border rounded-md text-sm" value={priceForm.direction} onChange={e => setPriceForm({ ...priceForm, direction: e.target.value })} data-testid="adjust-direction">
                <option value="increase">Increase</option><option value="decrease">Decrease</option>
              </select>
            </div>
            <Input type="number" step="0.1" placeholder={priceForm.type === 'percentage' ? 'e.g. 5 for 5%' : 'e.g. 1.50'} value={priceForm.amount} onChange={e => setPriceForm({ ...priceForm, amount: e.target.value })} data-testid="adjust-amount" />
            <Button className="w-full" style={{ backgroundColor: theme.primary }} onClick={handlePriceAdjust} data-testid="apply-adjust-btn">Apply Adjustment</Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
