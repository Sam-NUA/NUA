import { useEffect, useState, useCallback } from 'react';
import { NetworkService } from '../platform';
import { getQueueStatus, flushQueue } from '../lib/offlineQueue';

/** Tracks how many sales are queued offline and keeps retrying to flush them. */
export default function useOfflineQueue() {
  const [queuedCount, setQueuedCount] = useState(0);
  const [reviewCount, setReviewCount] = useState(0);

  const refresh = useCallback(async () => {
    const status = await getQueueStatus(); setQueuedCount(status.sales); setReviewCount(status.review);
  }, []);
  const trySync = useCallback(async () => {
    try { await flushQueue(setQueuedCount); } catch { /* session locked or storage unavailable */ }
    await refresh();
  }, [refresh]);

  useEffect(() => {
    refresh();
    trySync(); // in case sales were queued in a previous session and we're back online now
    const unsubscribe = NetworkService.addStatusListener(({ connected }) => { if (connected) trySync(); });
    const id = setInterval(trySync, 30000); // safety net — 'online' doesn't always fire cleanly
    return () => { unsubscribe(); clearInterval(id); };
  }, [refresh, trySync]);

  return { queuedCount, reviewCount, refresh };
}
