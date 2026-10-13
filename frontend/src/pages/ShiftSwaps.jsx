import React, { useState, useEffect } from 'react';
import { ArrowLeftRight, Check, X, Clock } from 'lucide-react';
import { Card, CardContent } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '../components/ui/dialog';
import { Input } from '../components/ui/input';
import { useTheme } from '../contexts/ThemeContext';
import { useAuth } from '../contexts/AuthContext';
import { v15API, staffMgmtAPI } from '../services/api';
import axios from 'axios';
import { toast } from 'sonner';
import { SecureStorageService } from '../platform';

const API = process.env.REACT_APP_BACKEND_URL;
const authHeader = async () => ({ Authorization: `Bearer ${await SecureStorageService.getToken()}` });

export default function ShiftSwaps() {
  const { theme } = useTheme();
  const { user } = useAuth();
  const canApprove = user?.role === 'owner' || user?.role === 'manager';
  const [swaps, setSwaps] = useState([]);
  const [shifts, setShifts] = useState([]);
  const [staff, setStaff] = useState([]);
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState({ shiftId: '', targetStaffId: '', reason: '' });

  const refresh = async () => {
    try { const r = await v15API.getSwaps(); setSwaps(r.data || []); } catch { toast.error('Failed to load shift swaps'); }
    try { const r = await staffMgmtAPI.getRoster(); setShifts(r.data || []); } catch { toast.error('Failed to load roster shifts'); }
    try { const r = await axios.get(`${API}/api/auth/staff`, { headers: await authHeader() }); setStaff(r.data || []); } catch { toast.error('Failed to load staff list'); }
  };
  useEffect(() => { refresh(); }, []);

  const create = async () => {
    if (!form.shiftId || !form.targetStaffId) { toast.error('Pick a shift and target staff'); return; }
    const target = staff.find(s => s.id === form.targetStaffId);
    try {
      await v15API.createSwap({ shiftId: form.shiftId, targetStaffId: form.targetStaffId, targetStaffName: target?.name, reason: form.reason });
      toast.success('Swap requested — pending manager approval');
      setShowCreate(false);
      setForm({ shiftId: '', targetStaffId: '', reason: '' });
      refresh();
    } catch { toast.error('Failed'); }
  };

  const approve = async (id) => { try { await v15API.approveSwap(id); toast.success('Approved'); refresh(); } catch {} };
  const reject = async (id) => { try { await v15API.rejectSwap(id); toast('Rejected'); refresh(); } catch {} };

  // My own shifts only (for staff users)
  const myShifts = shifts.filter(s => s.staffId === user?.id);

  return (
    <div className="space-y-6" data-testid="swaps-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2" style={{ color: theme.text }}><ArrowLeftRight size={22} /> Shift Swap Requests</h1>
          <p className="text-sm text-gray-500">Staff can request to swap a shift with a colleague. {canApprove ? 'You can approve / reject below.' : 'Your manager will be notified.'}</p>
        </div>
        <Button style={{ backgroundColor: theme.primary }} onClick={() => setShowCreate(true)} data-testid="new-swap-btn">Request Swap</Button>
      </div>
      <div className="space-y-2">
        {swaps.map(s => (
          <Card key={s.id} data-testid={`swap-${s.id}`}>
            <CardContent className="p-4 flex items-center justify-between">
              <div className="flex items-center gap-3">
                <Badge className={s.status === 'pending' ? 'bg-amber-100 text-amber-700' : s.status === 'approved' ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}>{s.status}</Badge>
                <div>
                  <p className="text-sm"><span className="font-semibold">{s.requestedByName}</span> → <span className="font-semibold">{s.targetStaffName}</span></p>
                  <p className="text-xs text-gray-500">Shift: <span className="font-mono">{s.shiftId}</span> · {s.reason || 'No reason given'}</p>
                </div>
              </div>
              {canApprove && s.status === 'pending' && (
                <div className="flex gap-2">
                  <Button size="sm" variant="outline" onClick={() => approve(s.id)} className="text-green-600" data-testid={`approve-${s.id}`}><Check size={14} /></Button>
                  <Button size="sm" variant="outline" onClick={() => reject(s.id)} className="text-red-500" data-testid={`reject-${s.id}`}><X size={14} /></Button>
                </div>
              )}
            </CardContent>
          </Card>
        ))}
        {swaps.length === 0 && <Card className="border-dashed"><CardContent className="py-12 text-center text-gray-400"><Clock size={40} className="mx-auto mb-3 opacity-30" /><p>No swap requests yet</p></CardContent></Card>}
      </div>

      <Dialog open={showCreate} onOpenChange={setShowCreate}>
        <DialogContent className="max-w-sm" data-testid="swap-dialog">
          <DialogHeader><DialogTitle>Request Shift Swap</DialogTitle></DialogHeader>
          <div className="space-y-3 py-2">
            <select className="w-full p-2 border rounded-md text-sm" value={form.shiftId} onChange={e => setForm({ ...form, shiftId: e.target.value })} data-testid="swap-shift">
              <option value="">Select my shift...</option>
              {(canApprove ? shifts : myShifts).map(s => <option key={s.id} value={s.id}>{s.date} · {s.startTime}-{s.endTime} · {s.staffName}</option>)}
            </select>
            <select className="w-full p-2 border rounded-md text-sm" value={form.targetStaffId} onChange={e => setForm({ ...form, targetStaffId: e.target.value })} data-testid="swap-target">
              <option value="">Swap with...</option>
              {staff.filter(s => s.id !== user?.id).map(s => <option key={s.id} value={s.id}>{s.name} ({s.role})</option>)}
            </select>
            <Input placeholder="Reason (optional)" value={form.reason} onChange={e => setForm({ ...form, reason: e.target.value })} data-testid="swap-reason" />
            <Button className="w-full" style={{ backgroundColor: theme.primary }} onClick={create} data-testid="swap-submit">Submit Request</Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
