// NUA POS service worker — v4 (network-first for JS/HTML to avoid stale bundles)
const CACHE = 'nua-shell-v4';
const STATIC_ASSETS = ['/manifest.json', '/favicon.ico'];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE)
      .then(c => c.addAll(STATIC_ASSETS).catch(() => {}))
  );
  self.skipWaiting();
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(
        // Delete EVERY old cache (including this version's predecessors)
        keys.filter(k => k !== CACHE).map(k => caches.delete(k))
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);

  // Never cache same-origin app code/HTML — always network-first so a new
  // deploy is picked up immediately. Falls back to cache only when offline.
  const isAppShell =
    req.mode === 'navigate' ||
    url.pathname.endsWith('.js') ||
    url.pathname.endsWith('.css') ||
    url.pathname.endsWith('.html') ||
    url.pathname === '/';

  // API always network-only (no SW caching of authenticated data)
  if ((url.pathname.startsWith('/api/') || url.pathname.startsWith('/bookings-api/'))) {
    e.respondWith(fetch(req).catch(() => new Response(JSON.stringify({offline: true}), {status: 503, headers: {'Content-Type': 'application/json'}})));
    return;
  }

  if (isAppShell) {
    e.respondWith(
      fetch(req)
        .then(resp => {
          // Only cache successful navigations as a last-resort offline fallback
          if (req.mode === 'navigate' && resp.ok) {
            const clone = resp.clone();
            caches.open(CACHE).then(c => c.put('/', clone)).catch(() => {});
          }
          return resp;
        })
        .catch(() => caches.match(req).then(hit => hit || caches.match('/')))
    );
    return;
  }

  // Static assets (images, fonts, icons) — cache-first with background refresh
  e.respondWith(
    caches.match(req).then(hit => {
      const fetchPromise = fetch(req).then(resp => {
        if (resp.ok) {
          const clone = resp.clone();
          caches.open(CACHE).then(c => c.put(req, clone)).catch(() => {});
        }
        return resp;
      }).catch(() => hit);
      return hit || fetchPromise;
    })
  );
});

// Allow the page to ask the SW to update + purge caches immediately
self.addEventListener('message', (e) => {
  if (e.data === 'SKIP_WAITING') self.skipWaiting();
  if (e.data === 'PURGE') {
    caches.keys().then(keys => Promise.all(keys.map(k => caches.delete(k))));
  }
});
