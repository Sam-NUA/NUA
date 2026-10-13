import React, { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import { Card, CardContent } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '../components/ui/dialog';
import { Textarea } from '../components/ui/textarea';
import { toast } from 'sonner';
import { ShieldCheck, ShieldAlert, ShieldX, Clock } from 'lucide-react';
import { SecureStorageService } from '../platform';

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const H = async () => ({ Authorization: `Bearer ${await SecureStorageService.getToken()}` });

export default function Approvals() {
  const [items, setItems] = useState([]);
  const [policy, setPolicy] = useState(null);
  const [filter, setFilter] = useState('pending');
  const [rejecting, setRejecting] = useState(null);
  const [reason, setReason] = useState('');

  const load = useCallback(async () => {
    try {
      const [i, p] = await Promise.all([
        axios.get(`${API}/approvals?status=${filter === 'all' ? '' : filter}`, { headers: await H() }),
        axios.get(`${API}/approvals/config/policy`, { headers: await H() }),
      ]);
      setItems(i.data); setPolicy(p.data);
    } catch { toast.error('Failed to load approvals'); }
  }, [filter]);
  useEffect(() => { load(); }, [load]);

  const approve = async (id) => {
    try { await axios.post(`${API}/approvals/${id}/approve`, {}, { headers: await H() }); toast.success('Approved & executed'); load(); }
    catch (e) { toast.error(e.response?.data?.detail || 'Failed'); }
  };
  const reject = async () => {
    try {
      await axios.post(`${API}/approvals/${rejecting.id}/reject`, { reason }, { headers: await H() });
      toast.success('Rejected');
      setRejecting(null); setReason(''); load();
    } catch (e) { toast.error(e.response?.data?.detail || 'Failed'); }
  };

  const badge = { pending: 'bg-amber-100 text-amber-700', approved: 'bg-emerald-100 text-emerald-700', rejected: 'bg-rose-100 text-rose-700' };

  return (
    <div className="space-y-6" data-testid="approvals-page">
      <div>
        <h1 className="text-3xl font-bold flex items-center gap-2"><ShieldCheck className="text-emerald-600" /> Approval Queue</h1>
        <p className="text-sm text-slate-500 mt-1">Every high-risk automated action lands here before it fires.</p>
      </div>

      {policy && (
        <Card><CardContent className="p-4 flex flex-wrap gap-3 text-sm">
          <span className="text-slate-500">Policy mode:</span>
          <Badge className="capitalize">{policy.mode}</Badge>
          <span className="text-slate-500">·</span>
          <span>Approve PO &gt; <b>${policy.poAbove}</b></span>
          <span>·</span>
          <span>Approve refunds &gt; <b>${policy.refundAbove}</b></span>
          {policy.tierDowngradesAlwaysApprove && <><span>·</span><span>Tier downgrades always approved</span></>}
        </CardContent></Card>
      )}

      <div className="flex gap-2">
        {['pending', 'approved', 'rejected', 'all'].map(f => (
          <Button key={f} size="sm" variant={filter === f ? 'default' : 'outline'} onClick={() => setFilter(f)} data-testid={`filter-${f}`}>
            {f.charAt(0).toUpperCase() + f.slice(1)}
          </Button>
        ))}
      </div>

      {items.length === 0 ? (
        <Card className="border-dashed"><CardContent className="p-10 text-center">
          <ShieldCheck size={40} className="mx-auto mb-3 text-slate-300" />
          <p className="text-slate-500">No {filter === 'all' ? '' : filter} approvals.</p>
        </CardContent></Card>
      ) : (
        <div className="space-y-3">
          {items.map(a => (
            <Card key={a.id} data-testid={`approval-${a.id}`}>
              <CardContent className="p-5">
                <div className="flex justify-between items-start gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      <h3 className="font-semibold">{a.actionType.replace(/_/g, ' ')}</h3>
                      <Badge className={`text-[10px] ${badge[a.status]}`}>{a.status}</Badge>
                    </div>
                    <p className="text-xs text-slate-500 mb-2">
                      Requested by <span className="font-mono">{a.requestedBy}</span> · {new Date(a.createdAt).toLocaleString()}
                    </p>
                    {a.context?.ruleName && <p className="text-xs text-slate-500">via rule: <span className="font-medium">{a.context.ruleName}</span></p>}
                    <pre className="mt-2 bg-slate-50 border rounded p-2 text-[11px] font-mono whitespace-pre-wrap">{JSON.stringify(a.params, null, 2)}</pre>
                    {a.outcome && (
                      <div className="mt-2 text-xs">
                        <span className="text-slate-500">Outcome: </span>
                        <span className="font-mono">{JSON.stringify(a.outcome)}</span>
                      </div>
                    )}
                    {a.resolution && <p className="text-xs text-rose-500 mt-1">Reason: {a.resolution}</p>}
                  </div>
                  {a.status === 'pending' && (
                    <div className="flex flex-col gap-2 shrink-0">
                      <Button size="sm" className="bg-emerald-600 hover:bg-emerald-700" onClick={() => approve(a.id)} data-testid={`approve-${a.id}`}>
                        <ShieldCheck size={12} className="mr-1" /> Approve
                      </Button>
                      <Button size="sm" variant="outline" className="text-rose-600 border-rose-200" onClick={() => setRejecting(a)} data-testid={`reject-${a.id}`}>
                        <ShieldX size={12} className="mr-1" /> Reject
                      </Button>
                    </div>
                  )}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      <Dialog open={!!rejecting} onOpenChange={o => !o && setRejecting(null)}>
        <DialogContent data-testid="reject-dialog">
          <DialogHeader><DialogTitle>Reject Approval</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <p className="text-sm text-slate-500">Why is this being rejected?</p>
            <Textarea value={reason} onChange={e => setReason(e.target.value)} placeholder="Optional reason…" data-testid="reject-reason" />
            <Button className="w-full bg-rose-600 hover:bg-rose-700" onClick={reject} data-testid="reject-submit">Reject</Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
