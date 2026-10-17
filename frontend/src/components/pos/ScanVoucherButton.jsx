import React, { useEffect, useRef, useState } from 'react';
import { ScanLine, X } from 'lucide-react';
import { Button } from '../ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '../ui/dialog';
import { ScannerService } from '../../platform';

/**
 * Scan a promo/voucher QR or barcode with the device camera and hand the
 * decoded text back to the caller (who feeds it into the existing manual
 * code input + apply flow — no separate redemption path to keep in sync).
 *
 * Uses the browser-native BarcodeDetector (shipped in Chromium/Edge) so no
 * extra dependency is needed. Hides itself entirely when unsupported —
 * staff still have the manual code input as a fallback.
 */
export default function ScanVoucherButton({ onDetected }) {
  const [supported] = useState(() => ScannerService.isCameraScanAvailable());
  const [open, setOpen] = useState(false);
  const [error, setError] = useState('');
  const videoRef = useRef(null);
  const streamRef = useRef(null);
  const rafRef = useRef(null);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;

    const start = async () => {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } });
        if (cancelled) { stream.getTracks().forEach(t => t.stop()); return; }
        streamRef.current = stream;
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          await videoRef.current.play();
        }
        const detector = new window.BarcodeDetector({ formats: ['qr_code', 'code_128', 'ean_13'] });
        const tick = async () => {
          if (cancelled || !videoRef.current) return;
          try {
            const codes = await detector.detect(videoRef.current);
            if (codes && codes.length > 0) {
              const value = (codes[0].rawValue || '').trim();
              if (value) {
                onDetected(value);
                setOpen(false);
                return;
              }
            }
          } catch { /* keep scanning */ }
          rafRef.current = requestAnimationFrame(tick);
        };
        rafRef.current = requestAnimationFrame(tick);
      } catch (e) {
        setError('Camera unavailable — check permissions, or type the code instead.');
      }
    };
    start();

    return () => {
      cancelled = true;
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      if (streamRef.current) streamRef.current.getTracks().forEach(t => t.stop());
      streamRef.current = null;
    };
  }, [open, onDetected]);

  if (!supported) return null;

  return (
    <>
      <Button type="button" variant="outline" size="icon" onClick={() => { setError(''); setOpen(true); }}
        title="Scan voucher QR / barcode" data-testid="scan-voucher-btn">
        <ScanLine size={16} />
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-sm" data-testid="scan-voucher-dialog">
          <DialogHeader><DialogTitle>Scan voucher code</DialogTitle></DialogHeader>
          <div className="relative rounded-lg overflow-hidden bg-black aspect-square">
            <video ref={videoRef} className="w-full h-full object-cover" muted playsInline />
            <div className="absolute inset-8 border-2 border-white/70 rounded-lg pointer-events-none" />
          </div>
          {error ? (
            <p className="text-sm text-red-500 mt-2">{error}</p>
          ) : (
            <p className="text-xs text-gray-500 mt-2 text-center">Point the camera at the code on the guest's phone or printout.</p>
          )}
          <Button variant="ghost" size="sm" className="w-full mt-1" onClick={() => setOpen(false)}>
            <X size={14} className="mr-1" /> Cancel
          </Button>
        </DialogContent>
      </Dialog>
    </>
  );
}
