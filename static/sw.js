/*
  Gym PWA Service Worker (v1)
  Provides offline caching, offline app-shell resilience, and asset caching.
*/

const CACHE_NAME = 'gym-pwa-v1';

// Core assets to pre-cache on install
const PRECACHE_ASSETS = [
  '/',
  '/static/style.css',
  '/static/manifest.json',
  '/static/icon-192.png',
  '/static/icon-512.png',
  '/static/apple-touch-icon.png',
  '/static/icon.svg',
  'https://cdn.tailwindcss.com'
];

// ── Install: Precache core shell assets ──────────────────────────────────────────
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => {
        // Cache core assets gracefully (don't fail entire install if CDN is unavailable)
        return Promise.allSettled(
          PRECACHE_ASSETS.map((url) =>
            fetch(url)
              .then((res) => {
                if (res.ok) return cache.put(url, res);
              })
              .catch((err) => console.warn('[SW] Could not pre-cache:', url, err))
          )
        );
      })
      .then(() => self.skipWaiting())
  );
});

// ── Activate: Clean up older cache versions ─────────────────────────────────────
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => {
        return Promise.all(
          keys
            .filter((key) => key !== CACHE_NAME)
            .map((key) => caches.delete(key))
        );
      })
      .then(() => self.clients.claim())
  );
});

// ── Fetch: Network-first for HTML, Stale-while-revalidate for assets ─────────────
self.addEventListener('fetch', (event) => {
  const request = event.request;

  // Only handle GET requests (POSTs cannot be cached by Cache API)
  if (request.method !== 'GET') {
    return;
  }

  const url = new URL(request.url);

  // 1. Navigation requests (HTML pages) → Network-first with cache fallback
  if (request.mode === 'navigate' || request.destination === 'document' || url.pathname === '/') {
    event.respondWith(
      fetch(request)
        .then((networkResponse) => {
          if (networkResponse && networkResponse.status === 200) {
            const clone = networkResponse.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put('/', clone));
          }
          return networkResponse;
        })
        .catch(async () => {
          // Network failed (offline or server unreachable) → serve cached app shell
          const cachedResponse = await caches.match('/');
          if (cachedResponse) {
            return cachedResponse;
          }
          return new Response(
            '<!DOCTYPE html><html><body style="font-family:sans-serif;text-align:center;padding:50px;">' +
            '<h2>Gym Tracker (Offline)</h2><p>Please reconnect to your local network.</p></body></html>',
            { headers: { 'Content-Type': 'text/html' } }
          );
        })
    );
    return;
  }

  // 2. Static assets (CSS, JS, Images, Icons, Tailwind CDN) → Stale-while-revalidate
  if (
    url.pathname.startsWith('/static/') ||
    request.destination === 'style' ||
    request.destination === 'script' ||
    request.destination === 'image' ||
    url.hostname === 'cdn.tailwindcss.com'
  ) {
    event.respondWith(
      caches.match(request).then((cachedResponse) => {
        const fetchPromise = fetch(request)
          .then((networkResponse) => {
            if (networkResponse && networkResponse.status === 200) {
              const clone = networkResponse.clone();
              caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
            }
            return networkResponse;
          })
          .catch(() => cachedResponse);

        return cachedResponse || fetchPromise;
      })
    );
    return;
  }

  // 3. All other GET requests → Network with Cache fallback
  event.respondWith(
    fetch(request)
      .catch(() => caches.match(request))
  );
});
