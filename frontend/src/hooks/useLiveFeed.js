import { useEffect, useRef, useState } from 'react';

import api from '../services/api';

// A shared, bounded invalidation feed works across function instances and
// reconnects. Consumers retain their normal data refresh as a safety net.
export default function useLiveFeed(onEvent) {
  const [connected, setConnected] = useState(false);
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;

  useEffect(() => {
    let stopped = false;
    let timer;
    let cursor;
    let delay = 5000;
    const controller = new AbortController();
    const poll = async () => {
      const token = localStorage.getItem('nua_token');
      if (!token || stopped) { setConnected(false); return; }
      try {
        const query = cursor ? `?cursor=${encodeURIComponent(cursor)}` : '';
        const response = await api.get(`/realtime/events${query}`, {
          signal: controller.signal,
        });
        const data = response.data;
        if (stopped) return;
        setConnected(true);
        delay = 5000;
        if (data.reset) onEventRef.current?.({ type: 'sync.required' });
        for (const event of data.events) onEventRef.current?.(event);
        cursor = data.cursor;
      } catch (error) {
        if (!stopped) setConnected(false);
        const status = error.response?.status;
        if (status === 401 || status === 403) return;
        const retry = Number(error.response?.headers?.['retry-after']);
        delay = Math.max(5000, Math.min(60000, retry ? retry * 1000 : delay * 2));
      }
      if (!stopped) timer = setTimeout(poll, delay);
    };
    poll();
    return () => { stopped = true; clearTimeout(timer); controller.abort(); };
  }, []);
  return { connected };
}
