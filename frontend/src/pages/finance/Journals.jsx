import React, { useState, useEffect, useCallback } from 'react';
import { financeAPI } from '../../services/api';
import { toast } from 'sonner';
import { Card, CardContent } from '../../components/ui/card';
import { Button } from '../../components/ui/button';
import { Input } from '../../components/ui/input';
import { Badge } from '../../components/ui/badge';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '../../components/ui/dialog';
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from '../../components/ui/select';
import { PlusCircle, ArrowLeftRight } from 'lucide-react';
import { DialogService } from '../../platform';
import { FMT, today } from './helpers';

const Journals = () => {
  const [journals, setJournals] = useState([]);
  const [accounts, setAccounts] = useState([]);
  const [showNew, setShowNew] = useState(false);
  const [entry, setEntry] = useState({
    date: today(), memo: '',
    lines: [{ accountCode: '', debit: 0, credit: 0 }, { accountCode: '', debit: 0, credit: 0 }],
  });

  const load = useCallback(async () => {
    try {
      const [j, a] = await Promise.all([financeAPI.listJournals({ limit: 100 }), financeAPI.listAccounts()]);
      setJournals(j.data); setAccounts(a.data);
    } catch { toast.error('Could not load journals'); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const totals = entry.lines.reduce((acc, l) => ({
    debit: acc.debit + parseFloat(l.debit || 0),
    credit: acc.credit + parseFloat(l.credit || 0),
  }), { debit: 0, credit: 0 });
  const balanced = Math.abs(totals.debit - totals.credit) < 0.005 && totals.debit > 0;

  const save = async () => {
    if (!balanced) return toast.error('Entry must be balanced');
    if (entry.lines.some(l => !l.accountCode)) return toast.error('All lines need an account');
    try {
      await financeAPI.createJournal({
        date: entry.date, memo: entry.memo,
        lines: entry.lines.map(l => ({
          accountCode: l.accountCode,
          debit: parseFloat(l.debit || 0),
          credit: parseFloat(l.credit || 0),
          description: l.description || '',
        })),
      });
      toast.success('Journal posted');
      setShowNew(false);
      setEntry({ date: today(), memo: '', lines: [{ accountCode: '', debit: 0, credit: 0 }, { accountCode: '', debit: 0, credit: 0 }] });
      load();
    } catch (e) { toast.error(e.response?.data?.detail || 'Failed'); }
  };

  const reverse = async (id) => {
    if (!await DialogService.confirm('Reverse this journal? A new balancing entry will be posted.')) return;
    try { await financeAPI.reverseJournal(id, {}); toast.success('Reversed'); load(); }
    catch (e) { toast.error(e.response?.data?.detail || 'Failed'); }
  };

  const updateLine = (i, patch) => {
    const next = entry.lines.map((l, ix) => ix === i ? { ...l, ...patch } : l);
    setEntry({ ...entry, lines: next });
  };

  return (
    <div className="space-y-4" data-testid="journals-page">
      <div className="flex justify-between items-center">
        <h3 className="text-lg font-semibold">General Journal</h3>
        <Button size="sm" onClick={() => setShowNew(true)} data-testid="journal-new-btn">
          <PlusCircle size={14} className="mr-1" /> New Entry
        </Button>
      </div>
      <Card><CardContent className="p-0">
        <table className="w-full text-sm">
          <thead className="bg-slate-50"><tr>
            <th className="text-left p-2 pl-4 text-xs text-slate-500">Journal #</th>
            <th className="text-left p-2 text-xs text-slate-500">Date</th>
            <th className="text-left p-2 text-xs text-slate-500">Source</th>
            <th className="text-left p-2 text-xs text-slate-500">Memo</th>
            <th className="text-right p-2 pr-4 text-xs text-slate-500">Amount</th>
            <th className="p-2 pr-4"></th>
          </tr></thead>
          <tbody>
            {journals.map(j => {
              const amount = (j.lines || []).reduce((s, l) => s + (l.debit || 0), 0);
              return (
                <tr key={j.id} className="border-t hover:bg-slate-50" data-testid={`journal-row-${j.journalNumber}`}>
                  <td className="p-2 pl-4 font-mono text-xs">{j.journalNumber}</td>
                  <td className="p-2">{j.date}</td>
                  <td className="p-2"><Badge variant="outline" className="text-xs">{j.sourceType}</Badge></td>
                  <td className="p-2 text-slate-600">{j.memo}</td>
                  <td className="p-2 pr-4 text-right font-medium">{FMT(amount)}</td>
                  <td className="p-2 pr-4 text-right">
                    <Button size="sm" variant="ghost" onClick={() => reverse(j.id)} data-testid={`journal-reverse-${j.journalNumber}`}>
                      <ArrowLeftRight size={14} />
                    </Button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {journals.length === 0 && <p className="text-center text-slate-400 py-8">No journals yet</p>}
      </CardContent></Card>

      <Dialog open={showNew} onOpenChange={setShowNew}>
        <DialogContent className="max-w-3xl max-h-[85vh] overflow-y-auto" data-testid="journal-new-dialog">
          <DialogHeader><DialogTitle>New Journal Entry</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <Input type="date" value={entry.date} onChange={e => setEntry({ ...entry, date: e.target.value })} data-testid="journal-date" />
              <Input placeholder="Memo" value={entry.memo} onChange={e => setEntry({ ...entry, memo: e.target.value })} data-testid="journal-memo" />
            </div>
            <table className="w-full text-sm border rounded overflow-hidden">
              <thead className="bg-slate-50">
                <tr>
                  <th className="p-2 text-left">Account</th>
                  <th className="p-2 text-right w-32">Debit</th>
                  <th className="p-2 text-right w-32">Credit</th>
                  <th className="p-2 text-left">Description</th>
                </tr>
              </thead>
              <tbody>
                {entry.lines.map((l, i) => (
                  <tr key={i} className="border-t">
                    <td className="p-2">
                      <Select value={l.accountCode} onValueChange={v => updateLine(i, { accountCode: v })}>
                        <SelectTrigger data-testid={`journal-line-${i}-account`}><SelectValue placeholder="Select…" /></SelectTrigger>
                        <SelectContent>
                          {accounts.map(a => <SelectItem key={a.code} value={a.code}>{a.code} — {a.name}</SelectItem>)}
                        </SelectContent>
                      </Select>
                    </td>
                    <td className="p-2"><Input type="number" step="0.01" value={l.debit} onChange={e => updateLine(i, { debit: e.target.value, credit: 0 })} className="text-right" data-testid={`journal-line-${i}-debit`} /></td>
                    <td className="p-2"><Input type="number" step="0.01" value={l.credit} onChange={e => updateLine(i, { credit: e.target.value, debit: 0 })} className="text-right" data-testid={`journal-line-${i}-credit`} /></td>
                    <td className="p-2"><Input placeholder="Line memo" value={l.description || ''} onChange={e => updateLine(i, { description: e.target.value })} /></td>
                  </tr>
                ))}
              </tbody>
              <tfoot className="bg-slate-50 font-medium">
                <tr>
                  <td className="p-2 text-right">Totals</td>
                  <td className="p-2 text-right">{FMT(totals.debit)}</td>
                  <td className="p-2 text-right">{FMT(totals.credit)}</td>
                  <td className="p-2">
                    {balanced ? <Badge className="bg-emerald-500">Balanced</Badge> : <Badge className="bg-rose-500">Off {FMT(totals.debit - totals.credit)}</Badge>}
                  </td>
                </tr>
              </tfoot>
            </table>
            <div className="flex justify-between">
              <Button variant="outline" size="sm" onClick={() => setEntry({ ...entry, lines: [...entry.lines, { accountCode: '', debit: 0, credit: 0 }] })} data-testid="journal-add-line">
                + Add line
              </Button>
              <Button onClick={save} disabled={!balanced} data-testid="journal-post-btn">Post Journal</Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default Journals;
