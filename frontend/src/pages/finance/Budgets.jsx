import React, { useState, useEffect, useCallback } from 'react';
import { financeAPI } from '../../services/api';
import { toast } from 'sonner';
import { Card, CardContent } from '../../components/ui/card';
import { Button } from '../../components/ui/button';
import { Input } from '../../components/ui/input';
import { Badge } from '../../components/ui/badge';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '../../components/ui/dialog';
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from '../../components/ui/select';
import { PlusCircle, X, Pencil, Trash2 } from 'lucide-react';
import { DialogService } from '../../platform';
import { FMT, fyStart } from './helpers';

const fyEnd = (start) => `${parseInt(start.slice(0, 4), 10) + 1}-06-30`;

const Budgets = () => {
  const [budgets, setBudgets] = useState([]);
  const [accounts, setAccounts] = useState([]);
  const [selectedBudget, setSelectedBudget] = useState('');
  const [report, setReport] = useState(null);
  const [show, setShow] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [form, setForm] = useState({ name: 'FY Budget', fyStart: fyStart(), fyEnd: fyEnd(fyStart()), lines: [] });

  const load = useCallback(async () => {
    try {
      const [b, a] = await Promise.all([financeAPI.listBudgets(), financeAPI.listAccounts()]);
      setBudgets(b.data);
      setAccounts(a.data);
      if (b.data.length && !selectedBudget) setSelectedBudget(b.data[0].id);
    } catch { toast.error('Could not load budgets'); }
    // eslint-disable-next-line
  }, []);
  useEffect(() => { load(); }, [load]);

  const loadReport = useCallback(async () => {
    if (!selectedBudget) { setReport(null); return; }
    try { setReport((await financeAPI.budgetVsActual({ budget_id: selectedBudget })).data); }
    catch { toast.error('Could not load budget-vs-actual report'); }
  }, [selectedBudget]);
  useEffect(() => { loadReport(); }, [loadReport]);

  const addLine = () => setForm(f => ({ ...f, lines: [...f.lines, { accountCode: '', monthlyAmount: 0 }] }));
  const updateLine = (i, field, value) => setForm(f => ({
    ...f, lines: f.lines.map((l, idx) => idx === i ? { ...l, [field]: value } : l),
  }));
  const removeLine = (i) => setForm(f => ({ ...f, lines: f.lines.filter((_, idx) => idx !== i) }));

  const closeDialog = () => {
    setShow(false); setEditingId(null);
    setForm({ name: 'FY Budget', fyStart: fyStart(), fyEnd: fyEnd(fyStart()), lines: [] });
  };

  const openEdit = () => {
    const b = budgets.find(x => x.id === selectedBudget);
    if (!b) return;
    setEditingId(b.id);
    setForm({ name: b.name, fyStart: b.fyStart, fyEnd: b.fyEnd, lines: b.lines.map(l => ({ ...l })) });
    setShow(true);
  };

  const save = async () => {
    if (!form.name || form.lines.length === 0) return toast.error('Name + at least one line required');
    const payload = {
      ...form,
      lines: form.lines.filter(l => l.accountCode).map(l => ({ ...l, monthlyAmount: parseFloat(l.monthlyAmount) || 0 })),
    };
    try {
      const r = editingId
        ? await financeAPI.updateBudget(editingId, payload)
        : await financeAPI.createBudget(payload);
      toast.success(editingId ? 'Budget updated' : 'Budget created');
      closeDialog();
      setSelectedBudget(r.data.id);
      load();
    } catch (e) { toast.error(e.response?.data?.detail || 'Failed'); }
  };

  const remove = async () => {
    const b = budgets.find(x => x.id === selectedBudget);
    if (!b) return;
    if (!await DialogService.confirm(`Delete budget "${b.name}"? This cannot be undone.`)) return;
    try {
      await financeAPI.deleteBudget(b.id);
      toast.success('Budget deleted');
      setSelectedBudget('');
      load();
    } catch (e) { toast.error(e.response?.data?.detail || 'Failed'); }
  };

  return (
    <div className="space-y-4" data-testid="budgets-page">
      <div className="flex justify-between items-center">
        <div>
          <h3 className="text-lg font-semibold">Budgets</h3>
          <p className="text-xs text-slate-500">Set a monthly target per account, then track actuals against it through the year.</p>
        </div>
        <Button size="sm" onClick={() => setShow(true)} data-testid="budget-new-btn"><PlusCircle size={14} className="mr-1" /> New Budget</Button>
      </div>

      {budgets.length > 0 && (
        <div className="flex items-center gap-2">
          <Select value={selectedBudget} onValueChange={setSelectedBudget}>
            <SelectTrigger className="max-w-xs" data-testid="budget-select"><SelectValue placeholder="Select a budget" /></SelectTrigger>
            <SelectContent>
              {budgets.map(b => <SelectItem key={b.id} value={b.id}>{b.name} ({b.fyStart} → {b.fyEnd})</SelectItem>)}
            </SelectContent>
          </Select>
          <Button size="icon" variant="ghost" onClick={openEdit} disabled={!selectedBudget} data-testid="budget-edit-btn">
            <Pencil size={14} />
          </Button>
          <Button size="icon" variant="ghost" onClick={remove} disabled={!selectedBudget} data-testid="budget-delete-btn">
            <Trash2 size={14} className="text-rose-600" />
          </Button>
        </div>
      )}

      {report && report.rows.length > 0 && (
        <Card><CardContent className="p-4">
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">Budget vs actual</p>
          <div className="space-y-2.5">
            {report.rows.map(row => {
              const max = Math.max(row.budget, row.actual, 1);
              return (
                <div key={row.code} data-testid={`budget-chart-row-${row.code}`}>
                  <div className="flex justify-between text-xs mb-0.5">
                    <span className="font-mono text-slate-500 mr-1">{row.code}</span>
                    <span className="text-slate-600">{row.name}</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <div className="flex-1 h-3 rounded-full bg-slate-100 overflow-hidden" title={`Budget: ${FMT(row.budget)}`}>
                      <div className="h-full bg-slate-400 rounded-full" style={{ width: `${Math.min(100, (row.budget / max) * 100)}%` }} />
                    </div>
                    <div className={`flex-1 h-3 rounded-full bg-slate-100 overflow-hidden`} title={`Actual: ${FMT(row.actual)}`}>
                      <div className={`h-full rounded-full ${row.actual > row.budget ? 'bg-rose-500' : 'bg-emerald-500'}`}
                        style={{ width: `${Math.min(100, (row.actual / max) * 100)}%` }} />
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
          <div className="flex gap-4 mt-3 text-[11px] text-slate-500">
            <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-full bg-slate-400 inline-block" /> Budget</span>
            <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-full bg-emerald-500 inline-block" /> Actual (under)</span>
            <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-full bg-rose-500 inline-block" /> Actual (over)</span>
          </div>
        </CardContent></Card>
      )}

      {report && (
        <Card><CardContent className="p-0">
          <table className="w-full text-sm">
            <thead className="bg-slate-50"><tr>
              <th className="p-2 pl-4 text-left text-xs text-slate-500">Account</th>
              <th className="p-2 text-right text-xs text-slate-500">Budget</th>
              <th className="p-2 text-right text-xs text-slate-500">Actual</th>
              <th className="p-2 text-right text-xs text-slate-500">Variance</th>
              <th className="p-2 pr-4 text-right text-xs text-slate-500">Variance %</th>
            </tr></thead>
            <tbody>
              {report.rows.map(row => (
                <tr key={row.code} className="border-t" data-testid={`budget-row-${row.code}`}>
                  <td className="p-2 pl-4"><span className="font-mono text-xs mr-2">{row.code}</span>{row.name}</td>
                  <td className="p-2 text-right">{FMT(row.budget)}</td>
                  <td className="p-2 text-right">{FMT(row.actual)}</td>
                  <td className={`p-2 text-right font-medium ${row.variance > 0 ? 'text-rose-600' : 'text-emerald-600'}`}>{FMT(row.variance)}</td>
                  <td className="p-2 pr-4 text-right">
                    <Badge variant={Math.abs(row.variancePct) > 15 ? 'destructive' : 'outline'}>{row.variancePct}%</Badge>
                  </td>
                </tr>
              ))}
              {report.rows.length === 0 && (
                <tr><td colSpan={5} className="p-6 text-center text-slate-400">No budget lines to compare.</td></tr>
              )}
            </tbody>
          </table>
        </CardContent></Card>
      )}
      {!report && budgets.length === 0 && (
        <Card><CardContent className="p-8 text-center text-slate-400">No budgets yet — create one to start tracking against it.</CardContent></Card>
      )}

      <Dialog open={show} onOpenChange={o => { if (!o) closeDialog(); else setShow(true); }}>
        <DialogContent className="max-w-lg" data-testid="budget-new-dialog">
          <DialogHeader><DialogTitle>{editingId ? 'Edit Budget' : 'New Budget'}</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <Input placeholder="Budget name" value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} data-testid="budget-name" />
            <div className="grid grid-cols-2 gap-3">
              <Input type="date" value={form.fyStart} onChange={e => setForm({ ...form, fyStart: e.target.value })} />
              <Input type="date" value={form.fyEnd} onChange={e => setForm({ ...form, fyEnd: e.target.value })} />
            </div>
            <div className="space-y-2">
              <p className="text-xs font-medium text-slate-500">Monthly targets by account</p>
              {form.lines.map((line, i) => (
                <div key={i} className="flex gap-2 items-center" data-testid={`budget-line-${i}`}>
                  <Select value={line.accountCode} onValueChange={v => updateLine(i, 'accountCode', v)}>
                    <SelectTrigger className="flex-1"><SelectValue placeholder="Account" /></SelectTrigger>
                    <SelectContent>
                      {accounts.map(a => <SelectItem key={a.code} value={a.code}>{a.code} · {a.name}</SelectItem>)}
                    </SelectContent>
                  </Select>
                  <Input type="number" placeholder="$/month" className="w-28" value={line.monthlyAmount}
                    onChange={e => updateLine(i, 'monthlyAmount', e.target.value)} data-testid={`budget-line-amount-${i}`} />
                  <Button size="icon" variant="ghost" onClick={() => removeLine(i)}><X size={14} /></Button>
                </div>
              ))}
              <Button size="sm" variant="outline" onClick={addLine} data-testid="budget-add-line">+ Add account</Button>
            </div>
            <Button className="w-full" onClick={save} data-testid="budget-save-btn">{editingId ? 'Save Changes' : 'Create Budget'}</Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default Budgets;
