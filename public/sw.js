const CACHE_NAME = "nursing-exam-cache-v1";
const STATIC_ASSETS = [
  "/css/app.css",
  "/js/common.js",
  "/manifest.json"
];

self.addEventListener("install", event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(STATIC_ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys().then(keys => Promise.all(
      keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k))
    ))
  );
  self.clients.claim();
});

self.addEventListener("fetch", event => {
  const url = new URL(event.request.url);
  // Do not cache API or dynamic HTML navigations
  if (url.pathname.startsWith("/api/") || event.request.method !== "GET") {
    return;
  }
  // Cache first for static CSS/JS/Fonts
  if (url.pathname.startsWith("/css/") || url.pathname.startsWith("/js/")) {
    event.respondWith(
      caches.match(event.request).then(cached => {
        return cached || fetch(event.request).then(resp => {
          if (resp.status === 200) {
            const clone = resp.clone();
            caches.open(CACHE_NAME).then(c => c.put(event.request, clone));
          }
          return resp;
        });
      })
    );
  }
});
