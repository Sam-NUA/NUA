import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { authAPI } from '../services/api';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Card, CardContent } from '../components/ui/card';
import { KeyRound, Lock, Mail, AlertCircle, CheckCircle2 } from 'lucide-react';
import Logo from '../components/brand/Logo';

// Operator-only last-resort recovery — not linked from the sign-in screen on
// purpose. Reachable only by someone who already holds OWNER_RECOVERY_KEY
// (set directly in Vercel, never shared here). Step 1 trades that key for a
// single-use, 15-minute token; step 2 trades the token for a new password.
export default function OwnerRecovery() {
  const [step, setStep] = useState('initiate');
  const [recoveryKey, setRecoveryKey] = useState('');
  const [email, setEmail] = useState('');
  const [token, setToken] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);

  const handleInitiate = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const res = await authAPI.ownerRecoveryInitiate(recoveryKey, email);
      setToken(res.data.token);
      setStep('complete');
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not start recovery');
    }
    setLoading(false);
  };

  const handleComplete = async (e) => {
    e.preventDefault();
    setError('');
    if (password.length < 8) { setError('Password must be at least 8 characters'); return; }
    if (password !== confirm) { setError('Passwords do not match'); return; }
    setLoading(true);
    try {
      await authAPI.ownerRecoveryComplete(token, password);
      setDone(true);
    } catch (err) {
      setError(err.response?.data?.detail || 'This recovery token is invalid or has expired');
    }
    setLoading(false);
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-gray-900 via-gray-950 to-black" data-testid="owner-recovery-page">
      <Card className="w-full max-w-sm border-gray-800 bg-gray-900/80 backdrop-blur">
        <CardContent className="p-8">
          <div className="flex flex-col items-center mb-6">
            <Logo variant="marketing" background="dark" size={34} />
          </div>

          {done ? (
            <div className="text-center" data-testid="owner-recovery-success">
              <CheckCircle2 size={28} className="mx-auto mb-3 text-emerald-400" />
              <p className="text-white font-medium mb-1">Owner password updated</p>
              <p className="text-gray-400 text-sm mb-5">Sign in with your new password.</p>
              <Link to="/" className="text-sm hover:opacity-90" style={{ color: '#f58c14' }} data-testid="owner-recovery-back-to-login">
                Back to sign in
              </Link>
            </div>
          ) : step === 'initiate' ? (
            <>
              <div className="flex flex-col items-center mb-5">
                <KeyRound size={28} style={{ color: '#f58c14' }} />
                <p className="text-white font-medium mt-2">Owner access recovery</p>
                <p className="text-gray-400 text-sm text-center mt-1">
                  Operator-only. Requires the recovery key configured in Vercel.
                </p>
              </div>
              {error && (
                <div className="flex items-center gap-2 text-red-400 text-sm bg-red-950/50 p-3 rounded-lg mb-4" data-testid="owner-recovery-error">
                  <AlertCircle size={16} /> {error}
                </div>
              )}
              <form onSubmit={handleInitiate} className="space-y-4">
                <div className="relative">
                  <KeyRound size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
                  <Input type="password" placeholder="OWNER_RECOVERY_KEY" value={recoveryKey}
                    onChange={e => setRecoveryKey(e.target.value)}
                    className="pl-10 bg-gray-800 border-gray-700 text-white" required
                    data-testid="owner-recovery-key-input" />
                </div>
                <div className="relative">
                  <Mail size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
                  <Input type="email" placeholder="Owner email" value={email}
                    onChange={e => setEmail(e.target.value)}
                    className="pl-10 bg-gray-800 border-gray-700 text-white" required
                    data-testid="owner-recovery-email-input" />
                </div>
                <Button type="submit" className="w-full h-11 text-white font-medium hover:opacity-90"
                  style={{ backgroundColor: '#f58c14' }} disabled={loading} data-testid="owner-recovery-initiate-submit">
                  {loading ? 'Verifying...' : 'Request recovery token'}
                </Button>
              </form>
            </>
          ) : (
            <>
              <div className="flex flex-col items-center mb-5">
                <Lock size={28} style={{ color: '#f58c14' }} />
                <p className="text-white font-medium mt-2">Set a new owner password</p>
                <p className="text-gray-400 text-sm text-center mt-1">This token is single-use and expires in 15 minutes.</p>
              </div>
              {error && (
                <div className="flex items-center gap-2 text-red-400 text-sm bg-red-950/50 p-3 rounded-lg mb-4" data-testid="owner-recovery-complete-error">
                  <AlertCircle size={16} /> {error}
                </div>
              )}
              <form onSubmit={handleComplete} className="space-y-4">
                <div className="relative">
                  <Lock size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
                  <Input type="password" placeholder="New password" value={password}
                    onChange={e => setPassword(e.target.value)}
                    className="pl-10 bg-gray-800 border-gray-700 text-white" required
                    data-testid="owner-recovery-password-input" />
                </div>
                <div className="relative">
                  <Lock size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
                  <Input type="password" placeholder="Confirm password" value={confirm}
                    onChange={e => setConfirm(e.target.value)}
                    className="pl-10 bg-gray-800 border-gray-700 text-white" required
                    data-testid="owner-recovery-confirm-input" />
                </div>
                <Button type="submit" className="w-full h-11 text-white font-medium hover:opacity-90"
                  style={{ backgroundColor: '#f58c14' }} disabled={loading} data-testid="owner-recovery-complete-submit">
                  {loading ? 'Saving...' : 'Set new password'}
                </Button>
              </form>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
