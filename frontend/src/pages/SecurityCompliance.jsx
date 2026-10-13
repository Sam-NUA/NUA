import React, { useState, useEffect } from 'react';
import { Shield, Globe, Lock, Download, AlertCircle } from 'lucide-react';
import { Card, CardContent } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Badge } from '../components/ui/badge';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '../components/ui/dialog';
import { useTheme } from '../contexts/ThemeContext';
import { useAuth } from '../contexts/AuthContext';
import { v15API, customersAPI } from '../services/api';
import { toast } from 'sonner';
import SensitiveActionReauthDialog from '../components/security/SensitiveActionReauthDialog';
import { FileService } from '../platform';

const LANGS = [{ c: 'en', n: 'English' }, { c: 'es', n: 'Español' }, { c: 'fr', n: 'Français' }, { c: 'hi', n: 'हिन्दी' }, { c: 'zh', n: '中文' }];

export default function SecurityCompliance() {
  const { theme, darkMode, toggleDarkMode, lang, setLang } = useTheme();
  const { user } = useAuth();
  const isOwner = user?.role === 'owner';
  const [setup, setSetup] = useState(null);
  const [code, setCode] = useState('');
  const [customers, setCustomers] = useState([]);
  const [exportData, setExportData] = useState(null);
  // Directive Phase 5 — disabling 2FA and erasing a customer's personal
  // data are both "sensitive settings": one weakens the owner's own
  // account security, the other is irreversible. A single reauth dialog
  // is reused for both, dispatching on `pendingReauth.run` once verified.
  const [pendingReauth, setPendingReauth] = useState(null); // { label, run } | null

  useEffect(() => { customersAPI.getAll().then(r => setCustomers(r.data || [])).catch(() => {}); }, []);

  const start2FA = async () => {
    try { const r = await v15API.setup2FA(); setSetup(r.data); }
    catch (e) { toast.error(e.response?.data?.detail || 'Failed'); }
  };
  const verify2FA = async () => {
    try { await v15API.verify2FA(code); toast.success('2FA enabled!'); setSetup(null); setCode(''); }
    catch (e) { toast.error(e.response?.data?.detail || 'Invalid code'); }
  };
  const disable2FA = () => setPendingReauth({
    label: 'disable two-factor authentication',
    run: async () => { try { await v15API.disable2FA(); toast('2FA disabled'); } catch {} },
  });

  const doExport = async (cid) => {
    try {
      const r = await v15API.gdprExport(cid);
      setExportData(r.data);
      // Trigger download
      const blob = new Blob([JSON.stringify(r.data, null, 2)], { type: 'application/json' });
      await FileService.downloadFile(blob, `gdpr-export-${cid}.json`);
      toast.success('GDPR export downloaded');
    } catch { toast.error('Export failed'); }
  };
  const doErase = (cid) => {
    if (!window.confirm('Anonymize this customer\'s personal data? Financial records will be preserved. This cannot be undone.')) return;
    setPendingReauth({
      label: 'anonymize this customer\'s personal data',
      run: async () => {
        try { await v15API.gdprErase(cid); toast.success('Customer anonymized'); customersAPI.getAll().then(r => setCustomers(r.data || [])); }
        catch (e) { toast.error(e.response?.data?.detail || 'Failed'); }
      },
    });
  };

  return (
    <div className="space-y-6" data-testid="security-page">
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2" style={{ color: theme.text }}><Shield size={22} /> Security & Compliance</h1>
        <p className="text-sm text-gray-500">2FA, dark mode, language, GDPR data tools.</p>
      </div>

      {/* Appearance & Locale */}
      <Card>
        <CardContent className="p-5 space-y-4">
          <h2 className="font-bold text-sm uppercase tracking-wider text-gray-500">Appearance & Locale</h2>
          <div className="flex items-center justify-between">
            <div><p className="font-medium text-sm">Dark Mode</p><p className="text-xs text-gray-500">Reduce eye strain at night</p></div>
            <button onClick={toggleDarkMode} className={`relative inline-flex h-6 w-11 items-center rounded-full transition ${darkMode ? 'bg-indigo-600' : 'bg-gray-300'}`} data-testid="dark-toggle">
              <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition ${darkMode ? 'translate-x-6' : 'translate-x-1'}`} />
            </button>
          </div>
          <div>
            <div className="flex items-center gap-2 mb-2"><Globe size={14} /><p className="font-medium text-sm">Cart Language</p></div>
            <div className="flex gap-2 flex-wrap">
              {LANGS.map(l => (
                <button key={l.c} onClick={() => setLang(l.c)} className={`px-3 py-1.5 text-xs rounded-full border ${lang === l.c ? 'text-white' : 'bg-white text-gray-600'}`} style={lang === l.c ? { backgroundColor: theme.primary, borderColor: theme.primary } : {}} data-testid={`lang-${l.c}`}>{l.n}</button>
              ))}
            </div>
          </div>
        </CardContent>
      </Card>

      {/* 2FA */}
      {isOwner && (
        <Card>
          <CardContent className="p-5 space-y-3">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="font-bold text-sm uppercase tracking-wider text-gray-500 flex items-center gap-2"><Lock size={14} /> Two-Factor Authentication</h2>
                <p className="text-xs text-gray-500 mt-1">Extra security for owner login. {user?.twoFactorEnabled && <Badge className="bg-green-100 text-green-700 ml-1">Enabled</Badge>}</p>
              </div>
              {user?.twoFactorEnabled ? (
                <Button variant="outline" onClick={disable2FA} data-testid="disable-2fa">Disable</Button>
              ) : (
                <Button onClick={start2FA} style={{ backgroundColor: theme.primary }} data-testid="setup-2fa">Enable 2FA</Button>
              )}
            </div>
            {setup && (
              <div className="bg-gray-50 p-4 rounded-lg space-y-3" data-testid="2fa-setup">
                <p className="text-sm">Scan this URI in your authenticator app:</p>
                <code className="block text-xs bg-white p-2 rounded border break-all">{setup.qrUri}</code>
                <p className="text-xs text-gray-500">For demo, use code <strong>123456</strong> to verify.</p>
                <div className="flex gap-2">
                  <Input placeholder="6-digit code" value={code} onChange={e => setCode(e.target.value)} data-testid="2fa-code" />
                  <Button onClick={verify2FA} style={{ backgroundColor: theme.primary }} data-testid="verify-2fa">Verify</Button>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* GDPR Tools */}
      <Card>
        <CardContent className="p-5">
          <h2 className="font-bold text-sm uppercase tracking-wider text-gray-500 mb-3 flex items-center gap-2"><AlertCircle size={14} /> GDPR Data Tools</h2>
          <p className="text-xs text-gray-500 mb-4">Export or anonymize personal data for any customer (Article 15 + 17 compliance).</p>
          <div className="space-y-2 max-h-64 overflow-y-auto">
            {customers.map(c => (
              <div key={c.id} className="flex items-center justify-between p-2 border rounded-lg" data-testid={`gdpr-row-${c.id}`}>
                <div className="text-sm"><span className="font-medium">{c.name}</span> <span className="text-gray-500 text-xs">· {c.email || '—'}</span></div>
                <div className="flex gap-1">
                  <Button size="sm" variant="outline" onClick={() => doExport(c.id)} data-testid={`gdpr-export-${c.id}`}><Download size={12} className="mr-1" /> Export</Button>
                  {isOwner && <Button size="sm" variant="outline" className="text-red-500" onClick={() => doErase(c.id)} data-testid={`gdpr-erase-${c.id}`}>Erase</Button>}
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
      <SensitiveActionReauthDialog
        open={!!pendingReauth}
        label={pendingReauth?.label || ''}
        onVerified={() => { const run = pendingReauth?.run; setPendingReauth(null); run?.(); }}
        onCancel={() => setPendingReauth(null)}
      />
    </div>
  );
}
