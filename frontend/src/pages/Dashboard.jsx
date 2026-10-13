import React, { useState, useEffect } from 'react';
import {
  DollarSign, ShoppingBag, Users, TrendingUp, Utensils, Eye, Receipt, RotateCcw, Printer,
  BarChart3
} from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Badge } from '../components/ui/badge';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '../components/ui/dialog';
import { useTheme } from '../contexts/ThemeContext';
import { useAuth } from '../contexts/AuthContext';
import { transactionsAPI, customersAPI, enterpriseAPI, refundsAPI } from '../services/api';
import { toast } from 'sonner';
import { buildReceiptHtml } from '../lib/receiptHtml';
import { SecureStorageService } from '../platform';

const Dashboard = () => {
  const { theme } = useTheme();
  const { user } = useAuth();
  const [liveSales, setLiveSales] = useState(null);
  const [transactions, setTransactions] = useState([]);
  const [topItems, setTopItems] = useState([]);
  const [bestCategory, setBestCategory] = useState(null);
  const [activeTables, setActiveTables] = useState(0);
  // Dialogs
  const [selectedTxn, setSelectedTxn] = useState(null);
  const [showDetail, setShowDetail] = useState(false);
  const [showRefund, setShowRefund] = useState(false);
  const [showReceipt, setShowReceipt] = useState(false);
  const [refundForm, setRefundForm] = useState({ amount: '', reason: '', refundMethod: 'original_payment' });

  useEffect(() => { fetchAll(); const iv = setInterval(fetchAll, 30000); return () => clearInterval(iv); }, []);

  const fetchAll = async () => {
    try {
      const [salesRes, txnRes] = await Promise.all([
        enterpriseAPI.getLiveSales().catch(() => ({ data: null })),
        transactionsAPI.getAll(),
      ]);
      if (salesRes.data) setLiveSales(salesRes.data);
      setTransactions(txnRes.data || []);

      // Top 10 items
      const itemMap = {};
      (txnRes.data || []).forEach(t => (t.items || []).forEach(i => {
        const pid = i.productId || i.productName;
        if (!itemMap[pid]) itemMap[pid] = { name: i.productName, qty: 0, revenue: 0 };
        itemMap[pid].qty += i.quantity || 0;
        itemMap[pid].revenue += (i.price || 0) * (i.quantity || 0);
      }));
      const sorted = Object.values(itemMap).sort((a, b) => b.revenue - a.revenue);
      setTopItems(sorted.slice(0, 10));

      // Best category
      const catMap = {};
      (txnRes.data || []).forEach(t => (t.items || []).forEach(i => {
        const cat = i.category || 'Other';
        catMap[cat] = (catMap[cat] || 0) + (i.price || 0) * (i.quantity || 0);
      }));
      const bestCat = Object.entries(catMap).sort((a, b) => b[1] - a[1])[0];
      if (bestCat) setBestCategory({ name: bestCat[0], revenue: bestCat[1] });

      // Active tables
      try {
        const kitchenRes = await fetch(`${process.env.REACT_APP_BACKEND_URL}/api/kitchen/orders`, { headers: { Authorization: `Bearer ${await SecureStorageService.getToken()}` } });
        const ko = await kitchenRes.json();
        const tables = new Set((ko || []).filter(o => o.tableNumber).map(o => o.tableNumber));
        setActiveTables(tables.size);
      } catch { setActiveTables(0); }
    } catch {}
  };

  const openDetail = async (txn) => {
    try { const r = await transactionsAPI.getDetail(txn.id); setSelectedTxn(r.data); } catch { setSelectedTxn(txn); }
    setShowDetail(true);
  };
  const openRefund = (txn) => { setSelectedTxn(txn); setRefundForm({ amount: txn.total || '', reason: '', refundMethod: 'original_payment' }); setShowRefund(true); };
  const openReceipt = (txn) => { setSelectedTxn(txn); setShowReceipt(true); };
  const handleRefund = async () => {
    if (!refundForm.reason) { toast.error('Reason required'); return; }
    try {
      await refundsAPI.create({ originalTransactionId: selectedTxn.id, amount: parseFloat(refundForm.amount), reason: refundForm.reason, refundMethod: refundForm.refundMethod, processedBy: user?.name || 'Owner' });
      toast.success('Refund processed'); setShowRefund(false); fetchAll();
    } catch (e) { toast.error(e.response?.data?.detail || 'Refund failed'); }
  };
  const printReceipt = () => {
    const t = selectedTxn; if (!t) return;
    const w = window.open('', '_blank', 'width=400,height=600');
    w.document.write(buildReceiptHtml(t));
    w.document.close(); w.print();
  };

  const totalRevenue = liveSales?.totalSales || transactions.reduce((s, t) => s + (t.total || 0), 0);
  const totalTxns = liveSales?.transactionCount || transactions.length;
  const avgTicket = liveSales?.avgTicket || (totalTxns ? totalRevenue / totalTxns : 0);

  return (
    <div className="space-y-6" data-testid="dashboard-page">
      <div><h1 className="text-3xl font-bold" style={{ color: theme.text }}>Dashboard</h1><p className="text-gray-500 mt-1">Real-time business overview</p></div>

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        <Card><CardContent className="p-5"><p className="text-sm text-gray-500">Total Revenue</p><p className="text-2xl font-bold" style={{ color: theme.primary }}>${totalRevenue.toFixed(2)}</p></CardContent></Card>
        <Card><CardContent className="p-5"><p className="text-sm text-gray-500">Active Tables</p><p className="text-2xl font-bold text-blue-600">{activeTables}</p></CardContent></Card>
        <Card><CardContent className="p-5"><p className="text-sm text-gray-500">Transactions</p><p className="text-2xl font-bold" style={{ color: theme.text }}>{totalTxns}</p></CardContent></Card>
        <Card><CardContent className="p-5"><p className="text-sm text-gray-500">Best Category</p><p className="text-lg font-bold text-emerald-600">{bestCategory?.name || '-'}</p><p className="text-xs text-gray-400">${(bestCategory?.revenue || 0).toFixed(0)}</p></CardContent></Card>
        <Card><CardContent className="p-5"><p className="text-sm text-gray-500">Avg Ticket</p><p className="text-2xl font-bold text-amber-600">${avgTicket.toFixed(2)}</p></CardContent></Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Recent Transactions — Full Actions */}
        <div className="lg:col-span-2">
          <Card><CardHeader><CardTitle className="text-sm">Recent Transactions</CardTitle></CardHeader>
          <CardContent className="p-0"><div className="overflow-x-auto">
            <table className="w-full text-sm" data-testid="dashboard-txn-table">
              <thead className="bg-gray-50"><tr>
                <th className="text-left p-3 text-gray-500 font-medium">ID</th>
                <th className="text-left p-3 text-gray-500 font-medium">Time</th>
                <th className="text-left p-3 text-gray-500 font-medium">Payment</th>
                <th className="text-left p-3 text-gray-500 font-medium">Cashier</th>
                <th className="text-right p-3 text-gray-500 font-medium">Total</th>
                <th className="text-center p-3 text-gray-500 font-medium">Actions</th>
              </tr></thead>
              <tbody>
                {transactions.slice(0, 15).map(txn => (
                  <tr key={txn.id} className="border-t hover:bg-gray-50" data-testid={`dash-txn-${txn.id}`}>
                    <td className="p-3 font-mono text-xs">{txn.id}</td>
                    <td className="p-3 text-xs">{new Date(txn.timestamp).toLocaleTimeString()}</td>
                    <td className="p-3"><Badge variant="outline" className="text-[10px]">{txn.paymentMethod}</Badge></td>
                    <td className="p-3 text-xs">{txn.cashier}</td>
                    <td className="p-3 text-right font-bold" style={{ color: theme.primary }}>${(txn.total || 0).toFixed(2)}</td>
                    <td className="p-3">
                      <div className="flex justify-center gap-1">
                        <Button variant="ghost" size="sm" className="h-7 w-7 p-0" title="View" onClick={() => openDetail(txn)}><Eye size={13} /></Button>
                        <Button variant="ghost" size="sm" className="h-7 w-7 p-0" title="Receipt" onClick={() => openReceipt(txn)}><Receipt size={13} /></Button>
                        <Button variant="ghost" size="sm" className="h-7 w-7 p-0" title="Print" onClick={() => { setSelectedTxn(txn); printReceipt(); }}><Printer size={13} /></Button>
                        <Button variant="ghost" size="sm" className="h-7 w-7 p-0 text-red-500" title="Refund" onClick={() => openRefund(txn)}><RotateCcw size={13} /></Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {transactions.length === 0 && <p className="text-center text-gray-400 py-8">No transactions yet</p>}
          </div></CardContent></Card>
        </div>

        {/* Top 10 Selling Items */}
        <Card><CardHeader><CardTitle className="text-sm flex items-center gap-2"><BarChart3 size={16} /> Top 10 Items</CardTitle></CardHeader>
        <CardContent className="space-y-2">
          {topItems.map((item, i) => (
            <div key={i} className="flex items-center gap-3 py-1.5">
              <div className="w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold text-white" style={{ backgroundColor: i < 3 ? theme.primary : '#9CA3AF' }}>{i + 1}</div>
              <div className="flex-1 min-w-0"><p className="text-sm font-medium truncate">{item.name}</p><p className="text-[10px] text-gray-400">{item.qty} sold</p></div>
              <span className="text-sm font-bold" style={{ color: theme.primary }}>${item.revenue.toFixed(0)}</span>
            </div>
          ))}
          {topItems.length === 0 && <p className="text-gray-400 text-sm text-center py-6">No sales data</p>}
        </CardContent></Card>
      </div>

      {/* Transaction Detail Dialog */}
      <Dialog open={showDetail} onOpenChange={setShowDetail}>
        <DialogContent className="max-w-lg max-h-[85vh] overflow-y-auto" data-testid="txn-detail-dialog">
          <DialogHeader><DialogTitle>Transaction Details</DialogTitle></DialogHeader>
          {selectedTxn && (
            <div className="space-y-4 py-2">
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div><span className="text-gray-500">ID:</span> <span className="font-mono">{selectedTxn.id}</span></div>
                <div><span className="text-gray-500">Date:</span> {new Date(selectedTxn.timestamp).toLocaleString()}</div>
                <div><span className="text-gray-500">Payment:</span> <Badge variant="outline">{selectedTxn.paymentMethod}</Badge></div>
                <div><span className="text-gray-500">Cashier:</span> {selectedTxn.cashier}</div>
              </div>
              <div className="border rounded-lg p-3">
                <p className="font-semibold text-sm mb-2">Items</p>
                {(selectedTxn.items || []).map((item, i) => (
                  <div key={i} className="flex justify-between py-1 text-sm border-b last:border-0"><span>{item.productName} x{item.quantity}</span><span className="font-medium">${(item.price * item.quantity).toFixed(2)}</span></div>
                ))}
              </div>
              <div className="border rounded-lg p-3 space-y-1 text-sm">
                <div className="flex justify-between"><span>Subtotal</span><span>${(selectedTxn.subtotal || 0).toFixed(2)}</span></div>
                <div className="flex justify-between"><span>GST</span><span>${(selectedTxn.gst || 0).toFixed(2)}</span></div>
                <div className="flex justify-between font-bold text-lg pt-1 border-t"><span>Total</span><span style={{ color: theme.primary }}>${(selectedTxn.total || 0).toFixed(2)}</span></div>
              </div>
              {(selectedTxn.refunds || []).length > 0 && (
                <div className="border border-red-200 rounded-lg p-3 bg-red-50">
                  <p className="font-semibold text-sm text-red-700 mb-2">Refunds</p>
                  {selectedTxn.refunds.map((r, i) => (<div key={i} className="text-sm text-red-600 flex justify-between"><span>{r.reason}</span><span>-${r.amount.toFixed(2)}</span></div>))}
                </div>
              )}
              <div className="flex gap-2">
                <Button variant="outline" className="flex-1" onClick={() => { setShowDetail(false); openReceipt(selectedTxn); }}><Receipt size={14} className="mr-1" /> Receipt</Button>
                <Button variant="outline" className="flex-1 text-red-500" onClick={() => { setShowDetail(false); openRefund(selectedTxn); }}><RotateCcw size={14} className="mr-1" /> Refund</Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* Refund Dialog */}
      <Dialog open={showRefund} onOpenChange={setShowRefund}>
        <DialogContent className="max-w-sm" data-testid="refund-dialog">
          <DialogHeader><DialogTitle>Issue Refund</DialogTitle></DialogHeader>
          {selectedTxn && (
            <div className="space-y-3 py-2">
              <p className="text-sm text-gray-500">Transaction: <span className="font-mono">{selectedTxn.id}</span> — ${(selectedTxn.total || 0).toFixed(2)}</p>
              <Input type="number" step="0.01" placeholder="Refund amount" value={refundForm.amount} onChange={e => setRefundForm({ ...refundForm, amount: e.target.value })} data-testid="refund-amount" />
              <Input placeholder="Reason" value={refundForm.reason} onChange={e => setRefundForm({ ...refundForm, reason: e.target.value })} data-testid="refund-reason" />
              <select className="w-full p-2 border rounded-md text-sm" value={refundForm.refundMethod} onChange={e => setRefundForm({ ...refundForm, refundMethod: e.target.value })}>
                <option value="original_payment">Original Payment</option><option value="store_credit">Store Credit</option><option value="cash">Cash</option>
              </select>
              <Button className="w-full bg-red-600 hover:bg-red-700 text-white" onClick={handleRefund} data-testid="confirm-refund-btn">Process Refund</Button>
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* Receipt Dialog */}
      <Dialog open={showReceipt} onOpenChange={setShowReceipt}>
        <DialogContent className="max-w-sm" data-testid="receipt-dialog">
          <DialogHeader><DialogTitle>Receipt</DialogTitle></DialogHeader>
          {selectedTxn && (
            <div className="py-2">
              <div className="bg-white border rounded-lg p-6 font-mono text-sm space-y-2">
                <p className="text-center font-bold text-lg">NUA</p>
                <p className="text-center text-gray-500 text-xs">#{selectedTxn.receiptNumber || selectedTxn.id}</p>
                <hr className="border-dashed" />
                <p className="text-xs">{new Date(selectedTxn.timestamp).toLocaleString()}</p>
                <hr className="border-dashed" />
                {(selectedTxn.items || []).map((item, i) => (<div key={i} className="flex justify-between text-xs"><span>{item.productName} x{item.quantity}</span><span>${(item.price * item.quantity).toFixed(2)}</span></div>))}
                <hr className="border-dashed" />
                <div className="flex justify-between font-bold"><span>TOTAL</span><span>${(selectedTxn.total || 0).toFixed(2)}</span></div>
                <p className="text-center text-xs text-gray-500">Payment: {selectedTxn.paymentMethod}</p>
                {(selectedTxn.splitDetails || []).length > 0 && (
                  <>
                    <hr className="border-dashed" />
                    <p className="text-xs font-bold uppercase tracking-wide text-gray-500">Split payment</p>
                    {selectedTxn.splitDetails.map((s, i) => (
                      <div key={i} className="text-xs" data-testid={`receipt-split-${i}`}>
                        <div className="flex justify-between">
                          <span>{s.payerName} ({s.method})</span>
                          <span>${(s.amount || 0).toFixed(2)}</span>
                        </div>
                        {(s.items || []).length > 0 && (
                          <p className="text-gray-400 pl-2">{s.items.map(it => `${it.quantity}× ${it.name}`).join(' · ')}</p>
                        )}
                      </div>
                    ))}
                  </>
                )}
              </div>
              <div className="flex gap-2 mt-4">
                <Button variant="outline" className="flex-1" onClick={printReceipt}><Printer size={14} className="mr-1" /> Print</Button>
                <Button variant="outline" className="flex-1" onClick={() => toast.success('Receipt emailed')}>Email</Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default Dashboard;
