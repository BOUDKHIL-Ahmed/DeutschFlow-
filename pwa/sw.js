const CACHE_NAME = "deutschflow-pwa-v1";
const SHELL_ASSETS = [
  "/",
  "/manifest.json",
  "/static/styles.css",
  "/static/app.js",
  "/static/icon-192.png",
  "/static/icon-512.png",
  "/static/apple-touch-icon.png"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (url.pathname.startsWith("/api/")) {
    return; // Always live network for synchronized SQLite & AI endpoints
  }
  event.respondWith(
    fetch(event.request)
      .then((resp) => {
        if (resp.ok && event.request.method === "GET") {
          const copy = resp.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy));
        }
        return resp;
      })
      .catch(() => caches.match(event.request))
  );
});
