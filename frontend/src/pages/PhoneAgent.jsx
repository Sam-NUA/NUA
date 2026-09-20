import React, { useState, useEffect } from 'react';
import { Phone, Send, Sparkles, Clock, CheckCircle2 } from 'lucide-react';
import { Card, CardContent } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Badge } from '../components/ui/badge';
import { useTheme } from '../contexts/ThemeContext';
import { phaseEFAPI } from '../services/api';
import { toast } from 'sonner';

const EXAMPLES = [
  { caller: '+61400111222', transcript: 'Hi, I\'d like to book a table for 4 people this Saturday at 7 PM. My name is John.' },
  { caller: '+61400333444', transcript: 'Can I order a large pepperoni pizza and 2 cokes for pickup?' },
  { caller: '+61400555666', transcript: 'What time do you close on Sunday?' },
];

export default function PhoneAgent() {
  const { theme } = useTheme();
  const [calls, setCalls] = useState([]);
  const [caller, setCaller] = useState('');
  const [transcript, setTranscript] = useState('');
  const [loading, setLoading] = useState(false);

  const refresh = async () => { try { const r = await phaseEFAPI.getCalls(); setCalls(r.data || []); } catch {} };
  useEffect(() => { refresh(); }, []);

  const simulate = async () => {
    if (!caller.trim() || !transcript.trim()) { toast.error('Caller + transcript required'); return; }
    setLoading(true);
    try {
      const r = await phaseEFAPI.simulateCall(caller, transcript);
      const actions = r.data?.actions || [];
      toast.success(`Intent: ${r.data?.intent}${actions.length ? ` · ${actions.length} action(s)` : ''}`);
      setCaller(''); setTranscript('');
      refresh();
    } catch { toast.error('Simulation failed'); }
    setLoading(false);
  };

  const colors = { reservation: 'bg-green-100 text-green-700', order: 'bg-blue-100 text-blue-700', inquiry: 'bg-amber-100 text-amber-700', other: 'bg-gray-100 text-gray-700', unknown: 'bg-red-100 text-red-700' };

  return (
    <div className="space-y-6" data-testid="phone-agent-page">
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2" style={{ color: theme.text }}><Phone size={22} /> AI Phone Agent</h1>
        <p className="text-sm text-gray-500">Inbound calls handled by AI. Books reservations, drafts orders, logs inquiries. Wire Twilio Voice for live calls.</p>
      </div>

      <Card>
        <CardContent className="p-5 space-y-3">
          <h2 className="font-bold text-sm uppercase tracking-wider text-gray-500 flex items-center gap-2"><Sparkles size={14} /> Simulate Inbound Call</h2>
          <Input placeholder="Caller phone (e.g. +61400111222)" value={caller} onChange={e => setCaller(e.target.value)} data-testid="phone-caller" />
          <textarea className="w-full p-2 border rounded-md text-sm min-h-[80px]" placeholder="Transcript (what the caller said)" value={transcript} onChange={e => setTranscript(e.target.value)} data-testid="phone-transcript" />
          <div className="flex flex-wrap gap-2">
            {EXAMPLES.map((ex, i) => (
              <button key={i} onClick={() => { setCaller(ex.caller); setTranscript(ex.transcript); }} className="text-[10px] px-2 py-1 rounded-full border bg-gray-50 hover:bg-gray-100">{ex.transcript.slice(0, 40)}...</button>
            ))}
          </div>
          <Button onClick={simulate} disabled={loading} style={{ backgroundColor: theme.primary }} data-testid="simulate-call-btn">
            <Send size={14} className="mr-1" /> {loading ? 'Processing...' : 'Simulate Call'}
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-0">
          <div className="p-4 border-b"><h2 className="font-bold text-sm uppercase tracking-wider text-gray-500">Recent Calls ({calls.length})</h2></div>
          <div className="divide-y">
            {calls.map(c => (
              <div key={c.id} className="p-4" data-testid={`call-${c.id}`}>
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <Badge className={colors[c.intent] || 'bg-gray-100'}>{c.intent}</Badge>
                    <span className="text-sm font-medium">{c.caller}</span>
                    <span className="text-xs text-gray-400 flex items-center gap-1"><Clock size={10} /> {new Date(c.startedAt).toLocaleString()}</span>
                  </div>
                </div>
                <p className="text-sm text-gray-600 bg-gray-50 p-2 rounded">"{c.transcript}"</p>
                {(c.actions || []).map((a, i) => (
                  <div key={i} className="mt-2 space-y-1">
                    <div className="text-xs text-green-700 flex items-center gap-1">
                      <CheckCircle2 size={12} /> {a.action}{a.id ? ` (${a.id})` : ''}
                      {a.kitchenOrderId ? ` — sent to kitchen (${a.kitchenOrderId})` : ''}
                    </div>
                    {a.items?.length > 0 && (
                      <div className="text-xs text-gray-500 pl-4">Ordered: {a.items.map(it => `${it.quantity}x ${it.productName}`).join(', ')}</div>
                    )}
                    {a.unmatchedItems?.length > 0 && (
                      <div className="text-xs text-amber-600 pl-4">Couldn't match to the menu: {a.unmatchedItems.join(', ')}</div>
                    )}
                  </div>
                ))}
              </div>
            ))}
            {calls.length === 0 && <div className="py-12 text-center text-gray-400"><Phone size={36} className="mx-auto mb-2 opacity-30" /><p>No calls yet</p></div>}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
