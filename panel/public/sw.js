/* ClinicQ panel service worker.
 *
 * Strategy is deliberately small (CLAUDE.md: no over-building):
 *  - App shell (navigation + static assets): cache-first with background update,
 *    so the panel launches instantly and installs as a PWA.
 *  - API calls (/panel/*): NEVER cached here — the live queue owns its own
 *    freshness (4s poll) and its offline fallback (last snapshot in
 *    localStorage). Caching queue responses in the SW would risk showing a stale
 *    queue as if live. So we just pass them through.
 */
const CACHE = "clinicq-shell-v1";
const SHELL = ["/", "/login", "/settings", "/manifest.webmanifest", "/icons/icon-192.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;

  const url = new URL(req.url);
  // Let API traffic go straight to the network (queue handles its own offline).
  if (url.pathname.startsWith("/panel/") || url.hostname !== self.location.hostname) return;

  // Navigations: network-first so fresh HTML wins, fall back to cached shell.
  if (req.mode === "navigate") {
    event.respondWith(
      fetch(req)
        .then((res) => {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(req, copy));
          return res;
        })
        .catch(() => caches.match(req).then((m) => m || caches.match("/"))),
    );
    return;
  }

  // Static assets: cache-first, refresh in the background.
  event.respondWith(
    caches.match(req).then(
      (cached) =>
        cached ||
        fetch(req).then((res) => {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(req, copy));
          return res;
        }),
    ),
  );
});
