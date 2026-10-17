export function isOnline() {
  return navigator.onLine;
}

/** Returns an unsubscribe function, same contract as the Capacitor adapter. */
export function addStatusListener(callback) {
  const onOnline = () => callback({ connected: true });
  const onOffline = () => callback({ connected: false });
  window.addEventListener('online', onOnline);
  window.addEventListener('offline', onOffline);
  return () => {
    window.removeEventListener('online', onOnline);
    window.removeEventListener('offline', onOffline);
  };
}
