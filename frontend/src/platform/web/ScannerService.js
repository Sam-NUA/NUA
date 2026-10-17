/** Directive Phase 7 — ScannerService. Keyboard-emulation scanners need
 * nothing from this service at all: they just type into whatever text
 * input has focus, which already works everywhere with zero code. This
 * only covers the one thing that needs feature detection: camera-based
 * scanning via the browser-native BarcodeDetector (no extra dependency),
 * used by components/pos/ScanVoucherButton.jsx. No native scanner SDK or
 * USB/Bluetooth scanner integration exists on any platform — that's new
 * work, not a gap in this abstraction, and is tracked honestly in
 * MOBILE_DESKTOP_BACKLOG.md rather than faked here.
 */
export function isCameraScanAvailable() {
  return typeof window !== 'undefined' && 'BarcodeDetector' in window;
}

export function getCapability() {
  return isCameraScanAvailable()
    ? { status: 'available' }
    : { status: 'unsupported', reason: 'BarcodeDetector is not available in this browser engine.' };
}
