const CACHE_NAME = 'pms-cache-v1';
const ASSETS_TO_CACHE = [
  '/',
  '/static/manifest.json',
  '/static/images/favicon.svg'
];

// Install Event
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(ASSETS_TO_CACHE);
    })
  );
  self.skipWaiting();
});

// Activate Event
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames.map((cache) => {
          if (cache !== CACHE_NAME) {
            return caches.delete(cache);
          }
        })
      );
    })
  );
  self.clients.claim();
});

// Fetch Event
self.addEventListener('fetch', (event) => {
  // We don't want to cache everything, especially API calls
  if (event.request.method !== 'GET') return;
  
  event.respondWith(
    fetch(event.request).catch(() => {
      return caches.match(event.request);
    })
  );
});

// Background Sync (for potential future use)
self.addEventListener('sync', (event) => {
  if (event.tag === 'sync-location') {
    // Current browsers don't allow navigator.geolocation in SW
    // But we can keep the SW alive for a bit
    console.log('Background Sync event fired');
  }
});
