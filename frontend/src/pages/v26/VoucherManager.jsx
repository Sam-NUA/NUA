import React, { useEffect, useState } from 'react';
import { Card, CardContent } from '../../components/ui/card';
import { Button } from '../../components/ui/button';
import { Input } from '../../components/ui/input';
import { Textarea } from '../../components/ui/textarea';
import { Badge } from '../../components/ui/badge';
import { useToast } from '../../hooks/use-toast';
import { useTheme } from '../../contexts/ThemeContext';
import { v26API } from '../../services/api';
import Barcode128 from '../../components/Barcode128';
import { Ticket, Plus, Edit2, Trash2, Barcode, Save } from 'lucide-react';
import { DialogService } from '../../platform';

export default function VoucherManager() {
  const { theme } = useTheme(); const { toast } = useToast();
  const [rows, setRows] = useState([]);
  const [editing, setEditing] = useState(null);
  const [showCode, setShowCode] = useState(null);

  const load = () => v26API.listVouchers().then(r => setRows(r.data || []));
  useEffect(() => { load(); }, []);

  const blank = () => ({
    name: '', kind: 'discount', discountType: 'percent', value: 10,
    appliesTo: 'cart', minSpend: 0, maxUses: 0,
    validFrom: null, validTo: null, termsAndConditions: '', active: true,
  });

  const save = async () => {
    try {
      let res;
      if (editing.id) {
        res = await v26API.updateVoucher(editing.id, editing);
        toast({ title: 'Saved' });
      } else {
        res = await v26API.createVoucher(editing);
        const gc = res?.data?.giftCard;
        if (gc) {
          toast({
            title: 'Gift voucher created',
            description: `Card ${gc.code} pending activation ($${gc.initialBalance.toFixed(2)}). Activates on POS sale.`,
          });
        } else {
          toast({ title: 'Saved' });
        }
      }
      setEditing(null); load();
    } catch (e) { toast({ title: 'Failed', description: e?.response?.data?.detail, variant: 'destructive' }); }
  };

  const remove = async (id) => {
    if (!await DialogService.confirm('Delete this voucher?')) return;
    try { await v26API.deleteVoucher(id); toast({ title: 'Deleted' }); load(); }
    catch (e) { toast({ title: 'Failed', variant: 'destructive' }); }
  };

  return (
    <div className="space-y-6" data-testid="voucher-manager-page">
      <div className="flex justify-between items-center">
        <h1 className="text-3xl font-bold flex items-center gap-2" style={{ color: theme.text }}>
          <Ticket className="text-rose-600" /> Vouchers, Coupons & Marketing Codes
        </h1>
        <Button onClick={() => setEditing(blank())} style={{ background: theme.primary }} data-testid="new-voucher-btn">
          <Plus size={14} className="mr-1.5" /> New Code
        </Button>
      </div>

      <Card><CardContent className="p-0">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-xs uppercase tracking-wider text-gray-500">
            <tr>
              <th className="text-left px-5 py-3">Name</th>
              <th className="text-left px-5 py-3">Code</th>
              <th className="text-left px-5 py-3">Type</th>
              <th className="text-right px-5 py-3">Value</th>
              <th className="text-right px-5 py-3">Used</th>
              <th className="text-left px-5 py-3">Status</th>
              <th className="text-right px-5 py-3">Actions</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? <tr><td colSpan={7} className="text-center py-8 text-gray-400">No vouchers — create one</td></tr> :
              rows.map(v => (
                <tr key={v.id} className="border-t hover:bg-gray-50" data-testid={`voucher-row-${v.id}`}>
                  <td className="px-5 py-3 font-medium">{v.name}</td>
                  <td className="px-5 py-3 font-mono text-xs">{v.manualCode}</td>
                  <td className="px-5 py-3"><Badge variant="outline" className="text-[10px]">{v.kind} · {v.discountType}</Badge></td>
                  <td className="px-5 py-3 text-right">{v.discountType === 'percent' ? `${v.value}%` : `$${v.value}`}</td>
                  <td className="px-5 py-3 text-right">{v.usedCount}{v.maxUses > 0 ? `/${v.maxUses}` : ''}</td>
                  <td className="px-5 py-3"><Badge className={v.active ? 'bg-emerald-100 text-emerald-700' : 'bg-gray-200 text-gray-700'}>{v.active ? 'active' : 'disabled'}</Badge></td>
                  <td className="px-5 py-3 text-right flex justify-end gap-1">
                    <Button size="sm" variant="ghost" onClick={() => setShowCode(v)} data-testid={`view-code-${v.id}`}><Barcode size={14} /></Button>
                    <Button size="sm" variant="ghost" onClick={() => setEditing(v)} data-testid={`edit-${v.id}`}><Edit2 size={14} /></Button>
                    <Button size="sm" variant="ghost" onClick={() => remove(v.id)} data-testid={`del-${v.id}`}><Trash2 size={14} /></Button>
                  </td>
                </tr>
              ))}
          </tbody>
        </table>
      </CardContent></Card>

      {editing && (
        <Card className="border-amber-300"><CardContent className="p-5 space-y-3" data-testid="voucher-editor">
          <h2 className="font-bold text-lg">{editing.id ? 'Edit' : 'New'} Code</h2>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
            <div><label className="text-xs uppercase text-gray-500">Name</label>
              <Input value={editing.name} onChange={e => setEditing({ ...editing, name: e.target.value })} /></div>
            <div><label className="text-xs uppercase text-gray-500">Kind</label>
              <select className="w-full p-2 border rounded text-sm" value={editing.kind} onChange={e => setEditing({ ...editing, kind: e.target.value })}>
                <option>discount</option><option>freebie</option><option>bundle</option><option>gift</option><option>marketing</option>
              </select></div>
            <div><label className="text-xs uppercase text-gray-500">Discount Type</label>
              <select className="w-full p-2 border rounded text-sm" value={editing.discountType} onChange={e => setEditing({ ...editing, discountType: e.target.value })}>
                <option value="percent">% off</option><option value="fixed">$ off</option><option value="free_item">free cheapest item</option>
              </select></div>
            <div><label className="text-xs uppercase text-gray-500">Value</label>
              <Input type="number" value={editing.value} onChange={e => setEditing({ ...editing, value: parseFloat(e.target.value) || 0 })} /></div>
            <div><label className="text-xs uppercase text-gray-500">Min Spend $</label>
              <Input type="number" value={editing.minSpend} onChange={e => setEditing({ ...editing, minSpend: parseFloat(e.target.value) || 0 })} /></div>
            <div><label className="text-xs uppercase text-gray-500">Max Uses (0=∞)</label>
              <Input type="number" value={editing.maxUses} onChange={e => setEditing({ ...editing, maxUses: parseInt(e.target.value) || 0 })} /></div>
            <div><label className="text-xs uppercase text-gray-500">Valid From</label>
              <Input type="datetime-local" value={(editing.validFrom || '').slice(0, 16)} onChange={e => setEditing({ ...editing, validFrom: e.target.value })} /></div>
            <div><label className="text-xs uppercase text-gray-500">Valid To</label>
              <Input type="datetime-local" value={(editing.validTo || '').slice(0, 16)} onChange={e => setEditing({ ...editing, validTo: e.target.value })} /></div>
            <div><label className="text-xs uppercase text-gray-500">Active</label>
              <div className="flex items-center h-10"><input type="checkbox" checked={editing.active} onChange={e => setEditing({ ...editing, active: e.target.checked })} /></div></div>
          </div>
          <div><label className="text-xs uppercase text-gray-500">Terms & Conditions</label>
            <Textarea rows={3} value={editing.termsAndConditions} onChange={e => setEditing({ ...editing, termsAndConditions: e.target.value })} /></div>
          <div className="flex gap-2">
            <Button onClick={save} style={{ background: theme.primary }} data-testid="save-voucher"><Save size={14} className="mr-1.5" /> Save</Button>
            <Button variant="outline" onClick={() => setEditing(null)}>Cancel</Button>
          </div>
        </CardContent></Card>
      )}

      {showCode && (
        <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-6" onClick={() => setShowCode(null)} data-testid="barcode-modal">
          <Card onClick={e => e.stopPropagation()} className="max-w-md w-full"><CardContent className="p-6 text-center space-y-4">
            <h3 className="font-bold">{showCode.name}</h3>
            <Barcode128 value={showCode.manualCode} />
            <p className="text-xs text-gray-500">Scan at POS or type code manually</p>
            <Button onClick={() => setShowCode(null)}>Close</Button>
          </CardContent></Card>
        </div>
      )}
    </div>
  );
}
