import React, { useEffect, useState, useCallback, useMemo } from 'react';
import axios from 'axios';
import { Card, CardContent } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Input } from '../components/ui/input';
import { Textarea } from '../components/ui/textarea';
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from '../components/ui/select';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '../components/ui/dialog';
import { toast } from 'sonner';
import { BookMarked, RefreshCw, Plus, Trash2, Search } from 'lucide-react';
import { DialogService } from '../platform';

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const H = () => ({ Authorization: `Bearer ${localStorage.getItem('nua_token')}` });

const KIND_TONE = {
  preference: 'bg-indigo-500', pattern: 'bg-emerald-500',
  fact: 'bg-slate-500', note: 'bg-amber-500',
};

export default function AshMemory() {
  const [memories, setMemories] = useState([]);
  const [scopes, setScopes] = useState({});
  const [scopeFilter, setScopeFilter] = useState('all');
  const [kindFilter, setKindFilter] = useState('all');
  const [query, setQuery] = useState('');
  const [refreshing, setRefreshing] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [form, setForm] = useState({ text: '', scope: 'global', kind: 'preference', confidence: 1 });

  const load = useCallback(async () => {
    setRefreshing(true);
    try {
      const [m, s] = await Promise.all([
        axios.get(`${API}/nua/memory?limit=200`, { headers: H() }),
        axios.get(`${API}/nua/memory/scopes`, { headers: H() }),
      ]);
      setMemories(m.data);
      setScopes(s.data);
    } catch { toast.error('Failed to load memory'); }
    finally { setRefreshing(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const saveMemory = async () => {
    if (!form.text.trim()) return;
    try {
      await axios.post(`${API}/nua/memory`, form, { headers: H() });
      toast.success('Remembered');
      setAddOpen(false);
      setForm({ text: '', scope: 'global', kind: 'preference', confidence: 1 });
      await load();
    } catch { toast.error('Failed'); }
  };

  const deleteMemory = async (id) => {
    if (!await DialogService.confirm('Ask NUA to forget this? This cannot be undone.')) return;
    try {
      await axios.delete(`${API}/nua/memory/${id}`, { headers: H() });
      setMemories(ms => ms.filter(m => m.id !== id));
      toast('Forgotten');
    } catch { toast.error('Failed'); }
  };

  const filtered = useMemo(() => memories.filter(m =>
    (scopeFilter === 'all' || m.scope === scopeFilter) &&
    (kindFilter === 'all' || m.kind === kindFilter) &&
    (query.trim() === '' || m.text.toLowerCase().includes(query.toLowerCase()))
  ), [memories, scopeFilter, kindFilter, query]);

  const scopeOptions = Object.keys(scopes).sort();

  return (
    <div className="space-y-6" data-testid="ash-memory-page">
      <div className="flex justify-between items-center flex-wrap gap-3">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-2">
            <BookMarked className="text-indigo-600" /> NUA Memory
          </h1>
          <p className="text-sm text-slate-500 mt-1">Long-term facts, preferences and patterns NUA uses to ground every conversation.</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={load} disabled={refreshing} data-testid="mem-refresh-btn">
            <RefreshCw size={14} className={`mr-1.5 ${refreshing ? 'animate-spin' : ''}`} /> Refresh
          </Button>
          <Dialog open={addOpen} onOpenChange={setAddOpen}>
            <DialogTrigger asChild>
              <Button data-testid="add-memory-btn"><Plus size={14} className="mr-1" /> Teach NUA</Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader><DialogTitle>Teach NUA a new fact</DialogTitle></DialogHeader>
              <div className="space-y-3">
                <div>
                  <label className="text-xs text-slate-500">Statement</label>
                  <Textarea rows={3} value={form.text}
                    onChange={e => setForm(f => ({ ...f, text: e.target.value }))}
                    placeholder="e.g. Table 4 is always reserved for the owner on Friday nights."
                    data-testid="mem-text-input" />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-xs text-slate-500">Scope</label>
                    <Input value={form.scope}
                      onChange={e => setForm(f => ({ ...f, scope: e.target.value }))}
                      placeholder="global, customer:xyz, product:abc"
                      data-testid="mem-scope-input" />
                  </div>
                  <div>
                    <label className="text-xs text-slate-500">Kind</label>
                    <Select value={form.kind} onValueChange={v => setForm(f => ({ ...f, kind: v }))}>
                      <SelectTrigger data-testid="mem-kind-select"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="preference">Preference</SelectItem>
                        <SelectItem value="pattern">Pattern</SelectItem>
                        <SelectItem value="fact">Fact</SelectItem>
                        <SelectItem value="note">Note</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                </div>
                <Button className="w-full" onClick={saveMemory} disabled={!form.text.trim()} data-testid="save-memory-btn">
                  Remember
                </Button>
              </div>
            </DialogContent>
          </Dialog>
        </div>
      </div>

      {/* Filters + scope chips */}
      <Card>
        <CardContent className="p-4 space-y-3">
          <div className="flex flex-wrap gap-3">
            <div className="relative flex-1 min-w-[200px]">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <Input placeholder="Search memories\u2026" value={query} onChange={e => setQuery(e.target.value)} className="pl-9" data-testid="mem-search" />
            </div>
            <Select value={kindFilter} onValueChange={setKindFilter}>
              <SelectTrigger className="w-36" data-testid="kind-filter"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All kinds</SelectItem>
                <SelectItem value="preference">Preferences</SelectItem>
                <SelectItem value="pattern">Patterns</SelectItem>
                <SelectItem value="fact">Facts</SelectItem>
                <SelectItem value="note">Notes</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              className={`text-[11px] px-2 py-1 rounded-full border ${scopeFilter === 'all' ? 'bg-indigo-600 text-white' : 'bg-white text-slate-700'}`}
              onClick={() => setScopeFilter('all')}
              data-testid="scope-all"
            >All ({memories.length})</button>
            {scopeOptions.map(s => (
              <button
                key={s}
                className={`text-[11px] px-2 py-1 rounded-full border ${scopeFilter === s ? 'bg-indigo-600 text-white' : 'bg-white text-slate-700'}`}
                onClick={() => setScopeFilter(s)}
                data-testid={`scope-${s}`}
              >{s} ({scopes[s]})</button>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Memory list */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {filtered.length === 0 && (
          <Card className="md:col-span-2"><CardContent className="p-12 text-center text-sm text-slate-500">
            <BookMarked className="mx-auto mb-2 opacity-40" size={28} />
            No memories yet. Teach NUA something, or wait for it to observe patterns.
          </CardContent></Card>
        )}
        {filtered.map(m => (
          <Card key={m.id} data-testid={`memory-${m.id}`}>
            <CardContent className="p-4">
              <div className="flex justify-between items-start gap-3 mb-2">
                <div className="flex gap-1 flex-wrap">
                  <Badge className={KIND_TONE[m.kind] || 'bg-slate-500'}>{m.kind}</Badge>
                  <Badge variant="outline" className="font-mono text-[9px]">{m.scope}</Badge>
                </div>
                <button onClick={() => deleteMemory(m.id)} className="text-slate-400 hover:text-rose-500" data-testid={`del-mem-${m.id}`}>
                  <Trash2 size={14} />
                </button>
              </div>
              <p className="text-sm leading-relaxed">{m.text}</p>
              <div className="flex justify-between items-center mt-3 pt-2 border-t text-[10px] text-slate-500">
                <span>confidence <span className="font-semibold">{Math.round((m.confidence || 0) * 100)}%</span></span>
                <span>used {m.usageCount || 0}\u00d7 &middot; {(m.source || 'agent')}</span>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
