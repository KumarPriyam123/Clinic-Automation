/* ClinicQ panel service worker.
 *
 * Strategy is deliberately small (CLAUDE.md: no over-building):
 *  - App shell (navigation + static assets): cache-first with background update,
 *    so the panel launches instantly and installs as a PWA.
 *  - API calls (/panel/*): NEVER cached here — the live queue owns its own
 *    freshness (4s poll) and its offline fallback (last snapshot in
 *    localStorage). Caching queue responses in the SW would risk showing a stale
 *    queue as if live. So we just pass them through.
 *
 * IMPORTANT: bump CACHE_VERSION on every deploy so the activate handler evicts
 * the stale shell immediately.  A stale cached bundle is indistinguishable from
 * live data and is a silent pilot-breaking failure (see WA_ROUNDTRIP.md).
 */
const CACHE_VERSION = "v3";
const CACHE = `clinicq-shell-${CACHE_VERSION}`;
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

/**
 * Returns true when this request must bypass the cache and go straight to the
 * network.  Exported as a named function so sw.test.mjs can assert it without
 * a real SW environment.
 *
 * Rules (in priority order):
 *  1. /api/* — proxy mode: same-origin rewrites from Next.js; must never cache.
 *  2. /panel/* — direct mode: NEXT_PUBLIC_API_URL pointing at the backend.
 *  3. Cross-origin — absolute backend URL; let the backend handle its own caching.
 *
 * Both /api/* and /panel/* must be listed.  In proxy mode the browser only
 * ever sends /api/* (same-origin), so the cross-origin check would not fire.
 */
function shouldPassToNetwork(pathname, requestHostname, swHostname) {
  if (pathname.startsWith("/api/")) return true;    // proxy mode
  if (pathname.startsWith("/panel/")) return true;  // direct mode
  if (requestHostname !== swHostname) return true;
  return false;
}

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;

  const url = new URL(req.url);
  // API traffic: pass straight to network. See shouldPassToNetwork() above.
  if (shouldPassToNetwork(url.pathname, url.hostname, self.location.hostname)) return;

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
