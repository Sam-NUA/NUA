import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import { Receipt, Check, Users, Loader2, Bitcoin, CreditCard, X } from 'lucide-react';
import { Button } from '../components/ui/button';
import { Card, CardContent } from '../components/ui/card';
import { Input } from '../components/ui/input';
import { billSplitAPI, guestSessionAPI } from '../services/api';
import { toast } from 'sonner';

const TOKEN_KEY = 'nua_guest_token';
const PHONE_KEY = 'nua_guest_phone';
const mineKey = (splitId) => `nua_guest_mine_${splitId}`;

function money(n) { return `$${(n || 0).toFixed(2)}`; }

function loadMine(splitId) {
  try {
    const raw = sessionStorage.getItem(mineKey(splitId));
    if (!raw) return { lines: new Set(), slots: new Set() };
    const parsed = JSON.parse(raw);
    return { lines: new Set(parsed.lines || []), slots: new Set(parsed.slots || []) };
  } catch { return { lines: new Set(), slots: new Set() }; }
}
function saveMine(splitId, mine) {
  sessionStorage.setItem(mineKey(splitId), JSON.stringify({ lines: [...mine.lines], slots: [...mine.slots] }));
}

// A shared-QR guest bill-split page: no login, works from any phone that
// scanned the table's QR code or followed the link. Verifying a phone
// (OTP, real SMS) is only required to claim/pay — browsing the bill is
// open to anyone with the link, matching the trust model the QR
// table-ordering pages already use.
//
// The public API deliberately never says WHICH phone claimed a line (see
// routes/bill_split.py's _public_view) — this page has to track "which of
// the claimed items are mine" itself, in sessionStorage so a phone
// locking mid-payment doesn't lose track of what was already claimed.
export default function SplitBillGuest() {
  const { tableNumber: tableFromPath } = useParams();
  const [searchParams] = useSearchParams();
  const splitParam = searchParams.get('split');

  const [split, setSplit] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [mine, setMine] = useState({ lines: new Set(), slots: new Set() });
  const [selected, setSelected] = useState([]); // open lineIds staged for the next claim call
  const [equalCount, setEqualCount] = useState(4);
  const [phone, setPhone] = useState(sessionStorage.getItem(PHONE_KEY) || '');
  const [token, setToken] = useState(sessionStorage.getItem(TOKEN_KEY) || '');
  const [otpStage, setOtpStage] = useState(null); // null | 'code-sent'
  const [otpCode, setOtpCode] = useState('');
  const [busy, setBusy] = useState(false);
  const pollRef = useRef(null);

  const load = useCallback(async () => {
    try {
      const res = splitParam
        ? await billSplitAPI.status(splitParam)
        : await billSplitAPI.getSplit(tableFromPath, new URLSearchParams(window.location.search).get("business"));
      setSplit(res.data);
      setMine(loadMine(res.data.id));
      setError(null);
    } catch (e) {
      setError(e?.response?.data?.detail || "Couldn't load this table's bill.");
    } finally {
      setLoading(false);
    }
  }, [tableFromPath, splitParam]);

  useEffect(() => {
    load();
    pollRef.current = setInterval(load, 4000); // other guests claiming/paying show up live
    return () => clearInterval(pollRef.current);
  }, [load]);

  const rememberMine = (patch) => {
    setMine(prev => {
      const next = {
        lines: new Set([...prev.lines, ...(patch.lines || [])]),
        slots: new Set([...prev.slots, ...(patch.slots || [])]),
      };
      if (split?.id) saveMine(split.id, next);
      return next;
    });
  };

  const requestCode = async () => {
    if (!phone.trim()) { toast.error('Enter your mobile number'); return; }
    setBusy(true);
    try {
      await guestSessionAPI.requestCode(phone.trim());
      setOtpStage('code-sent');
      toast.success('Code sent — check your phone');
    } catch { toast.error('Could not send a code — try again'); }
    finally { setBusy(false); }
  };

  const verifyCode = async () => {
    if (!otpCode.trim()) return;
    setBusy(true);
    try {
      const r = await guestSessionAPI.verify(phone.trim(), otpCode.trim(), split?.businessId || new URLSearchParams(window.location.search).get("business"));
      setToken(r.data.token);
      sessionStorage.setItem(TOKEN_KEY, r.data.token);
      sessionStorage.setItem(PHONE_KEY, phone.trim());
      setOtpStage(null);
      setOtpCode('');
    } catch (e) {
      toast.error(e?.response?.data?.detail || "That code didn't match");
    } finally { setBusy(false); }
  };

  const chooseMode = async (mode) => {
    const table = split?.tableNumber || tableFromPath;
    setBusy(true);
    try {
      const r = await billSplitAPI.chooseMode(table, mode, equalCount, { business: new URLSearchParams(window.location.search).get("business") });
      setSplit(r.data);
    } catch (e) { toast.error(e?.response?.data?.detail || 'Could not set split mode'); }
    finally { setBusy(false); }
  };

  const toggleLine = (line) => {
    if (line.status !== 'open') return; // nothing to stage on an already-claimed/paid line
    setSelected(prev => prev.includes(line.id) ? prev.filter(id => id !== line.id) : [...prev, line.id]);
  };

  const claimSelected = async () => {
    if (!token) { toast.error('Verify your phone first'); return; }
    if (!selected.length) return;
    setBusy(true);
    try {
      const r = await billSplitAPI.claim(split.id, selected, token);
      setSplit(r.data.split);
      if (r.data.failed.length) toast.error('Someone else just claimed an item you picked — list refreshed.');
      rememberMine({ lines: r.data.claimed });
      setSelected([]);
    } catch (e) { toast.error(e?.response?.data?.detail || 'Could not claim those items'); }
    finally { setBusy(false); }
  };

  const claimEqualSlot = async (index) => {
    if (!token) { toast.error('Verify your phone first'); return; }
    setBusy(true);
    try {
      const r = await billSplitAPI.claimEqual(split.id, index, token);
      setSplit(r.data);
      rememberMine({ slots: [index] });
    } catch (e) { toast.error(e?.response?.data?.detail || 'That share was just taken'); }
    finally { setBusy(false); }
  };

  const pay = async (provider, lineIds, slotIndex) => {
    if (!token) { toast.error('Verify your phone first'); return; }
    setBusy(true);
    try {
      const r = await billSplitAPI.checkout(split.id, {
        provider, lineIds, slotIndex, originUrl: window.location.origin,
      }, token);
      window.location.href = r.data.url;
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Could not start checkout');
      setBusy(false);
    }
  };

  if (loading) {
    return <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <Loader2 size={32} className="animate-spin text-gray-400" />
    </div>;
  }
  if (error || !split) {
    return <div className="min-h-screen flex items-center justify-center bg-gray-50 p-6 text-center">
      <div>
        <Receipt size={40} className="mx-auto mb-3 text-gray-300" />
        <p className="text-gray-500">{error || 'No open bill for this table right now.'}</p>
      </div>
    </div>;
  }

  const myClaimedLines = split.lines.filter(l => mine.lines.has(l.id) && l.status === 'claimed');
  const myUnpaidSlots = (split.equalParts || []).filter(p => mine.slots.has(p.index) && p.status === 'claimed');
  const selectedTotal = split.lines.filter(l => selected.includes(l.id)).reduce((s, l) => s + l.unitPrice, 0);

  return (
    <div className="min-h-screen bg-gray-50 pb-28" data-testid="split-bill-guest-page">
      <div className="bg-white border-b px-5 py-4 sticky top-0 z-10">
        <div className="flex items-center gap-2">
          <Receipt size={20} className="text-orange-500" />
          <h1 className="font-bold text-lg">Table {split.tableNumber}</h1>
        </div>
        <p className="text-xs text-gray-400 mt-0.5">
          {split.status === 'settled' ? 'Fully paid ✓' : "Split the bill — pay just your share"}
        </p>
      </div>

      <div className="p-4 space-y-4 max-w-md mx-auto">
        {!split.mode && (
          <Card>
            <CardContent className="p-5 space-y-3">
              <p className="font-medium text-sm">How's everyone splitting this?</p>
              <Button className="w-full justify-start" variant="outline" onClick={() => chooseMode('items')} disabled={busy}>
                Pick your own items
              </Button>
              <div className="flex items-center gap-2">
                <Button className="flex-1 justify-start" variant="outline" onClick={() => chooseMode('equal')} disabled={busy}>
                  <Users size={16} className="mr-2" /> Split evenly
                </Button>
                <Input type="number" min="1" max="20" value={equalCount}
                       onChange={e => setEqualCount(Number(e.target.value))} className="w-16" />
              </div>
            </CardContent>
          </Card>
        )}

        {split.mode === 'items' && (
          <Card>
            <CardContent className="p-5">
              <p className="font-semibold text-sm mb-3">Tap what's yours</p>
              <div className="space-y-2">
                {split.lines.map(line => {
                  const isMineClaimed = mine.lines.has(line.id) && line.status === 'claimed';
                  const isStaged = selected.includes(line.id);
                  const isMine = isStaged || isMineClaimed;
                  const disabled = line.status === 'paid' || (line.status === 'claimed' && !isMine);
                  return (
                    <button key={line.id} disabled={disabled}
                      onClick={() => toggleLine(line)}
                      data-testid={`split-line-${line.id}`}
                      className={`w-full flex items-center justify-between px-3 py-2.5 rounded-lg border text-sm text-left
                        ${line.status === 'paid' ? 'bg-emerald-50 border-emerald-200 text-emerald-700' :
                          line.status === 'claimed' && !isMine ? 'bg-gray-100 border-gray-200 text-gray-400' :
                          isMine ? 'bg-orange-50 border-orange-400' : 'bg-white border-gray-200 hover:border-gray-400'}`}>
                      <span className="flex items-center gap-2">
                        {isMine && line.status !== 'paid' && <Check size={14} className="text-orange-500" />}
                        {line.status === 'paid' && <Check size={14} className="text-emerald-500" />}
                        {line.productName}
                      </span>
                      <span className="font-mono">{money(line.unitPrice)}</span>
                    </button>
                  );
                })}
              </div>
              {selected.length > 0 && (
                <Button className="w-full mt-4 bg-gray-800 hover:bg-gray-900 text-white" onClick={claimSelected} disabled={busy}
                  data-testid="claim-items-btn">
                  Claim {selected.length} item{selected.length > 1 ? 's' : ''} — {money(selectedTotal)}
                </Button>
              )}
              {myClaimedLines.length > 0 && (
                <div className="mt-4 pt-4 border-t">
                  <p className="text-xs text-gray-500 mb-2">
                    Your total: {money(myClaimedLines.reduce((s, l) => s + l.unitPrice, 0))} — pay when ready
                  </p>
                  <div className="flex gap-2">
                    <Button className="flex-1 bg-orange-500 hover:bg-orange-600 text-white" disabled={busy}
                      onClick={() => pay('stripe', myClaimedLines.map(l => l.id), null)} data-testid="pay-card-btn">
                      <CreditCard size={15} className="mr-1.5" /> Card
                    </Button>
                    <Button className="flex-1 bg-gray-800 hover:bg-gray-900 text-white" disabled={busy}
                      onClick={() => pay('crypto', myClaimedLines.map(l => l.id), null)} data-testid="pay-crypto-btn">
                      <Bitcoin size={15} className="mr-1.5" /> Crypto
                    </Button>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        )}

        {split.mode === 'equal' && (
          <Card>
            <CardContent className="p-5">
              <p className="font-semibold text-sm mb-3">Pick your share</p>
              <div className="grid grid-cols-2 gap-2">
                {split.equalParts.map(part => {
                  const isMineSlot = mine.slots.has(part.index) && part.status === 'claimed';
                  return (
                    <button key={part.index} disabled={part.status !== 'open' && !isMineSlot}
                      data-testid={`split-slot-${part.index}`}
                      onClick={() => part.status === 'open' && claimEqualSlot(part.index)}
                      className={`px-3 py-3 rounded-lg border text-sm
                        ${part.status === 'paid' ? 'bg-emerald-50 border-emerald-200 text-emerald-700' :
                          isMineSlot ? 'bg-orange-50 border-orange-400' :
                          part.status === 'claimed' ? 'bg-gray-100 border-gray-200 text-gray-400' :
                          'bg-white border-gray-200 hover:border-orange-400'}`}>
                      <div className="font-mono font-bold">{money(part.amount)}</div>
                      <div className="text-[10px] uppercase tracking-wide mt-0.5">
                        {part.status === 'paid' ? 'Paid' : isMineSlot ? 'Yours' : part.status === 'claimed' ? 'Taken' : 'Tap to claim'}
                      </div>
                    </button>
                  );
                })}
              </div>
              {myUnpaidSlots.length > 0 && (
                <div className="mt-4 pt-4 border-t space-y-3">
                  {myUnpaidSlots.map(slot => (
                    <div key={slot.index} className="flex items-center gap-2">
                      <span className="text-sm font-mono flex-1">{money(slot.amount)}</span>
                      <Button size="sm" className="bg-orange-500 hover:bg-orange-600 text-white" disabled={busy}
                        onClick={() => pay('stripe', [], slot.index)} data-testid={`pay-slot-card-${slot.index}`}>
                        <CreditCard size={14} className="mr-1" /> Card
                      </Button>
                      <Button size="sm" className="bg-gray-800 hover:bg-gray-900 text-white" disabled={busy}
                        onClick={() => pay('crypto', [], slot.index)} data-testid={`pay-slot-crypto-${slot.index}`}>
                        <Bitcoin size={14} className="mr-1" /> Crypto
                      </Button>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        )}
      </div>

      {!token && (
        <div className="fixed bottom-0 left-0 right-0 bg-white border-t p-4 shadow-lg">
          <div className="max-w-md mx-auto">
            {otpStage !== 'code-sent' ? (
              <div className="flex gap-2">
                <Input placeholder="Your mobile number" value={phone} onChange={e => setPhone(e.target.value)}
                       data-testid="guest-phone-input" />
                <Button onClick={requestCode} disabled={busy} data-testid="guest-send-code-btn">Verify</Button>
              </div>
            ) : (
              <div className="flex gap-2">
                <Input placeholder="6-digit code" value={otpCode} onChange={e => setOtpCode(e.target.value)}
                       data-testid="guest-otp-input" />
                <Button onClick={verifyCode} disabled={busy} data-testid="guest-verify-otp-btn">Confirm</Button>
                <Button variant="ghost" size="icon" onClick={() => setOtpStage(null)}><X size={16} /></Button>
              </div>
            )}
            <p className="text-[11px] text-gray-400 mt-1.5">Verify your number to claim items and pay your share.</p>
          </div>
        </div>
      )}
    </div>
  );
}
