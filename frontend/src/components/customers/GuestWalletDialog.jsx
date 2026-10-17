import React, { useEffect, useState } from 'react';
import { QRCodeSVG } from 'qrcode.react';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '../ui/dialog';
import { Badge } from '../ui/badge';
import { Button } from '../ui/button';
import { finalizeAPI, customersAPI } from '../../services/api';
import { toast } from 'sonner';
import { Wallet, Download, Copy, Loader2, Smartphone, ExternalLink } from 'lucide-react';
import { FileService } from '../../platform';

/**
 * Guest Digital Wallet — QR + barcode for POS scan-to-add and Apple/Google
 * Wallet passes. Signed token so scans can be verified.
 */
export default function GuestWalletDialog({ open, onOpenChange, customer }) {
  const [wallet, setWallet] = useState(null);
  const [balances, setBalances] = useState(null); // vouchers + occasion offers
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open || !customer?.id) return;
    setLoading(true);
    finalizeAPI.guestWallet(customer.id)
      .then(r => setWallet(r.data))
      .catch(() => toast.error('Failed to load wallet'))
      .finally(() => setLoading(false));
    // Vouchers/offers load separately — the pass still renders if this fails.
    customersAPI.getWallet(customer.id)
      .then(r => setBalances(r.data))
      .catch(() => setBalances(null));
  }, [open, customer?.id]);

  const copyToken = async () => {
    if (!wallet?.qrToken) return;
    try {
      await navigator.clipboard.writeText(wallet.qrToken);
      toast.success('Wallet token copied');
    } catch { toast.error('Copy failed'); }
  };

  const downloadPass = async () => {
    if (!wallet) return;
    const passText = `NUA Digital Wallet\nName: ${wallet.name}\nTier: ${wallet.tier}\nPoints: ${wallet.points}\nCredit: $${(wallet.storeCredit || 0).toFixed(2)}\nBarcode: ${wallet.barcode}\nToken: ${wallet.qrToken}\n`;
    const blob = new Blob([passText], { type: 'text/plain' });
    await FileService.downloadFile(blob, `nua-wallet-${wallet.barcode}.txt`);
  };

  const downloadPkpass = () => {
    if (!customer?.id) return;
    // Direct navigation — pkpass triggers native "Add to Apple Wallet" on iOS.
    const token = localStorage.getItem('token') || localStorage.getItem('access_token') || '';
    const base = finalizeAPI.guestWalletApplePkpassUrl(customer.id);
    // Serve via fetch → blob so we can attach the auth header.
    fetch(base, { headers: token ? { Authorization: `Bearer ${token}` } : {} })
      .then(r => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const signed = r.headers.get('X-Pkpass-Signed') === 'true';
        return r.blob().then(b => ({ b, signed }));
      })
      .then(async ({ b, signed }) => {
        await FileService.downloadFile(b, `nua-${customer.id}.pkpass`);
        toast.success(signed ? 'Apple Wallet pass downloaded' : 'Pass downloaded (unsigned — configure certs to enable iOS)');
      })
      .catch(() => toast.error('Failed to download Apple Wallet pass'));
  };

  const openGoogleWallet = async () => {
    if (!customer?.id) return;
    try {
      const r = await finalizeAPI.guestWalletGoogle(customer.id);
      if (!r.data?.url) throw new Error('no url');
      if (!r.data.signed) {
        toast.warning('Preview mode — configure Google service account to enable Save-to-phone');
      }
      window.open(r.data.url, '_blank', 'noopener,noreferrer');
    } catch { toast.error('Failed to build Google Wallet link'); }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md max-h-[85vh] overflow-y-auto" data-testid="guest-wallet-dialog">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Wallet size={18} /> Digital Wallet
          </DialogTitle>
        </DialogHeader>
        {loading || !wallet ? (
          <div className="flex flex-col items-center justify-center py-16">
            <Loader2 className="animate-spin text-gray-400" />
            <p className="text-sm text-gray-500 mt-2">Generating pass…</p>
          </div>
        ) : (
          <div className="space-y-4 py-2" data-testid="wallet-body">
            <div className="rounded-2xl p-5 text-white" style={{ background: 'linear-gradient(135deg, #0f172a 0%, #1e293b 40%, #7c3aed 100%)' }}>
              <div className="flex items-start justify-between mb-4">
                <div>
                  <p className="text-[10px] uppercase tracking-widest text-white/60">NUA Loyalty</p>
                  <p className="text-lg font-bold mt-0.5" data-testid="wallet-name">{wallet.name}</p>
                </div>
                <Badge className="bg-white/20 text-white border-0" data-testid="wallet-tier">{wallet.tier}</Badge>
              </div>
              <div className="bg-white rounded-lg p-3 flex items-center justify-center">
                <QRCodeSVG value={wallet.qrToken} size={148} level="M" data-testid="wallet-qr" />
              </div>
              <div className="flex items-center justify-between mt-4 text-sm">
                <div>
                  <p className="text-[10px] uppercase tracking-widest text-white/50">Points</p>
                  <p className="text-lg font-bold" data-testid="wallet-points">{wallet.points}</p>
                </div>
                <div className="text-right">
                  <p className="text-[10px] uppercase tracking-widest text-white/50">Credit</p>
                  <p className="text-lg font-bold" data-testid="wallet-credit">${(wallet.storeCredit || 0).toFixed(2)}</p>
                </div>
              </div>
              <div className="mt-3 font-mono text-xs text-white/70 tracking-widest text-center" data-testid="wallet-barcode">
                {wallet.barcode}
              </div>
            </div>

            {/* Active vouchers & occasion offers */}
            {(balances?.vouchers || []).length > 0 && (
              <div className="rounded-xl border border-emerald-200 bg-emerald-50/60 p-3 space-y-2" data-testid="wallet-vouchers">
                <p className="text-[10px] font-bold uppercase tracking-widest text-emerald-700">
                  Vouchers & Offers · ${(balances.totalVoucherValue || 0).toFixed(2)} available
                </p>
                {balances.vouchers.map(v => (
                  <div key={v.id} className="flex items-center justify-between bg-white rounded-lg px-3 py-2 border border-emerald-100" data-testid={`wallet-voucher-row-${v.id}`}>
                    <div>
                      <p className="text-sm font-semibold text-gray-800">
                        {v.occasion || (v.reason === 'win_back' ? 'We miss you 💌' : 'Voucher')}
                      </p>
                      {v.expiresAt && (
                        <p className="text-[10px] text-gray-400">Expires {new Date(v.expiresAt).toLocaleDateString()}</p>
                      )}
                    </div>
                    <span className="text-sm font-bold text-emerald-700">${Number(v.amount).toFixed(2)}</span>
                  </div>
                ))}
                <p className="text-[10px] text-emerald-700/70">Applied with one tap from the POS wallet panel at checkout.</p>
              </div>
            )}

            <div className="flex gap-2">
              <Button variant="outline" onClick={copyToken} className="flex-1" data-testid="wallet-copy-token">
                <Copy size={14} className="mr-1.5" /> Copy token
              </Button>
              <Button variant="outline" onClick={downloadPass} className="flex-1" data-testid="wallet-download">
                <Download size={14} className="mr-1.5" /> Text pass
              </Button>
            </div>
            <div className="flex gap-2">
              <Button
                onClick={downloadPkpass}
                className="flex-1 text-white"
                style={{ background: '#111827' }}
                data-testid="wallet-apple-pkpass"
              >
                <Smartphone size={14} className="mr-1.5" /> Add to Apple Wallet
              </Button>
              <Button
                onClick={openGoogleWallet}
                className="flex-1 text-white"
                style={{ background: '#4285F4' }}
                data-testid="wallet-google"
              >
                <ExternalLink size={14} className="mr-1.5" /> Save to Google Wallet
              </Button>
            </div>
            <p className="text-[11px] text-gray-500 text-center leading-relaxed">
              Scan the QR at POS to add the customer, redeem points or apply store credit.
              The token is HMAC-signed and expires after long-term rotation.
            </p>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
