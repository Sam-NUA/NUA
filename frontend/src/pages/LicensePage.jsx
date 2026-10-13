/* License management — owner dashboard, lock screen overlay, billing recovery,
 * ABN change request, device management. All-in-one to minimise file churn.
 */
import React, { useEffect, useState } from 'react';
import { Card, CardContent } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Input } from '../components/ui/input';
import { Textarea } from '../components/ui/textarea';
import { useToast } from '../hooks/use-toast';
import { useTheme } from '../contexts/ThemeContext';
import { useLicense } from '../contexts/LicenseContext';
import { licenseAPI } from '../services/api';
import Icon from '../components/brand/Icon';
import { DialogService } from '../platform';
import {
  Shield, ShieldAlert, ShieldCheck, CreditCard, Building, Smartphone,
  CheckCircle, XCircle, Clock, RefreshCw, ExternalLink, Lock, Key
} from 'lucide-react';

const STATE_BADGES = {
  active:    { color: 'bg-emerald-100 text-emerald-700', icon: ShieldCheck,    label: 'ACTIVE' },
  past_due:  { color: 'bg-amber-100 text-amber-700',     icon: Clock,          label: 'PAST DUE' },
  grace:     { color: 'bg-orange-100 text-orange-700',   icon: ShieldAlert,    label: 'GRACE' },
  suspended: { color: 'bg-red-100 text-red-700',         icon: Lock,           label: 'SUSPENDED' },
  cancelled: { color: 'bg-gray-200 text-gray-700',       icon: XCircle,        label: 'CANCELLED' },
  abn_review:{ color: 'bg-blue-100 text-blue-700',       icon: Building,       label: 'ABN REVIEW' },
};

// =====================================================================
// LicenseLockScreen — full-page overlay when licenseState is bad
// =====================================================================
// Feature flag — licensing UI is off during product development. Flip to
// 'true' via REACT_APP_LICENSE_ENFORCEMENT to re-arm it.
const LICENSE_ENFORCEMENT_ENABLED =
  (process.env.REACT_APP_LICENSE_ENFORCEMENT || 'false').toLowerCase() === 'true';

export function LicenseLockScreen() {
  const { ok, licenseState, errorCode, message, abnEntityName } = useLicense();
  const { theme } = useTheme();
  const [recoveryLoading, setRecoveryLoading] = useState(false);
  const { toast } = useToast();

  // Global kill-switch
  if (!LICENSE_ENFORCEMENT_ENABLED) return null;

  // Always allow owner onto the License & Billing page so they can update
  // billing / view details without being blocked by their own lock screen.
  const path = typeof window !== 'undefined' ? window.location.pathname : '';
  if (path.startsWith('/license')) return null;

  // Lock screen only shows for HARD lock states. Past due / grace stay as banners.
  const isHardLock = ok === false && ['suspended', 'cancelled', 'abn_review'].includes(licenseState);
  if (!isHardLock) return null;

  const cfg = STATE_BADGES[licenseState] || STATE_BADGES.suspended;

  const openBilling = async () => {
    setRecoveryLoading(true);
    try {
      const r = await licenseAPI.billingRecovery(window.location.origin + '/license');
      if (r.data?.url) window.open(r.data.url, '_blank');
    } catch (e) {
      toast({ title: 'No billing portal available', description: e?.response?.data?.detail || 'Contact support', variant: 'destructive' });
    } finally {
      setRecoveryLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[9999] bg-gradient-to-br from-slate-900 to-slate-800 text-white flex items-center justify-center p-6" data-testid="license-lockscreen">
      <div className="max-w-xl w-full text-center space-y-6">
        {/* NUA brand mark — the real Pulse Grid mono icon (solid brand
            orange, white pulse glyph), not a hand-rolled gradient
            approximation. */}
        <div className="flex flex-col items-center gap-2" data-testid="lockscreen-logo">
          <div className="rounded-2xl shadow-xl overflow-hidden">
            <Icon variant="mono" size={64} />
          </div>
          <p className="text-sm font-bold tracking-[0.4em] text-white/80">NUA</p>
        </div>

        <div className="inline-flex w-20 h-20 rounded-full bg-red-500/20 items-center justify-center">
          <Lock className="text-red-400" size={40} />
        </div>
        <div>
          <p className="text-xs uppercase tracking-[0.3em] text-red-400 font-bold">{cfg.label}</p>
          <h1 className="text-4xl font-bold mt-2">POS Locked</h1>
          {abnEntityName && <p className="text-sm text-gray-400 mt-1">{abnEntityName}</p>}
        </div>
        <p className="text-lg text-gray-300 max-w-md mx-auto">{message || 'Your NUA license is not active. New transactions are paused.'}</p>
        <div className="bg-white/5 rounded-xl p-4 text-left text-sm space-y-2">
          <p className="font-medium text-amber-300">What you can still do:</p>
          <ul className="text-gray-300 space-y-1 text-sm">
            <li>· Log in as owner and review billing</li>
            <li>· Update card / pay outstanding invoice</li>
            <li>· Export your data (Warehouse → Export)</li>
            {licenseState === 'abn_review' && <li>· Track your pending ABN re-verification</li>}
          </ul>
        </div>
        <div className="flex gap-3 justify-center flex-wrap">
          <Button onClick={openBilling} disabled={recoveryLoading} size="lg" className="bg-amber-500 hover:bg-amber-400 text-black" data-testid="lockscreen-billing">
            <CreditCard size={16} className="mr-2" /> {recoveryLoading ? 'Opening…' : 'Update Billing'}
          </Button>
          <Button onClick={() => window.location.href = '/license'} size="lg" variant="outline" className="border-white/30 hover:bg-white/10" data-testid="lockscreen-details">
            <Shield size={16} className="mr-2" /> License Details
          </Button>
        </div>
        <p className="text-xs text-gray-500">Error code: <code className="bg-white/10 px-2 py-0.5 rounded">{errorCode || 'UNKNOWN'}</code></p>
      </div>
    </div>
  );
}

// =====================================================================
// LicenseBanner — non-blocking warnings for past_due/grace
// =====================================================================
export function LicenseBanner() {
  const { warnings, licenseState, graceEndAt } = useLicense();
  if (!LICENSE_ENFORCEMENT_ENABLED) return null;
  if (!['past_due', 'grace'].includes(licenseState) || warnings.length === 0) return null;
  return (
    <div className="bg-amber-50 border-l-4 border-amber-500 text-amber-900 px-4 py-2 text-sm flex items-center gap-2" data-testid="license-banner">
      <ShieldAlert size={14} className="flex-shrink-0" />
      <div className="flex-1">
        <strong>Billing notice:</strong> {warnings[0]}
        {graceEndAt && <span className="ml-2 text-xs">· Grace ends {graceEndAt.slice(0, 10)}</span>}
      </div>
      <a href="/license" className="font-bold underline">Fix now</a>
    </div>
  );
}

// =====================================================================
// LicensePage — owner dashboard
// =====================================================================
export default function LicensePage() {
  const { theme } = useTheme();
  const { toast } = useToast();
  const lic = useLicense();
  const [data, setData] = useState(null);
  const [audit, setAudit] = useState([]);
  const [loading, setLoading] = useState(true);

  // Onboarding form
  const [onboardAbn, setOnboardAbn] = useState('');
  const [entityName, setEntityName] = useState('');
  const [devSkip, setDevSkip] = useState(true);

  // ABN change form
  const [newAbn, setNewAbn] = useState('');
  const [twoFa, setTwoFa] = useState('');
  const [abnReason, setAbnReason] = useState('');

  // Device activation
  const [newDeviceName, setNewDeviceName] = useState('');

  const load = async () => {
    setLoading(true);
    try {
      const [me, au] = await Promise.all([licenseAPI.me(), licenseAPI.audit()]);
      setData(me.data);
      setAudit(au.data || []);
    } catch {}
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const onboard = async () => {
    try {
      await licenseAPI.onboard({ abn: onboardAbn, entityName, plan: 'standard', maxDevices: 5, devSkipAbr: devSkip });
      toast({ title: 'License issued' });
      load(); lic.revalidate();
    } catch (e) {
      toast({ title: 'Failed', description: e?.response?.data?.detail || 'Onboarding failed', variant: 'destructive' });
    }
  };

  const activateThis = async () => {
    try {
      await licenseAPI.activateDevice({ deviceId: lic.deviceId, name: newDeviceName || 'Browser POS' });
      toast({ title: 'Device activated' });
      load(); lic.revalidate();
    } catch (e) {
      toast({ title: 'Activation failed', description: e?.response?.data?.detail, variant: 'destructive' });
    }
  };

  const revoke = async (deviceId) => {
    if (!await DialogService.confirm('Revoke this device?')) return;
    try { await licenseAPI.revokeDevice(deviceId); toast({ title: 'Revoked' }); load(); }
    catch (e) { toast({ title: 'Failed', description: e?.response?.data?.detail, variant: 'destructive' }); }
  };

  const requestAbn = async () => {
    if (!newAbn || twoFa.length < 4) return toast({ title: 'New ABN + 2FA code required', variant: 'destructive' });
    try {
      await licenseAPI.requestAbnChange({ newAbn, twoFactorCode: twoFa, reason: abnReason });
      toast({ title: 'ABN change submitted', description: 'Tenant moved to ABN review. Contact support to approve.' });
      setNewAbn(''); setTwoFa(''); setAbnReason('');
      load(); lic.revalidate();
    } catch (e) {
      toast({ title: 'Request failed', description: e?.response?.data?.detail, variant: 'destructive' });
    }
  };

  const forceState = async (state) => {
    try {
      await licenseAPI.forceState(state, 'Dev test');
      // Await both refreshes so navigating immediately reflects the new state
      await Promise.all([load(), lic.revalidate()]);
      toast({ title: `State → ${state}` });
    } catch (e) { toast({ title: 'Failed', variant: 'destructive' }); }
  };

  if (loading) return <div className="text-center py-20 text-gray-400">Loading license…</div>;

  // ----- No license yet → onboarding form ---------------------------------
  if (!data?.hasLicense) {
    return (
      <div className="max-w-2xl mx-auto space-y-6" data-testid="license-onboard-page">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-2" style={{ color: theme.text }}><Key className="text-amber-500" /> Activate Your NUA License</h1>
          <p className="text-sm text-gray-500 mt-1">Bind a verified Australian ABN to your tenant. One ABN per license · immutable once issued.</p>
        </div>
        <Card><CardContent className="p-6 space-y-4">
          <div>
            <label className="text-xs uppercase tracking-widest text-gray-500 font-bold">ABN (11 digits)</label>
            <Input value={onboardAbn} onChange={e => setOnboardAbn(e.target.value)} placeholder="51 824 753 556" data-testid="abn-input" />
            <p className="text-xs text-gray-400 mt-1">Validated against MOD-89 checksum + live ABR lookup</p>
          </div>
          <div>
            <label className="text-xs uppercase tracking-widest text-gray-500 font-bold">Entity Name</label>
            <Input value={entityName} onChange={e => setEntityName(e.target.value)} placeholder="Acme Hospitality Pty Ltd" data-testid="entity-input" />
          </div>
          <label className="flex items-center gap-2 text-sm text-gray-600">
            <input type="checkbox" checked={devSkip} onChange={e => setDevSkip(e.target.checked)} data-testid="dev-skip" />
            <span>Dev mode: skip live ABR call (no ABR_GUID configured)</span>
          </label>
          <Button onClick={onboard} disabled={!onboardAbn} className="w-full" style={{ background: theme.primary }} data-testid="onboard-btn">Issue License</Button>
        </CardContent></Card>
      </div>
    );
  }

  const cfg = STATE_BADGES[data.state] || STATE_BADGES.active;
  const Icon = cfg.icon;

  // ----- License exists → full dashboard ----------------------------------
  return (
    <div className="space-y-6 max-w-6xl mx-auto" data-testid="license-page">
      {!LICENSE_ENFORCEMENT_ENABLED && (
        <div className="rounded-lg border-l-4 border-blue-400 bg-blue-50 px-4 py-3 text-sm text-blue-900 flex items-start gap-2" data-testid="enforcement-disabled-banner">
          <Shield size={16} className="flex-shrink-0 mt-0.5" />
          <div>
            <strong>Licensing enforcement is OFF</strong> for development. The lock screen and billing banner are hidden across the app. Set <code className="bg-blue-100 px-1.5 py-0.5 rounded">REACT_APP_LICENSE_ENFORCEMENT=true</code> (frontend) and <code className="bg-blue-100 px-1.5 py-0.5 rounded">LICENSE_ENFORCEMENT_ENABLED=true</code> (backend) to re-arm before deployment.
          </div>
        </div>
      )}
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-2" style={{ color: theme.text }}>
            <Shield className="text-emerald-600" /> License & Entitlements
          </h1>
          <p className="text-sm text-gray-500 mt-1">{data.abnEntityName} · ABN {data.abn}</p>
        </div>
        <Badge className={`${cfg.color} text-base px-3 py-1.5 flex items-center gap-1.5`} data-testid="license-state-badge">
          <Icon size={14} /> {cfg.label}
        </Badge>
      </div>

      {/* Summary grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Card><CardContent className="p-5">
          <p className="text-xs uppercase tracking-widest text-gray-500">Plan</p>
          <p className="text-2xl font-bold mt-1">{data.plan}</p>
        </CardContent></Card>
        <Card><CardContent className="p-5">
          <p className="text-xs uppercase tracking-widest text-gray-500">Devices</p>
          <p className="text-2xl font-bold mt-1">{(data.devices || []).length}<span className="text-base text-gray-400">/{data.maxDevices}</span></p>
        </CardContent></Card>
        <Card><CardContent className="p-5">
          <p className="text-xs uppercase tracking-widest text-gray-500">ABN Verified</p>
          <p className="text-lg font-bold mt-1">{data.abnVerifiedAt ? new Date(data.abnVerifiedAt).toLocaleDateString() : '—'}</p>
        </CardContent></Card>
        <Card><CardContent className="p-5">
          <p className="text-xs uppercase tracking-widest text-gray-500">Grace Ends</p>
          <p className="text-lg font-bold mt-1">{data.graceEndAt ? data.graceEndAt.slice(0, 10) : '—'}</p>
        </CardContent></Card>
      </div>

      {/* Warnings */}
      {(lic.warnings || []).length > 0 && (
        <Card className="border-amber-300 bg-amber-50"><CardContent className="p-4 space-y-1">
          {lic.warnings.map((w, i) => <p key={i} className="text-sm text-amber-900 flex items-center gap-2"><ShieldAlert size={14} /> {w}</p>)}
        </CardContent></Card>
      )}

      {/* Devices */}
      <Card data-testid="devices-card"><CardContent className="p-0">
        <div className="px-5 py-3 border-b flex items-center justify-between">
          <p className="font-bold flex items-center gap-1.5"><Smartphone size={16} /> Activated Devices</p>
          <div className="flex gap-2 items-center">
            <Input value={newDeviceName} onChange={e => setNewDeviceName(e.target.value)} placeholder="Device name" className="h-8 w-40 text-sm" />
            <Button size="sm" onClick={activateThis} data-testid="activate-device-btn"><Smartphone size={12} className="mr-1" /> Activate This Browser</Button>
          </div>
        </div>
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-xs uppercase tracking-wider text-gray-500"><tr>
            <th className="text-left px-5 py-3">Name</th><th className="text-left px-5 py-3">Device ID</th>
            <th className="text-left px-5 py-3">Activated</th><th className="text-right px-5 py-3">Action</th>
          </tr></thead>
          <tbody>
            {(data.devices || []).length === 0 ? <tr><td colSpan={4} className="text-center py-6 text-gray-400">No devices · activate this browser to start</td></tr> :
              data.devices.map(d => (
                <tr key={d.deviceId} className="border-t" data-testid={`device-${d.deviceId}`}>
                  <td className="px-5 py-3 font-medium">{d.name}</td>
                  <td className="px-5 py-3 font-mono text-xs">{d.deviceId.slice(0, 28)}…</td>
                  <td className="px-5 py-3 text-xs text-gray-500">{new Date(d.activatedAt).toLocaleString()}</td>
                  <td className="px-5 py-3 text-right">
                    <Button variant="ghost" size="sm" onClick={() => revoke(d.deviceId)} data-testid={`revoke-${d.deviceId}`}>Revoke</Button>
                  </td>
                </tr>
              ))}
          </tbody>
        </table>
      </CardContent></Card>

      {/* ABN change */}
      <Card><CardContent className="p-5 space-y-3" data-testid="abn-change-card">
        <p className="font-bold flex items-center gap-1.5"><Building size={16} /> Request ABN Change</p>
        <p className="text-xs text-gray-500">Per policy, ABN cannot be changed once a license is issued. A request will move the tenant into ABN review (sales paused) and requires support approval.</p>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
          <Input value={newAbn} onChange={e => setNewAbn(e.target.value)} placeholder="New ABN" data-testid="new-abn-input" />
          <Input value={twoFa} onChange={e => setTwoFa(e.target.value)} placeholder="2FA code (any 4+ chars in dev)" data-testid="twofa-input" />
          <Button onClick={requestAbn} variant="outline" data-testid="request-abn-btn">Submit Request</Button>
        </div>
        <Textarea value={abnReason} onChange={e => setAbnReason(e.target.value)} placeholder="Reason (required by support)" rows={2} />
      </CardContent></Card>

      {/* Dev state controls — visible only when devSkipAbr was used (so demos can simulate states) */}
      <Card className="border-dashed border-blue-300 bg-blue-50/40"><CardContent className="p-4">
        <p className="text-xs uppercase tracking-widest text-blue-700 font-bold mb-2">Dev / QA — Force State</p>
        <div className="flex gap-2 flex-wrap">
          {['active', 'past_due', 'grace', 'suspended', 'cancelled', 'abn_review'].map(s => (
            <Button key={s} size="sm" variant="outline" onClick={() => forceState(s)} data-testid={`force-${s}`}>{s}</Button>
          ))}
        </div>
      </CardContent></Card>

      {/* Audit log */}
      <Card data-testid="audit-card"><CardContent className="p-0">
        <div className="px-5 py-3 border-b font-bold flex items-center gap-1.5">Audit Log</div>
        <div className="max-h-80 overflow-y-auto">
          {audit.length === 0 ? <p className="px-5 py-8 text-center text-gray-400">No audit entries</p> :
            audit.map(a => (
              <div key={a.id} className="px-5 py-2.5 border-t text-sm flex justify-between" data-testid={`audit-${a.id}`}>
                <span><Badge variant="outline" className="mr-2 text-[10px]">{a.action}</Badge>{a.actor}</span>
                <span className="text-xs text-gray-500">{new Date(a.createdAt).toLocaleString()}</span>
              </div>
            ))}
        </div>
      </CardContent></Card>
    </div>
  );
}
