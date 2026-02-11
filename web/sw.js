/*
 * Service Worker — cache the shell, stay out of the way.
 *
 * Strategy: cache the static shell (HTML, CSS, JS, icons) so the app
 * loads instantly. API calls always go to network — this is a live
 * chat app, not an offline reader.
 */

const CACHE_NAME = 'silentstar-v2';
const BASE = '/silentstar/';

const SHELL_ASSETS = [
  BASE,
  BASE + 'static/style.css',
  BASE + 'static/chat.js',
  BASE + 'static/space.js',
  BASE + 'static/icon.svg',
  BASE + 'static/icon-192.png',
  BASE + 'static/icon-512.png',
];

// Install: pre-cache the shell
self.addEventListener('install', ev => {
  ev.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      return cache.addAll(SHELL_ASSETS);
    })
  );
  self.skipWaiting();
});

// Activate: clean old caches
self.addEventListener('activate', ev => {
  ev.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys
          .filter(k => k !== CACHE_NAME)
          .map(k => caches.delete(k))
      )
    )
  );
  self.clients.claim();
});

// Fetch: network-first for API/dynamic, cache-first for shell assets
self.addEventListener('fetch', ev => {
  const url = new URL(ev.request.url);

  // API calls, form submissions, HTMX requests — always network
  if (url.pathname.startsWith(BASE + 'api/') ||
      ev.request.method !== 'GET') {
    return;
  }

  // Shell assets — cache-first, fall back to network
  ev.respondWith(
    caches.match(ev.request, { ignoreSearch: true }).then(cached => {
      if (cached) {
        // Refresh cache in background
        fetch(ev.request).then(resp => {
          if (resp.ok) {
            caches.open(CACHE_NAME).then(cache => cache.put(ev.request, resp));
          }
        }).catch(() => {});
        return cached;
      }
      return fetch(ev.request);
    })
  );
});
