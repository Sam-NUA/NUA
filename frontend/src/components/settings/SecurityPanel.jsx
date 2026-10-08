import AccountAccessPanel from './AccountAccessPanel';
import React, { useEffect, useState } from 'react';
import { Card, CardContent } from '../ui/card';
import { Button } from '../ui/button';
import { Input } from '../ui/input';
import { Badge } from '../ui/badge';
import { useTheme } from '../../contexts/ThemeContext';
import { useAuth } from '../../contexts/AuthContext';
import { twoFactorAPI } from '../../services/api';
import { toast } from 'sonner';
import { QRCodeSVG } from 'qrcode.react';
import { ShieldCheck, ShieldAlert, Smartphone, KeyRound, Trash2, Printer } from 'lucide-react';

/**
 * Two-factor, from the point of view of someone who runs a restaurant.
 *
 * The order of the screen is deliberate: scan, confirm, then the recovery
 * codes with a print button, because the codes are shown exactly once and the
 * realistic failure mode here is not an attacker — it's the owner's phone
 * dying on a Saturday with the safe full and nobody able to reach the till.
 */
export default function SecurityPanel() {
  const { theme } = useTheme();
  const { user } = useAuth();
  const [status, setStatus] = useState(null);
  const [setup, setSetup] = useState(null);     // { secret, otpauthUri }
  const [code, setCode] = useState('');
  const [codes, setCodes] = useState(null);      // plaintext, shown once
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [policy, setPolicy] = useState(null);

  const load = async () => {
    try { setStatus((await twoFactorAPI.status()).data); } catch { /* silent */ }
    if (user?.role === 'owner' || user?.role === 'manager') {
      try { setPolicy((await twoFactorAPI.getPolicy()).data); } catch { /* silent */ }
    }
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, []);

  const begin = async () => {
    setBusy(true);
    try { setSetup((await twoFactorAPI.setup()).data); }
    catch (e) { toast.error(e.response?.data?.detail || 'Could not start setup'); }
    setBusy(false);
  };

  const confirm = async () => {
    setBusy(true);
    try {
      const r = await twoFactorAPI.verify(code);
      setCodes(r.data.recoveryCodes);
      setSetup(null); setCode('');
      toast.success('Two-factor is on');
      load();
    } catch (e) { toast.error(e.response?.data?.detail || 'That code did not match'); }
    setBusy(false);
  };

  const turnOff = async () => {
    setBusy(true);
    try {
      await twoFactorAPI.disable(password);
      setPassword(''); toast.success('Two-factor turned off'); load();
    } catch (e) { toast.error(e.response?.data?.detail || 'Could not turn it off'); }
    setBusy(false);
  };

  const regen = async () => {
    setBusy(true);
    try {
      const r = await twoFactorAPI.regenerateCodes(password);
      setCodes(r.data.recoveryCodes); setPassword('');
      toast.success('New recovery codes — the old ones no longer work');
      load();
    } catch (e) { toast.error(e.response?.data?.detail || 'Could not generate codes'); }
    setBusy(false);
  };

  const revoke = async (id) => {
    try { await twoFactorAPI.revokeDevice(id); toast.success('Device will be asked for a code'); load(); }
    catch { toast.error('Could not revoke'); }
  };

  const savePolicy = async (required) => {
    try {
      await twoFactorAPI.setPolicy(required, policy?.roles);
      toast.success(required ? 'Owners and managers now need a second factor' : 'Requirement removed');
      load();
    } catch (e) { toast.error(e.response?.data?.detail || 'Could not save'); }
  };

  const printCodes = () => {
    const w = window.open('', '_blank', 'width=480,height=640');
    if (!w) return toast.error('Allow pop-ups to print your codes');
    w.document.write(
      `<pre style="font:14px/1.9 ui-monospace,monospace;padding:32px">` +
      `NUA POS — recovery codes\n${user?.email || ''}\n` +
      `${new Date().toLocaleString()}\n\n${(codes || []).join('\n')}\n\n` +
      `Each code works once. Keep this somewhere the safe key lives,\nnot next to the terminal.</pre>`);
    w.document.close(); w.print();
  };

  const card = { backgroundColor: theme.cardBg || theme.background, color: theme.text };
  const on = status?.enabled;

  return (
    <div className="space-y-4" data-testid="security-panel">
      <AccountAccessPanel />
      <Card style={card}>
        <CardContent className="p-6 space-y-4">
          <div className="flex items-start justify-between gap-4 flex-wrap">
            <div className="flex items-center gap-3">
              {on ? <ShieldCheck size={22} className="text-green-500" />
                  : <ShieldAlert size={22} className="text-amber-500" />}
              <div>
                <h3 className="font-bold text-lg">Two-factor sign-in</h3>
                <p className="text-sm opacity-70">
                  {on
                    ? `On since ${status.enabledAt ? new Date(status.enabledAt).toLocaleDateString() : '—'}`
                    : 'A password alone is all that stands between someone and your takings.'}
                </p>
              </div>
            </div>
            <Badge variant={on ? 'default' : 'secondary'} data-testid="twofactor-state">
              {on ? 'Active' : 'Not set up'}
            </Badge>
          </div>

          {status?.requiredForYou && !on && (
            <div className="text-sm rounded-lg p-3 bg-amber-500/10 text-amber-600 dark:text-amber-400">
              This venue requires a second factor for your role. Set it up now — you'll be asked
              for a code the next time you sign in on a terminal that isn't remembered.
            </div>
          )}

          {/* ── Enrol ── */}
          {!on && !setup && (
            <Button onClick={begin} disabled={busy} data-testid="twofactor-begin">
              Set up two-factor
            </Button>
          )}

          {setup && (
            <div className="space-y-4" data-testid="twofactor-setup">
              <p className="text-sm opacity-80">
                Scan this with Google Authenticator, 1Password, or any authenticator app.
              </p>
              <div className="inline-block p-4 bg-white rounded-lg">
                <QRCodeSVG value={setup.otpauthUri} size={168} />
              </div>
              <p className="text-xs opacity-60">
                Can't scan? Enter this key by hand:{' '}
                <code className="font-mono select-all">{setup.secret}</code>
              </p>
              <div className="flex gap-2 items-center flex-wrap">
                <Input value={code} onChange={e => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                  placeholder="6-digit code" inputMode="numeric"
                  className="w-40 text-center font-mono tracking-widest"
                  data-testid="twofactor-confirm-code" />
                <Button onClick={confirm} disabled={busy || code.length < 6}
                  data-testid="twofactor-confirm">Confirm</Button>
                <Button variant="ghost" onClick={() => { setSetup(null); setCode(''); }}>Cancel</Button>
              </div>
            </div>
          )}

          {/* ── Recovery codes, shown exactly once ── */}
          {codes && (
            <div className="rounded-lg p-4 border border-amber-500/40 bg-amber-500/5 space-y-3"
                 data-testid="recovery-codes">
              <div className="flex items-center gap-2 font-medium">
                <KeyRound size={16} /> Save these now — they are not shown again
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 font-mono text-sm">
                {codes.map(c => <div key={c} className="select-all">{c}</div>)}
              </div>
              <div className="flex gap-2">
                <Button size="sm" onClick={printCodes} data-testid="print-recovery">
                  <Printer size={14} className="mr-1" /> Print
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setCodes(null)}>I've saved them</Button>
              </div>
            </div>
          )}

          {/* ── Manage ── */}
          {on && !codes && (
            <div className="space-y-3 pt-2 border-t" style={{ borderColor: theme.border || '#e5e7eb' }}>
              <p className="text-sm opacity-70">
                {status.recoveryCodesRemaining} recovery code{status.recoveryCodesRemaining === 1 ? '' : 's'} left.
                {status.recoveryCodesRemaining <= 2 && ' Generate new ones before you run out.'}
              </p>
              <div className="flex gap-2 items-center flex-wrap">
                <Input type="password" value={password} onChange={e => setPassword(e.target.value)}
                  placeholder="Your password" className="w-56" data-testid="twofactor-password" />
                <Button size="sm" variant="outline" onClick={regen} disabled={busy || !password}
                  data-testid="twofactor-regen">New recovery codes</Button>
                <Button size="sm" variant="ghost" className="text-red-500" onClick={turnOff}
                  disabled={busy || !password} data-testid="twofactor-disable">Turn off</Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* ── Remembered terminals ── */}
      {on && (
        <Card style={card}>
          <CardContent className="p-6">
            <h3 className="font-bold mb-1 flex items-center gap-2"><Smartphone size={18} /> Remembered terminals</h3>
            <p className="text-sm opacity-70 mb-3">
              These skip the code at sign-in. Revoke one the moment a device leaves the venue.
            </p>
            {(status.devices || []).length === 0 && <p className="text-sm opacity-60">None yet.</p>}
            <div className="space-y-2">
              {(status.devices || []).map(d => (
                <div key={d.id} className="flex items-center justify-between gap-3 text-sm rounded-lg p-3"
                     style={{ backgroundColor: theme.background }}>
                  <div>
                    <div className="font-medium">{d.label}</div>
                    <div className="opacity-60 text-xs">
                      Last used {d.lastSeenAt ? new Date(d.lastSeenAt).toLocaleString() : '—'}
                    </div>
                  </div>
                  <Button size="sm" variant="ghost" className="text-red-500"
                    onClick={() => revoke(d.id)} data-testid={`revoke-${d.id}`}>
                    <Trash2 size={14} />
                  </Button>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* ── Venue policy (owner) ── */}
      {policy && user?.role === 'owner' && (
        <Card style={card}>
          <CardContent className="p-6 space-y-3">
            <h3 className="font-bold">Require it for owners and managers</h3>
            <p className="text-sm opacity-70">
              Cashier and kitchen logins are left alone on purpose — they happen constantly on shared
              hardware and can't reach the money screens anyway.
            </p>
            <label className="flex items-center gap-2 text-sm cursor-pointer">
              <input type="checkbox" checked={!!policy.required} className="w-4 h-4 accent-orange-500"
                onChange={e => savePolicy(e.target.checked)} data-testid="twofactor-policy" />
              Owners and managers must use two-factor
            </label>
            {(policy.staff || []).some(s => !s.twoFactorEnabled) && (
              <div className="text-sm rounded-lg p-3 bg-amber-500/10 text-amber-600 dark:text-amber-400">
                Not set up yet:{' '}
                {(policy.staff || []).filter(s => !s.twoFactorEnabled).map(s => s.name || s.email).join(', ')}
                . They'll be asked to enrol at their next sign-in.
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
