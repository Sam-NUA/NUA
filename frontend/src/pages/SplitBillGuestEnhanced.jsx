import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import { Receipt, Check, Users, Loader2, Bitcoin, CreditCard, X, Settings, AlertCircle } from 'lucide-react';
import { Button } from '../components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Input } from '../components/ui/input';
import { billSplitAPI, guestSessionAPI } from '../services/api';
import { toast } from 'sonner';
import { useSplitWebSocket } from '../hooks/useSplitWebSocket';
import { LiveStatus } from '../components/split/LiveStatus';
import { GroupInvite } from '../components/split/GroupInvite';
import { AccessibilityPanel } from '../components/split/AccessibilityPanel';
import { t } from '../lib/i18n';

const TOKEN_KEY = 'nua_guest_token';
const PHONE_KEY = 'nua_guest_phone';
const EMAIL_KEY = 'nua_guest_email';
const mineKey = (splitId) => `nua_guest_mine_${splitId}`;
const TIP_PRESETS = [0, 10, 15, 20];

function money(n) { return `$${(n || 0).toFixed(2)}`; }
function round2(n) { return Math.round((n + Number.EPSILON) * 100) / 100; }

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

export default function SplitBillGuestEnhanced() {
  const { tableNumber: tableFromPath } = useParams();
  const [searchParams] = useSearchParams();
  const splitParam = searchParams.get('split');
  const inviteCodeParam = searchParams.get('inviteCode');

  const [split, setSplit] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [mine, setMine] = useState({ lines: new Set(), slots: new Set() });
  const [selected, setSelected] = useState([]);
  const [equalCount, setEqualCount] = useState(4);
  const [phone, setPhone] = useState(sessionStorage.getItem(PHONE_KEY) || '');
  const [token, setToken] = useState(sessionStorage.getItem(TOKEN_KEY) || '');
  const [otpStage, setOtpStage] = useState(null);
  const [otpCode, setOtpCode] = useState('');
  const [busy, setBusy] = useState(false);
  const pollRef = useRef(null);
  const [claimedByOthers, setClaimedByOthers] = useState([]);
  const [showAccessibility, setShowAccessibility] = useState(false);
  const [group, setGroup] = useState(null);
  const [isOrganizer, setIsOrganizer] = useState(false);
  const [showPartialPayment, setShowPartialPayment] = useState(false);
  const [partialAmount, setPartialAmount] = useState('');
  const [showCustomSetup, setShowCustomSetup] = useState(false);
  const [customRows, setCustomRows] = useState(['', '']);
  const [email, setEmail] = useState(sessionStorage.getItem(EMAIL_KEY) || '');
  const [tipPercent, setTipPercent] = useState(0);
  const [customTip, setCustomTip] = useState('');

  // WebSocket for real-time updates
  const { connected, error: wsError, requestSync } = useSplitWebSocket(
    split?.id,
    (data) => {
      if (data.type === 'split_updated' && data.data) {
        setSplit(data.data);
        setMine(loadMine(data.data.id));
      } else if (data.type === 'item_claimed') {
        setClaimedByOthers(prev => [...prev, data.data]);
        requestSync();
      } else if (data.type === 'payment_received') {
        requestSync();
      }
    }
  );

  const load = useCallback(async () => {
    try {
      const res = splitParam
        ? await billSplitAPI.status(splitParam)
        : await billSplitAPI.getSplit(tableFromPath, new URLSearchParams(window.location.search).get("business"));
      setSplit(res.data);
      setMine(loadMine(res.data.id));

      // Load group info if exists
      if (res.data.groupMode) {
        try {
          const groupRes = await fetch(`/api/table/split/${res.data.id}/group/status`);
          const groupData = await groupRes.json();
          setGroup(groupData);
          setIsOrganizer(groupData.organizerPhone === phone);
        } catch (e) {
          console.warn('Failed to load group info');
        }
      }

      setError(null);
    } catch (e) {
      setError(e?.response?.data?.detail || t('split.errors.loadFailed', 'Couldn\'t load bill'));
    } finally {
      setLoading(false);
    }
  }, [tableFromPath, splitParam, phone]);

  useEffect(() => {
    load();
    pollRef.current = setInterval(load, 4000);
    return () => clearInterval(pollRef.current);
  }, [load]);

  // Handle invite code in URL
  useEffect(() => {
    if (inviteCodeParam && phone && split?.id) {
      const acceptInvite = async () => {
        try {
          const res = await fetch(`/api/table/split/${split.id}/group/accept-invite`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'Authorization': `Bearer ${token}`,
            },
            body: JSON.stringify({ inviteToken: inviteCodeParam }),
          });
          if (res.ok) {
            toast.success('Joined group!');
            load();
          }
        } catch (e) {
          console.warn('Failed to accept invite');
        }
      };
      acceptInvite();
    }
  }, [inviteCodeParam, phone, split?.id, token, load]);

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
    if (!phone.trim()) {
      toast.error(t('split.errors.phoneRequired'));
      return;
    }
    setBusy(true);
    try {
      await guestSessionAPI.requestCode(phone.trim());
      setOtpStage('code-sent');
      toast.success(t('split.messages.codeSent', { phone }));
    } catch {
      toast.error(t('split.messages.sendCodeFailed', 'Could not send a code'));
    } finally {
      setBusy(false);
    }
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
      toast.success(t('split.messages.verified', 'Phone verified!'));
    } catch (e) {
      toast.error(e?.response?.data?.detail || t('split.errors.invalidCode'));
    } finally {
      setBusy(false);
    }
  };

  const chooseMode = async (mode) => {
    const table = split?.tableNumber || tableFromPath;
    setBusy(true);
    try {
      const r = await billSplitAPI.chooseMode(table, mode, equalCount, { business: new URLSearchParams(window.location.search).get("business") });
      setSplit(r.data);
    } catch (e) {
      toast.error(e?.response?.data?.detail || t('split.errors.setModeFailed'));
    } finally {
      setBusy(false);
    }
  };

  const addCustomRow = () => setCustomRows(prev => [...prev, '']);
  const removeCustomRow = (i) => setCustomRows(prev => prev.filter((_, idx) => idx !== i));
  const updateCustomRow = (i, val) => setCustomRows(prev => prev.map((v, idx) => (idx === i ? val : v)));
  const billTotal = split?.lines?.reduce((sum, l) => sum + (l.unitPrice || 0), 0) || 0;
  const customRowsTotal = round2(customRows.reduce((sum, v) => sum + (parseFloat(v) || 0), 0));

  const submitCustomSplit = async () => {
    const table = split?.tableNumber || tableFromPath;
    const amounts = customRows.map(v => parseFloat(v) || 0);
    if (amounts.length < 2 || amounts.some(a => a <= 0)) {
      toast.error('Enter an amount greater than $0 for each share');
      return;
    }
    setBusy(true);
    try {
      const r = await billSplitAPI.chooseMode(table, 'custom', null, { customAmounts: amounts, business: new URLSearchParams(window.location.search).get("business") });
      setSplit(r.data);
      setShowCustomSetup(false);
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Could not set up the custom split');
    } finally {
      setBusy(false);
    }
  };

  const claimEqualSlot = async (index) => {
    if (!token) {
      toast.error(t('split.errors.verifyFirst'));
      return;
    }
    setBusy(true);
    try {
      const r = await billSplitAPI.claimEqual(split.id, index, token);
      setSplit(r.data);
      rememberMine({ slots: [index] });
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'That share was just taken');
    } finally {
      setBusy(false);
    }
  };

  const tipFor = (baseAmount) => {
    if (tipPercent === 'custom') return round2(parseFloat(customTip) || 0);
    return round2((baseAmount || 0) * (tipPercent / 100));
  };

  const pay = async (provider, lineIds, slotIndex, baseAmount) => {
    if (!token) {
      toast.error(t('split.errors.verifyFirst'));
      return;
    }
    setBusy(true);
    try {
      if (email.trim()) sessionStorage.setItem(EMAIL_KEY, email.trim());
      const r = await billSplitAPI.checkout(split.id, {
        provider, lineIds, slotIndex, originUrl: window.location.origin,
        tipAmount: tipFor(baseAmount), email: email.trim() || undefined,
      }, token);
      window.location.href = r.data.url;
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Could not start checkout');
      setBusy(false);
    }
  };

  const toggleLine = (line) => {
    if (line.status !== 'open') return;
    setSelected(prev =>
      prev.includes(line.id) ? prev.filter(id => id !== line.id) : [...prev, line.id]
    );
  };

  const claimSelected = async () => {
    if (!token) {
      toast.error(t('split.errors.verifyFirst'));
      return;
    }
    if (!selected.length) return;
    setBusy(true);
    try {
      const r = await billSplitAPI.claim(split.id, selected, token);
      setSplit(r.data.split);
      if (r.data.failed.length) {
        toast.error(t('split.messages.someItemsTaken'));
      }
      rememberMine({ lines: r.data.claimed });
      setSelected([]);
    } catch (e) {
      toast.error(e?.response?.data?.detail || t('split.errors.claimFailed'));
    } finally {
      setBusy(false);
    }
  };

  const handlePartialPayment = async () => {
    if (!token) {
      toast.error(t('split.errors.verifyFirst'));
      return;
    }
    if (!partialAmount || parseFloat(partialAmount) <= 0) {
      toast.error(t('split.errors.amountRequired'));
      return;
    }

    setBusy(true);
    try {
      const response = await fetch(`/api/table/split/${split.id}/partial-checkout`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        body: JSON.stringify({
          amount: parseFloat(partialAmount),
          lineIds: myClaimedLines.map(l => l.id),
          totalAmount: myAmount,
        }),
      });

      if (response.ok) {
        toast.success(t('split.tab.tabCreated'));
        setShowPartialPayment(false);
        setPartialAmount('');
        load();
      }
    } catch (e) {
      toast.error('Failed to create tab');
    } finally {
      setBusy(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <Loader2 className="animate-spin" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-4 max-w-md mx-auto text-center">
        <AlertCircle size={32} className="mx-auto text-red-500 mb-2" />
        <p className="text-red-700 font-medium">{error}</p>
      </div>
    );
  }

  const myLines = split?.lines.filter(l => mine.lines.has(l.id)) || [];
  const myClaimedLines = myLines.filter(l => l.status === 'claimed');
  const myClaimedSlots = (split?.equalParts || []).filter(p => mine.slots.has(p.index) && p.status === 'claimed');
  const myAmount = myClaimedLines.reduce((sum, l) => sum + (l.unitPrice || 0), 0)
    + myClaimedSlots.reduce((sum, p) => sum + (p.amount || 0), 0);
  const isSlotMode = split?.mode === 'equal' || split?.mode === 'custom';

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-50 to-gray-100 p-4">
      {/* Accessibility Button */}
      <div className="fixed top-4 right-4 z-40">
        <Button
          variant="outline"
          size="sm"
          onClick={() => setShowAccessibility(!showAccessibility)}
          className="gap-1"
          aria-label="Accessibility settings"
        >
          <Settings size={16} />
          <span className="sr-only">Settings</span>
        </Button>
      </div>

      {/* Accessibility Panel */}
      {showAccessibility && (
        <AccessibilityPanel onClose={() => setShowAccessibility(false)} />
      )}

      <div className="max-w-2xl mx-auto space-y-4">
        {/* Header */}
        <div className="text-center">
          <h1 className="text-2xl font-bold text-gray-900">
            {t('split.title')}
          </h1>
          <p className="text-gray-600">{t('split.subtitle')}</p>
        </div>

        {/* Connection Status */}
        {wsError && !connected && (
          <div className="p-3 bg-amber-50 border border-amber-200 rounded text-sm text-amber-800">
            {wsError}
          </div>
        )}

        {/* Live Status */}
        {split?.id && (
          <LiveStatus split={split} connected={connected} claimedByOthers={claimedByOthers} />
        )}

        {/* Split Mode Selection */}
        {!split?.mode && !showCustomSetup && (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">{t('split.mode')}</CardTitle>
            </CardHeader>
            <CardContent className="grid grid-cols-3 gap-2">
              <Button
                variant="outline"
                onClick={() => chooseMode('items')}
                disabled={busy}
                className="flex flex-col items-center gap-1 h-auto py-3"
              >
                <Receipt size={20} />
                {t('split.items')}
              </Button>
              <Button
                variant="outline"
                onClick={() => chooseMode('equal')}
                disabled={busy}
                className="flex flex-col items-center gap-1 h-auto py-3"
              >
                <Users size={20} />
                {t('split.equal')}
              </Button>
              <Button
                variant="outline"
                onClick={() => setShowCustomSetup(true)}
                disabled={busy}
                className="flex flex-col items-center gap-1 h-auto py-3"
              >
                <Users size={20} />
                {t('split.custom')}
              </Button>
            </CardContent>
          </Card>
        )}

        {/* Custom Split Setup — uneven shares (e.g. "I only had a drink") */}
        {!split?.mode && showCustomSetup && (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">{t('split.customSplit.setupTitle')}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <p className="text-xs text-gray-500">
                {t('split.customSplit.billTotal', { amount: money(billTotal) })}
              </p>
              {customRows.map((val, i) => (
                <div key={i} className="flex items-center gap-2">
                  <span className="text-xs text-gray-500 w-14">
                    {t('split.customSplit.person', { number: i + 1 })}
                  </span>
                  <Input
                    type="number"
                    min="0"
                    step="0.01"
                    placeholder="0.00"
                    value={val}
                    onChange={(e) => updateCustomRow(i, e.target.value)}
                    disabled={busy}
                  />
                  {customRows.length > 2 && (
                    <Button variant="ghost" size="sm" onClick={() => removeCustomRow(i)} disabled={busy}>
                      <X size={14} />
                    </Button>
                  )}
                </div>
              ))}
              <div className="flex items-center justify-between text-sm">
                <Button variant="outline" size="sm" onClick={addCustomRow} disabled={busy || customRows.length >= 20}>
                  {t('split.customSplit.addPerson')}
                </Button>
                <span className={Math.abs(customRowsTotal - billTotal) < 0.01 ? 'text-green-600' : 'text-amber-600'}>
                  {money(customRowsTotal)} / {money(billTotal)}
                </span>
              </div>
              <div className="grid grid-cols-2 gap-2 pt-2">
                <Button variant="outline" onClick={() => setShowCustomSetup(false)} disabled={busy}>
                  Cancel
                </Button>
                <Button onClick={submitCustomSplit} disabled={busy}>
                  {busy ? <Loader2 size={16} className="animate-spin" /> : t('split.customSplit.createShares')}
                </Button>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Items Grid */}
        {split?.mode === 'items' && (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">
                {t('split.selectItems')} ({selected.length})
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2 max-h-64 overflow-y-auto">
                {split?.lines?.map(line => (
                  <button
                    key={line.id}
                    onClick={() => toggleLine(line)}
                    disabled={line.status !== 'open'}
                    className={`p-3 rounded-lg border-2 text-left transition ${
                      line.status === 'paid'
                        ? 'bg-gray-100 border-gray-300 cursor-not-allowed opacity-50'
                        : line.status === 'claimed'
                        ? 'bg-yellow-50 border-yellow-300 cursor-not-allowed'
                        : selected.includes(line.id)
                        ? 'bg-blue-50 border-blue-400'
                        : 'bg-white border-gray-300 hover:border-blue-400'
                    }`}
                  >
                    <div className="flex justify-between items-start">
                      <div>
                        <p className="font-medium text-sm">{line.productName}</p>
                        <p className="text-xs text-gray-600">{line.category}</p>
                      </div>
                      <div className="text-right">
                        <p className="font-bold">{money(line.unitPrice)}</p>
                        <p className="text-xs text-gray-600">
                          {line.status === 'open' ? t('split.status.open') : line.status}
                        </p>
                      </div>
                    </div>
                  </button>
                ))}
              </div>

              {selected.length > 0 && (
                <div className="mt-4 pt-4 border-t">
                  <p className="text-sm text-gray-600 mb-2">
                    Your share: {money(selected.reduce((sum, id) => {
                      const line = split.lines.find(l => l.id === id);
                      return sum + (line?.unitPrice || 0);
                    }, 0))}
                  </p>
                  <Button
                    onClick={claimSelected}
                    disabled={busy || !token}
                    className="w-full gap-1"
                  >
                    {busy ? <Loader2 size={16} className="animate-spin" /> : <Check size={16} />}
                    {t('split.claim')}
                  </Button>
                </div>
              )}
            </CardContent>
          </Card>
        )}

        {/* Equal / Custom Share Grid — same claimable-slot shape either way */}
        {isSlotMode && (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">
                {split.mode === 'equal' ? t('split.equal') : t('split.custom')}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-2 gap-2">
                {split?.equalParts?.map(part => {
                  const isMineSlot = mine.slots.has(part.index) && part.status === 'claimed';
                  return (
                    <button
                      key={part.index}
                      disabled={part.status !== 'open' && !isMineSlot}
                      onClick={() => part.status === 'open' && claimEqualSlot(part.index)}
                      className={`p-3 rounded-lg border-2 text-center transition ${
                        part.status === 'paid'
                          ? 'bg-gray-100 border-gray-300 cursor-not-allowed opacity-50'
                          : isMineSlot
                          ? 'bg-blue-50 border-blue-400'
                          : part.status === 'claimed'
                          ? 'bg-yellow-50 border-yellow-300 cursor-not-allowed'
                          : 'bg-white border-gray-300 hover:border-blue-400'
                      }`}
                    >
                      <div className="font-bold">{money(part.amount)}</div>
                      <div className="text-xs text-gray-600 uppercase tracking-wide mt-0.5">
                        {part.status === 'paid' ? t('split.status.paid') : isMineSlot ? 'Yours'
                          : part.status === 'claimed' ? t('split.status.claimed') : t('split.status.open')}
                      </div>
                    </button>
                  );
                })}
              </div>
            </CardContent>
          </Card>
        )}

        {/* Phone Verification */}
        {!token && (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">{t('split.phone')}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {!otpStage ? (
                <>
                  <Input
                    type="tel"
                    placeholder={t('split.enterPhone')}
                    value={phone}
                    onChange={(e) => setPhone(e.target.value)}
                    disabled={busy}
                  />
                  <Button onClick={requestCode} disabled={busy} className="w-full">
                    {busy && <Loader2 size={16} className="animate-spin mr-2" />}
                    {t('split.sendCode')}
                  </Button>
                </>
              ) : (
                <>
                  <Input
                    type="text"
                    placeholder={t('split.enterCode')}
                    value={otpCode}
                    onChange={(e) => setOtpCode(e.target.value)}
                    disabled={busy}
                    maxLength="6"
                  />
                  <Button onClick={verifyCode} disabled={busy || !otpCode} className="w-full">
                    {busy && <Loader2 size={16} className="animate-spin mr-2" />}
                    {t('split.verify')}
                  </Button>
                </>
              )}
            </CardContent>
          </Card>
        )}

        {/* Group Coordination */}
        {split?.id && (
          <GroupInvite
            splitId={split.id}
            groupId={group?.id}
            isOrganizer={isOrganizer}
            participants={group?.participants || []}
          />
        )}

        {/* Tip + Receipt email — shown once anything is claimed and ready to pay */}
        {token && (myClaimedLines.length > 0 || myClaimedSlots.length > 0) && (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">{t('split.tip.title')}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="grid grid-cols-5 gap-2">
                {TIP_PRESETS.map(pct => (
                  <Button
                    key={pct}
                    size="sm"
                    variant={tipPercent === pct ? 'default' : 'outline'}
                    onClick={() => setTipPercent(pct)}
                  >
                    {pct}%
                  </Button>
                ))}
                <Button
                  size="sm"
                  variant={tipPercent === 'custom' ? 'default' : 'outline'}
                  onClick={() => setTipPercent('custom')}
                >
                  {t('split.tip.other')}
                </Button>
              </div>
              {tipPercent === 'custom' && (
                <Input
                  type="number"
                  min="0"
                  step="0.01"
                  placeholder={t('split.tip.amount')}
                  value={customTip}
                  onChange={(e) => setCustomTip(e.target.value)}
                />
              )}
              {tipFor(myAmount) > 0 && (
                <p className="text-xs text-gray-500">
                  {t('split.tip.summary', {
                    tip: money(tipFor(myAmount)),
                    total: money(round2(myAmount + tipFor(myAmount))),
                  })}
                </p>
              )}
              <Input
                type="email"
                placeholder={t('split.receipt.emailPlaceholder')}
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </CardContent>
          </Card>
        )}

        {/* Pay for claimed items (items mode) */}
        {token && myClaimedLines.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">
                {t('split.tab.title')} - {money(myAmount)}
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {!showPartialPayment ? (
                <div className="space-y-2">
                  <div className="grid grid-cols-2 gap-2">
                    <Button
                      className="gap-1"
                      disabled={busy}
                      onClick={() => pay('stripe', myClaimedLines.map(l => l.id), null, myAmount)}
                    >
                      <CreditCard size={16} /> Card
                    </Button>
                    <Button
                      className="gap-1"
                      variant="outline"
                      disabled={busy}
                      onClick={() => pay('crypto', myClaimedLines.map(l => l.id), null, myAmount)}
                    >
                      <Bitcoin size={16} /> Crypto
                    </Button>
                  </div>
                  <Button onClick={() => setShowPartialPayment(true)} variant="ghost" size="sm" className="w-full">
                    {t('split.tab.partial')}
                  </Button>
                </div>
              ) : (
                <div className="space-y-2">
                  <Input
                    type="number"
                    placeholder={t('split.tab.amountToPay')}
                    value={partialAmount}
                    onChange={(e) => setPartialAmount(e.target.value)}
                    min="0"
                    step="0.01"
                    max={myAmount}
                  />
                  <div className="text-sm text-gray-600">
                    {t('split.tab.remaining')}: {money(myAmount - (parseFloat(partialAmount) || 0))}
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    <Button
                      variant="outline"
                      onClick={() => setShowPartialPayment(false)}
                    >
                      Cancel
                    </Button>
                    <Button onClick={handlePartialPayment} disabled={busy}>
                      {t('split.tab.confirmTab', { amount: money(parseFloat(partialAmount) || 0) })}
                    </Button>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        )}

        {/* Pay for claimed shares (equal/custom mode) — one slot at a time,
            matching the backend's single-slot checkout */}
        {token && myClaimedSlots.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">{t('split.pay')}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {myClaimedSlots.map(slot => (
                <div key={slot.index} className="flex items-center gap-2">
                  <span className="text-sm font-mono flex-1">{money(slot.amount)}</span>
                  <Button
                    size="sm"
                    className="gap-1"
                    disabled={busy}
                    onClick={() => pay('stripe', [], slot.index, slot.amount)}
                  >
                    <CreditCard size={14} /> Card
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    className="gap-1"
                    disabled={busy}
                    onClick={() => pay('crypto', [], slot.index, slot.amount)}
                  >
                    <Bitcoin size={14} /> Crypto
                  </Button>
                </div>
              ))}
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
