import { Network } from '@capacitor/network';

/** Capacitor's Network plugin, not navigator.onLine — per the browser-API
 * audit, the Network Information API this app's web code also reads
 * (components/pos/POSHeaderBar.jsx) is Chromium-only and absent on iOS
 * WebKit entirely; this plugin is the one connectivity signal that's
 * actually reliable on both Android and iOS. */
export async function isOnline() {
  const status = await Network.getStatus();
  return status.connected;
}

/** Returns an unsubscribe function, same contract as the web adapter.
 * Capacitor's addListener is itself async (resolves to the handle) — the
 * returned unsubscribe function awaits it before removing, so a caller
 * that unsubscribes immediately after subscribing doesn't race it. */
export function addStatusListener(callback) {
  const handlePromise = Network.addListener('networkStatusChange', (status) => {
    callback({ connected: status.connected });
  });
  return () => { handlePromise.then((handle) => handle.remove()); };
}
