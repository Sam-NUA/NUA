import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import { useAuth } from '../contexts/AuthContext';
import { staffMgmtAPI, authAPI } from '../services/api';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Card, CardContent } from '../components/ui/card';
import { Lock, Mail, AlertCircle, Hash, ShieldCheck, CheckCircle2, Wifi, WifiOff, Printer, CreditCard, ShieldQuestion } from 'lucide-react';
import Logo from '../components/brand/Logo';

const API = process.env.REACT_APP_BACKEND_URL;

// Live clock/date + internet status + this terminal's known peripherals —
// the first thing anyone should see walking up to a POS station, before
// they've even entered a PIN.
function StatusStrip() {
  const [now, setNow] = useState(new Date());
  const [online, setOnline] = useState(navigator.onLine);
  const [devices, setDevices] = useState(null);

  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    const goOnline = () => setOnline(true);
    const goOffline = () => setOnline(false);
    window.addEventListener('online', goOnline);
    window.addEventListener('offline', goOffline);
    return () => { window.removeEventListener('online', goOnline); window.removeEventListener('offline', goOffline); };
  }, []);

  useEffect(() => {
    let cancelled = false;
    const check = () => axios.get(`${API}/api/ops/device-status`, { timeout: 4000 })
      .then(r => { if (!cancelled) setDevices(r.data); })
      .catch(() => { if (!cancelled) setDevices(null); });
    check();
    const t = setInterval(check, 30000);
    return () => { cancelled = true; clearInterval(t); };
  }, []);

  return (
    <div className="mb-5 text-center" data-testid="login-status-strip">
      <p className="text-2xl font-mono font-bold text-nua-chromeInk tracking-wide">
        {now.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
      </p>
      <p className="text-xs text-nua-chromeMuted mb-3">
        {now.toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long' })}
      </p>
      <div className="flex items-center justify-center gap-3 text-[11px]">
        <span className={`flex items-center gap-1 ${online ? 'text-[#046C4E]' : 'text-[#B01B1B]'}`} data-testid="login-connection-status">
          {online ? <Wifi size={13} /> : <WifiOff size={13} />} {online ? 'Online' : 'Offline'}
        </span>
        <span className={`flex items-center gap-1 ${devices?.receiptTemplateConfigured ? 'text-[#046C4E]' : 'text-nua-chromeMuted'}`} title="Receipt template">
          <Printer size={13} /> {devices?.receiptTemplateConfigured ? 'Printer ready' : 'Printer not set up'}
        </span>
        <span className={`flex items-center gap-1 ${devices?.cardReaderConnected ? 'text-[#046C4E]' : 'text-nua-chromeMuted'}`} title="Card reader">
          <CreditCard size={13} /> {devices?.cardReaderConnected ? `Card reader (${devices.cardReaderCount})` : 'No card reader'}
        </span>
      </div>
    </div>
  );
}

// Every catch block on this page did `err.response?.data?.detail || '<wrong
// password>'-style message`. That fallback fires for ANY failure with no
// response object — a CORS rejection, a dropped connection, a cold backend
// instance still waking up, a request that timed out — not just a real
// 401/403 from the server. A transient network hiccup on the login POST was
// showing up as "Invalid credentials," which reads as "your password is
// wrong" when the true story is "we couldn't reach the server that time."
// Retrying the exact same correct password after the hiccup passed is
// exactly the "doesn't work at first, works on retry" pattern that produces
// — this tells the two apart instead of collapsing them into one message.
function loginErrorMessage(err, fallback) {
  if (err.response) return err.response.data?.detail || fallback;
  return "Couldn't reach the server — check your connection and try again.";
}

export default function Login() {
  const { login, completeTwoFactor } = useAuth();
  const navigate = useNavigate();
  // PIN is the priority login method for staff terminals — a device
  // defaults to PIN unless it's specifically the one an owner/manager last
  // signed into with email (so an admin's own laptop doesn't flip to PIN
  // just because they used it once).
  const [mode, setMode] = useState(() => (localStorage.getItem('nua_login_mode') === 'email' ? 'email' : 'pin')); // email | pin | forgot
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [pin, setPin] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  // Set once the password step passes but a code is still owed.
  const [challenge, setChallenge] = useState(null);
  const [code, setCode] = useState('');
  const [trustDevice, setTrustDevice] = useState(true);
  const [forgotEmail, setForgotEmail] = useState('');
  const [forgotSent, setForgotSent] = useState(false);
  const [resendCooldown, setResendCooldown] = useState(0);
  // Set when pin-login reports the staff member isn't rostered right now —
  // replaces the PIN form with a manager/owner PIN prompt to authorize on
  // the spot, rather than a hard lock-out.
  const [needsApproval, setNeedsApproval] = useState(null); // { staffId, staffName }
  const [managerPin, setManagerPin] = useState('');

  const handleEmailLogin = async (e) => {
    e.preventDefault();
    setError(''); setLoading(true);
    try {
      const res = await login(email, password);
      if (res.twoFactor) {
        setChallenge(res.twoFactor);
      } else {
        localStorage.setItem('nua_login_mode', 'email');
        navigate('/clock-in', { replace: true });
      }
    } catch (err) {
      setError(loginErrorMessage(err, 'Invalid credentials'));
    }
    setLoading(false);
  };

  const handleCodeSubmit = async (e) => {
    e.preventDefault();
    setError(''); setLoading(true);
    try {
      const res = await completeTwoFactor(challenge.challengeToken, code, trustDevice);
      if (res.verifiedBy === 'recovery') {
        // Say it out loud — a recovery code is a one-shot, and someone who
        // just burned one needs to know how many are left before they're
        // locked out mid-service.
        window.sessionStorage.setItem(
          'nua_recovery_notice',
          `You signed in with a recovery code. ${res.recoveryCodesRemaining} left.`);
      }
      localStorage.setItem('nua_login_mode', 'email');
      navigate('/clock-in', { replace: true });
    } catch (err) {
      setError(loginErrorMessage(err, 'Incorrect code'));
      setCode('');
    }
    setLoading(false);
  };

  const handlePinLogin = async (e) => {
    e.preventDefault();
    setError(''); setLoading(true);
    try {
      const res = await staffMgmtAPI.pinLogin(pin);
      if (res.data.needsApproval) {
        setNeedsApproval({ staffId: res.data.staffId, staffName: res.data.staffName });
        setLoading(false);
        return;
      }
      localStorage.setItem('nua_token', res.data.token);
      localStorage.setItem('nua_login_mode', 'pin');
      window.location.assign('/clock-in');
    } catch (err) {
      setError(loginErrorMessage(err, 'Invalid PIN'));
    }
    setLoading(false);
  };

  const handleApprovalSubmit = async (e) => {
    e.preventDefault();
    setError(''); setLoading(true);
    try {
      const res = await staffMgmtAPI.approvePinLogin(pin, managerPin);
      localStorage.setItem('nua_token', res.data.token);
      localStorage.setItem('nua_login_mode', 'pin');
      window.location.assign('/clock-in');
    } catch (err) {
      setError(loginErrorMessage(err, 'Invalid manager/owner PIN'));
      setManagerPin('');
    }
    setLoading(false);
  };

  // The server allows 5 forgot-password requests per IP before a 15-minute
  // lockout — this 60s client-side cooldown is just to stop an impatient
  // double-click (or "it didn't arrive yet" retry-spam) from quietly
  // burning through most of that allowance before the first email even
  // has a chance to land.
  useEffect(() => {
    if (resendCooldown <= 0) return;
    const t = setTimeout(() => setResendCooldown(c => c - 1), 1000);
    return () => clearTimeout(t);
  }, [resendCooldown]);

  const requestPasswordReset = async () => {
    setError(''); setLoading(true);
    try {
      // The backend deliberately answers identically whether or not the
      // email has an account — never branch on the response here in a way
      // that would let this screen leak that back to the caller.
      await authAPI.forgotPassword(forgotEmail);
      setForgotSent(true);
      setResendCooldown(60);
    } catch (err) {
      setError(loginErrorMessage(err, 'Something went wrong — try again'));
    }
    setLoading(false);
  };

  const handleForgotSubmit = async (e) => {
    e.preventDefault();
    await requestPasswordReset();
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-nua-bg" data-testid="login-page">
      <Card className="w-full max-w-sm border-nua-chromeBorder bg-nua-surface shadow-lg">
        <CardContent className="p-8">
          {/* Login is chrome, so it uses the plain product lockup (no
              flourish, no gradient) — icon + burgundy Bricolage Grotesque
              wordmark on the ivory card, per NUA_POS_DESIGN_TOKENS.md §2. */}
          <div className="flex flex-col items-center mb-4">
            <Logo variant="product" background="light" size={40} />
          </div>

          <p className="text-center text-nua-chromeInk font-medium mb-1">Good service starts here.</p><p className="text-center text-nua-chromeMuted text-sm mb-5">Your team. Your venue. Your next great shift.</p><StatusStrip />

          {/* Off-roster approval — replaces the PIN form rather than sitting
              alongside it, same "no half-signed-in" reasoning as 2FA below.
              Never a hard lock-out: a manager/owner PIN here always works. */}
          {needsApproval ? (
            <div data-testid="approval-step">
              <div className="flex flex-col items-center mb-5">
                <ShieldQuestion size={28} style={{ color: '#750D28' }} />
                <p className="text-nua-chromeInk font-medium mt-2">{needsApproval.staffName} isn't rostered right now</p>
                <p className="text-nua-chromeMuted text-sm text-center mt-1">
                  Ask a manager or owner to enter their PIN to authorize this login.
                </p>
              </div>
              {error && (
                <div className="flex items-center gap-2 text-[#B01B1B] text-sm bg-[rgba(176,27,27,0.10)] p-3 rounded-lg mb-4" data-testid="approval-error">
                  <AlertCircle size={16} /> {error}
                </div>
              )}
              <form onSubmit={handleApprovalSubmit} className="space-y-4">
                <div className="flex justify-center">
                  <Input type="password" inputMode="numeric" maxLength={4} placeholder="Manager PIN" value={managerPin}
                    autoFocus onChange={e => setManagerPin(e.target.value.replace(/\D/g, '').slice(0, 4))}
                    className="text-center text-3xl tracking-[0.5em] font-mono w-48 h-16 bg-white border-nua-chromeBorderControl text-nua-chromeInk"
                    data-testid="manager-approval-pin" />
                </div>
                <Button type="submit" className="w-full h-11 text-white font-medium hover:opacity-90"
                  style={{ backgroundColor: '#750D28' }} disabled={loading || managerPin.length < 2} data-testid="approval-submit">
                  {loading ? 'Checking...' : 'Authorize login'}
                </Button>
              </form>
              <button onClick={() => { setNeedsApproval(null); setManagerPin(''); setPin(''); setError(''); }}
                className="mt-5 w-full text-sm text-nua-chromeMuted hover:text-nua-chromeInk" data-testid="approval-back">
                Cancel
              </button>
            </div>
          ) : challenge ? (
            <div data-testid="twofactor-step">
              <div className="flex flex-col items-center mb-5">
                <ShieldCheck size={28} style={{ color: '#750D28' }} />
                <p className="text-nua-chromeInk font-medium mt-2">Two-factor check</p>
                <p className="text-nua-chromeMuted text-sm text-center mt-1">
                  {challenge.enrolmentRequired
                    ? 'This venue requires a second factor for your role. Open Settings → Security after signing in on a trusted device.'
                    : 'Enter the 6-digit code from your authenticator app'}
                </p>
              </div>
              {error && (
                <div className="flex items-center gap-2 text-[#B01B1B] text-sm bg-[rgba(176,27,27,0.10)] p-3 rounded-lg mb-4" data-testid="twofactor-error">
                  <AlertCircle size={16} /> {error}
                </div>
              )}
              {!challenge.enrolmentRequired && (
                <form onSubmit={handleCodeSubmit} className="space-y-4">
                  <Input
                    autoFocus inputMode="numeric" autoComplete="one-time-code"
                    placeholder="000000" value={code}
                    onChange={e => setCode(e.target.value.replace(/[^0-9A-Za-z-]/g, '').slice(0, 11))}
                    className="text-center text-2xl tracking-[0.4em] font-mono h-14 bg-white border-nua-chromeBorderControl text-nua-chromeInk"
                    data-testid="twofactor-code" />
                  <label className="flex items-center gap-2 text-sm text-nua-chromeMuted cursor-pointer">
                    <input type="checkbox" checked={trustDevice} className="accent-[#750D28] w-4 h-4"
                      onChange={e => setTrustDevice(e.target.checked)} data-testid="twofactor-trust" />
                    Remember this terminal for 30 days
                  </label>
                  <Button type="submit" className="w-full h-11 text-white font-medium hover:opacity-90"
                    style={{ backgroundColor: '#750D28' }} disabled={loading || code.length < 6}
                    data-testid="twofactor-submit">
                    {loading ? 'Checking...' : 'Verify'}
                  </Button>
                  {challenge.recoveryAvailable && (
                    <p className="text-xs text-nua-chromeMuted text-center">
                      Lost your phone? Enter one of your recovery codes instead.
                    </p>
                  )}
                </form>
              )}
              <button onClick={() => { setChallenge(null); setCode(''); setError(''); }}
                className="mt-5 w-full text-sm text-nua-chromeMuted hover:text-nua-chromeInk"
                data-testid="twofactor-back">
                Use a different account
              </button>
            </div>
          ) : mode === 'forgot' ? (
            <div data-testid="forgot-password-step">
              <div className="flex flex-col items-center mb-5">
                <Lock size={28} style={{ color: '#750D28' }} />
                <p className="text-nua-chromeInk font-medium mt-2">Reset your password</p>
                <p className="text-nua-chromeMuted text-sm text-center mt-1">
                  Enter your email and we'll send you a link to set a new password.
                </p>
              </div>
              {error && (
                <div className="flex items-center gap-2 text-[#B01B1B] text-sm bg-[rgba(176,27,27,0.10)] p-3 rounded-lg mb-4" data-testid="forgot-error">
                  <AlertCircle size={16} /> {error}
                </div>
              )}
              {forgotSent ? (
                <div>
                  <div className="flex items-start gap-2 text-[#046C4E] text-sm bg-[rgba(16,185,129,0.12)] p-3 rounded-lg mb-3" data-testid="forgot-sent">
                    <CheckCircle2 size={16} className="mt-0.5 flex-shrink-0" />
                    If that email has an account, a reset link is on its way. Check your inbox.
                  </div>
                  <Button variant="outline" className="w-full h-10 text-sm border-nua-chromeBorderControl text-nua-chromeInk2 hover:text-nua-chromeInk"
                    onClick={requestPasswordReset} disabled={loading || resendCooldown > 0} data-testid="forgot-resend">
                    {resendCooldown > 0 ? `Resend in ${resendCooldown}s` : loading ? 'Sending...' : "Didn't get it? Resend"}
                  </Button>
                </div>
              ) : (
                <form onSubmit={handleForgotSubmit} className="space-y-4">
                  <div className="relative">
                    <Mail size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-nua-chromeMuted" />
                    <Input type="email" placeholder="Email" value={forgotEmail} onChange={e => setForgotEmail(e.target.value)}
                      className="pl-10 bg-white border-nua-chromeBorderControl text-nua-chromeInk" required data-testid="forgot-email" />
                  </div>
                  <Button type="submit" className="w-full h-11 text-white font-medium hover:opacity-90"
                    style={{ backgroundColor: '#750D28' }} disabled={loading} data-testid="forgot-submit">
                    {loading ? 'Sending...' : 'Send Reset Link'}
                  </Button>
                </form>
              )}
              <button onClick={() => { setMode('email'); setError(''); setForgotSent(false); setForgotEmail(''); setResendCooldown(0); }}
                className="mt-5 w-full text-sm text-nua-chromeMuted hover:text-nua-chromeInk"
                data-testid="forgot-back">
                Back to sign in
              </button>
            </div>
          ) : (
          <>
          {/* Mode Toggle — PIN first: the priority login method for staff terminals */}
          <div className="flex gap-1 mb-6 bg-nua-bgAlt rounded-lg p-1">
            <button onClick={() => setMode('pin')} data-testid="mode-pin"
              className={`flex-1 py-2 text-sm rounded-md font-medium transition-colors ${mode === 'pin' ? 'text-white' : 'text-nua-chromeMuted hover:text-nua-chromeInk'}`}
              style={mode === 'pin' ? { backgroundColor: '#750D28' } : {}}>
              <Hash size={14} className="inline mr-1" /> PIN Code
            </button>
            <button onClick={() => setMode('email')} data-testid="mode-email"
              className={`flex-1 py-2 text-sm rounded-md font-medium transition-colors ${mode === 'email' ? 'text-white' : 'text-nua-chromeMuted hover:text-nua-chromeInk'}`}
              style={mode === 'email' ? { backgroundColor: '#750D28' } : {}}>
              <Mail size={14} className="inline mr-1" /> Email
            </button>
          </div>

          {error && (
            <div className="flex items-center gap-2 text-[#B01B1B] text-sm bg-[rgba(176,27,27,0.10)] p-3 rounded-lg mb-4" data-testid="login-error">
              <AlertCircle size={16} /> {error}
            </div>
          )}

          {mode === 'email' ? (
            <form onSubmit={handleEmailLogin} className="space-y-4">
              <div className="relative">
                <Mail size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-nua-chromeMuted" />
                <Input type="email" placeholder="Email" value={email} onChange={e => setEmail(e.target.value)}
                  className="pl-10 bg-white border-nua-chromeBorderControl text-nua-chromeInk" required data-testid="login-email" />
              </div>
              <div className="relative">
                <Lock size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-nua-chromeMuted" />
                <Input type="password" placeholder="Password" value={password} onChange={e => setPassword(e.target.value)}
                  className="pl-10 bg-white border-nua-chromeBorderControl text-nua-chromeInk" required data-testid="login-password" />
              </div>
              <div className="text-right">
                <button type="button" onClick={() => { setMode('forgot'); setError(''); }}
                  className="text-xs text-nua-chromeMuted hover:text-nua-chromeInk" data-testid="forgot-password-link">
                  Forgot password?
                </button>
              </div>
              <Button type="submit" className="w-full h-11 text-white font-medium hover:opacity-90" style={{ backgroundColor: '#750D28' }} disabled={loading} data-testid="login-submit">
                {loading ? 'Signing in...' : 'Sign In'}
              </Button>
            </form>
          ) : (
            <form onSubmit={handlePinLogin} className="space-y-4">
              <div className="text-center mb-2">
                <p className="text-nua-chromeMuted text-sm">Enter your staff PIN code</p>
              </div>
              <div className="flex justify-center">
                <Input type="password" inputMode="numeric" maxLength={4} placeholder="----" value={pin}
                  onChange={e => { const v = e.target.value.replace(/\D/g, '').slice(0, 4); setPin(v); }}
                  className="text-center text-3xl tracking-[0.5em] font-mono w-48 h-16 bg-white border-nua-chromeBorderControl text-nua-chromeInk"
                  data-testid="login-pin" />
              </div>
              <Button type="submit" className="w-full h-11 text-white font-medium hover:opacity-90" style={{ backgroundColor: '#750D28' }} disabled={loading || pin.length < 2} data-testid="pin-submit">
                {loading ? 'Signing in...' : 'Sign In with PIN'}
              </Button>
            </form>
          )}

          <div className="mt-6 pt-4 border-t border-nua-chromeBorder">
            <p className="text-xs text-nua-chromeMuted text-center">
              {mode === 'email' ? 'Owner: owner@nua.com' : 'Ask your manager for your PIN code'}
            </p>
          </div>
          </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
