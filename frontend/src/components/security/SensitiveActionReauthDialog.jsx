import React, { useEffect, useState } from 'react';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '../ui/dialog';
import { Button } from '../ui/button';
import { Input } from '../ui/input';
import { ShieldCheck } from 'lucide-react';
import { authAPI } from '../../services/api';
import { BiometricService } from '../../platform';

/**
 * Directive Phase 5 — "evaluate biometric reauthentication for managers,
 * refunds, voids, sensitive settings." BiometricService reports
 * 'unsupported' on every platform today (no hardware/plugin is wired
 * up — see platform/*\/BiometricService.js), so this always falls back
 * to the real, server-verified step every platform actually uses: PIN
 * re-entry, checked by POST /api/auth/verify-sensitive-action against
 * either the acting user's own PIN or a manager/owner's PIN from the
 * SAME business — the backend enforces the tenant check, this dialog
 * never decides who's allowed, only collects the PIN.
 *
 * `label` names the action being gated (e.g. "issue this refund") so
 * the prompt reads like a real confirmation, not a generic PIN screen.
 */
export default function SensitiveActionReauthDialog({ open, label, onVerified, onCancel }) {
  const [pin, setPin] = useState('');
  const [error, setError] = useState('');
  const [checking, setChecking] = useState(false);

  useEffect(() => {
    if (!open) { setPin(''); setError(''); return; }
    // Biometric first, if a future platform ever reports it available —
    // callers never need to know which path actually ran.
    if (BiometricService.isAvailable()) {
      BiometricService.verify(label).then(onVerified).catch(() => { /* fall through to PIN */ });
    }
  }, [open, label, onVerified]);

  const submit = async () => {
    if (pin.length < 2) return;
    setChecking(true);
    setError('');
    try {
      const res = await authAPI.verifySensitiveAction(pin);
      onVerified(res.data);
    } catch (e) {
      setError(e?.response?.data?.detail || 'Invalid PIN');
    } finally {
      setChecking(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onCancel?.(); }}>
      <DialogContent className="max-w-xs" data-testid="sensitive-action-reauth-dialog">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <ShieldCheck size={16} /> Confirm with PIN
          </DialogTitle>
        </DialogHeader>
        <p className="text-sm text-muted-foreground">
          Enter your PIN (or a manager/owner's) to {label}.
        </p>
        <Input
          type="password"
          inputMode="numeric"
          maxLength={4}
          autoFocus
          placeholder="PIN"
          value={pin}
          onChange={(e) => setPin(e.target.value.replace(/\D/g, '').slice(0, 4))}
          onKeyDown={(e) => { if (e.key === 'Enter') submit(); }}
          data-testid="sensitive-action-reauth-pin"
        />
        {error && <p className="text-sm text-red-500">{error}</p>}
        <DialogFooter>
          <Button variant="outline" onClick={onCancel}>Cancel</Button>
          <Button onClick={submit} disabled={checking || pin.length < 2} data-testid="sensitive-action-reauth-submit">
            {checking ? 'Checking…' : 'Confirm'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
