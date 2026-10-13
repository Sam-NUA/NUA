import React, { useState, useEffect, useCallback } from 'react';
import { financeAPI } from '../../services/api';
import { toast } from 'sonner';
import { Card, CardContent, CardHeader, CardTitle } from '../../components/ui/card';
import { Button } from '../../components/ui/button';
import { Input } from '../../components/ui/input';
import { Badge } from '../../components/ui/badge';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '../../components/ui/dialog';
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from '../../components/ui/select';
import { PlusCircle, Trash2 } from 'lucide-react';
import { DialogService } from '../../platform';

const ChartOfAccounts = () => {
  const [accounts, setAccounts] = useState([]);
  const [showAdd, setShowAdd] = useState(false);
  const [form, setForm] = useState({ code: '', name: '', type: 'expense', subType: '' });

  const load = useCallback(async () => {
    try { setAccounts((await financeAPI.listAccounts()).data); }
    catch { toast.error('Could not load accounts'); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const save = async () => {
    if (!form.code || !form.name) return toast.error('Code + name required');
    try {
      await financeAPI.createAccount(form);
      toast.success(`Account ${form.code} created`);
      setShowAdd(false);
      setForm({ code: '', name: '', type: 'expense', subType: '' });
      load();
    } catch (e) { toast.error(e.response?.data?.detail || 'Failed'); }
  };

  const remove = async (code) => {
    if (!await DialogService.confirm(`Delete account ${code}?`)) return;
    try { await financeAPI.deleteAccount(code); toast.success('Deleted'); load(); }
    catch (e) { toast.error(e.response?.data?.detail || 'Failed'); }
  };

  const grouped = accounts.reduce((acc, a) => { (acc[a.type] = acc[a.type] || []).push(a); return acc; }, {});
  const order = ['asset', 'liability', 'equity', 'revenue', 'expense'];

  return (
    <div className="space-y-4" data-testid="coa-page">
      <div className="flex justify-between items-center">
        <h3 className="text-lg font-semibold">Chart of Accounts</h3>
        <Button size="sm" onClick={() => setShowAdd(true)} data-testid="coa-add-btn">
          <PlusCircle size={14} className="mr-1" /> New Account
        </Button>
      </div>
      {order.filter(t => grouped[t]).map(t => (
        <Card key={t}>
          <CardHeader className="pb-2"><CardTitle className="capitalize text-base">{t}s</CardTitle></CardHeader>
          <CardContent className="p-0">
            <table className="w-full text-sm" data-testid={`coa-table-${t}`}>
              <thead className="bg-slate-50"><tr>
                <th className="text-left p-2 pl-4 text-xs text-slate-500">Code</th>
                <th className="text-left p-2 text-xs text-slate-500">Name</th>
                <th className="text-left p-2 text-xs text-slate-500">Sub-type</th>
                <th className="text-left p-2 text-xs text-slate-500">Flags</th>
                <th className="p-2 pr-4"></th>
              </tr></thead>
              <tbody>
                {grouped[t].sort((a, b) => a.code.localeCompare(b.code)).map(a => (
                  <tr key={a.code} className="border-t">
                    <td className="p-2 pl-4 font-mono">{a.code}</td>
                    <td className="p-2">{a.name}</td>
                    <td className="p-2 text-slate-500">{a.subType || '—'}</td>
                    <td className="p-2 space-x-1">
                      {a.isBank && <Badge variant="outline" className="text-xs">Bank</Badge>}
                      {a.isLocked && <Badge variant="secondary" className="text-xs">System</Badge>}
                    </td>
                    <td className="p-2 pr-4 text-right">
                      {!a.isLocked && (
                        <Button size="sm" variant="ghost" className="text-rose-500" onClick={() => remove(a.code)}
                                data-testid={`coa-delete-${a.code}`}>
                          <Trash2 size={14} />
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
      ))}

      <Dialog open={showAdd} onOpenChange={setShowAdd}>
        <DialogContent data-testid="coa-add-dialog">
          <DialogHeader><DialogTitle>New Account</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <Input placeholder="Code (e.g. 6900)" value={form.code} onChange={e => setForm({ ...form, code: e.target.value })} data-testid="coa-input-code" />
            <Input placeholder="Name" value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} data-testid="coa-input-name" />
            <Select value={form.type} onValueChange={v => setForm({ ...form, type: v })}>
              <SelectTrigger data-testid="coa-select-type"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="asset">Asset</SelectItem>
                <SelectItem value="liability">Liability</SelectItem>
                <SelectItem value="equity">Equity</SelectItem>
                <SelectItem value="revenue">Revenue</SelectItem>
                <SelectItem value="expense">Expense</SelectItem>
              </SelectContent>
            </Select>
            <Input placeholder="Sub-type (optional)" value={form.subType} onChange={e => setForm({ ...form, subType: e.target.value })} />
            <Button className="w-full" onClick={save} data-testid="coa-save-btn">Create</Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default ChartOfAccounts;
