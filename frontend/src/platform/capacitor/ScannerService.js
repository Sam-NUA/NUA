/** Capacitor's WebView is a real Chromium/WKWebView engine — the same
 * BarcodeDetector feature-detection the web implementation does applies
 * unchanged here; there's no Capacitor-specific scanner plugin installed
 * (see MOBILE_DESKTOP_BACKLOG.md) to prefer over it. */
export * from '../web/ScannerService';
