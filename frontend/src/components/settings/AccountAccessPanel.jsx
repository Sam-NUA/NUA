import React, { useEffect, useState } from 'react';
import { useAuth } from '../../contexts/AuthContext';
import { authAPI } from '../../services/api';
import { Button } from '../ui/button';
import { Input } from '../ui/input';

export default function AccountAccessPanel() {
  const { user, logout } = useAuth();
  const [options, setOptions] = useState(null);
  const [current, setCurrent] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  useEffect(() => {
    let active = true;
    authAPI.accessOptions().then(r => { if (active) setOptions(r.data); }).catch(() => {});
    return () => { active = false; };
  }, []);

  const save = async e => {
    e.preventDefault(); setError('');
    if (password !== confirm) { setError('Passwords do not match'); return; }
    setBusy(true);
    try {
      await authAPI.changePassword(current, password);
      setCurrent(''); setPassword(''); setConfirm(''); setDone(true);
      localStorage.removeItem('nua_token');
      localStorage.setItem('nua_login_mode', 'email');
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not update your password. Check your connection and try again.');
    } finally { setBusy(false); }
  };

  return <section className="rounded-xl border p-6 space-y-4" data-testid="account-access-panel">
    <h3 className="font-bold text-lg">Your account access</h3>
    <p className="text-sm">Sign-in email: <strong>{user?.email}</strong></p>
    <p className="text-sm opacity-75">Use your own email and password on a new device. The owner can set a personal PIN in Settings → Staff for quick terminal sign-in.</p>
    <p className="text-sm" role="status">{options === null ? 'Recovery status could not yet be confirmed.' : options.emailResetAvailable
      ? 'Email recovery is configured. Keep access to your sign-in inbox and use Forgot password when needed.'
      : 'Email recovery needs setup. Ask your setup administrator to enable it before handing this account over.'}</p>
    {done ? <div role="status" className="space-y-3"><p>Password updated. Sign in again on your devices with the new password.</p><Button onClick={logout}>Return to sign in</Button></div>
      : <form onSubmit={save} className="space-y-3 max-w-sm">
        <h4 className="font-medium">Change your password</h4>
        <label className="block text-sm">Current password<Input required type="password" autoComplete="current-password" value={current} onChange={e => setCurrent(e.target.value)} /></label>
        <label className="block text-sm">New password<Input required minLength={8} type="password" autoComplete="new-password" value={password} onChange={e => setPassword(e.target.value)} /></label>
        <p className="text-xs opacity-75">Use at least 8 characters. A longer, unique password is best.</p>
        <label className="block text-sm">Confirm new password<Input required minLength={8} type="password" autoComplete="new-password" value={confirm} onChange={e => setConfirm(e.target.value)} /></label>
        {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
        <Button disabled={busy} type="submit">{busy ? 'Saving…' : 'Update password'}</Button>
      </form>}
  </section>;
}
