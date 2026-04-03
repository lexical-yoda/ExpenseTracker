const CACHE_VERSION = 4;
const CACHE_NAME = 'em-v' + CACHE_VERSION;
const PRECACHE = [
  '/static/themes.css',
  '/static/theme.js',
  '/static/interactions.js',
  '/static/favicon.svg',
];

// Install: precache static assets
self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(PRECACHE))
  );
  self.skipWaiting();
});

// Activate: clean old caches
self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// Fetch: stale-while-revalidate for static, network-first for everything else
self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);

  // Skip non-GET requests
  if (e.request.method !== 'GET') return;

  // Static assets: stale-while-revalidate (serve cached, update in background)
  if (url.pathname.startsWith('/static/')) {
    e.respondWith(
      caches.open(CACHE_NAME).then(cache =>
        cache.match(e.request).then(cached => {
          const fetchPromise = fetch(e.request).then(resp => {
            // Only cache successful responses (prevent cache poisoning)
            if (resp.ok) {
              cache.put(e.request, resp.clone());
            }
            return resp;
          }).catch(() => cached); // Fall back to cache on network failure

          return cached || fetchPromise;
        })
      )
    );
    return;
  }

  // Everything else: network-first (so data is always fresh)
  e.respondWith(
    fetch(e.request).catch(() => caches.match(e.request))
  );
});
