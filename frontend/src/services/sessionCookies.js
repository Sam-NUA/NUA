import { Capacitor, CapacitorCookies } from '@capacitor/core';
import { usesDurableNativeRefresh, clearDurableNativeRefresh } from './nativeRefreshSession';

// The native HTTP cookie jar outlives the WebView and remains available while
// offline. Clear the API's native and WK cookie stores without reading secrets.
// Browser/Windows HttpOnly cookies still require the server's logout response.
export async function clearNativeSessionCookies(apiUrl) {
  if (!Capacitor.isNativePlatform()) return false;
  if (usesDurableNativeRefresh()) {
    await clearDurableNativeRefresh(apiUrl);
    return true;
  }
  await CapacitorCookies.clearCookies({ url: apiUrl });
  return true;
}
