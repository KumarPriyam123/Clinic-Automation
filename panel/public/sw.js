/* ClinicQ panel service worker.
 *
 * WHY THIS IS SHAPED THE WAY IT IS
 *
 * Serving stale code has now bitten this project three times: once showing
 * two-day-old session data while the database was correct, and twice during P8
 * handing back JS chunks from a previous build — which cost two false
 * diagnoses. A receptionist running last week's JS against this week's API gets
 * no signal that anything is wrong, and neither does the developer debugging
 * it. Freshness is therefore a correctness property here, not an optimisation.
 *
 * The strategy is per request class, and each class is deliberate:
 *
 *   /_next/static/**   cache-first   Content-hashed, so a hit is by definition
 *                                    the right bytes. Safe and worth caching.
 *   documents + RSC    network-first Not hashed. A stale document references
 *                                    chunk names that no longer exist — that is
 *                                    the actual bug. Cache is fallback only.
 *   API                network-only  Never cached, in either URL shape. A stale
 *                                    queue rendered as live is pilot-breaking.
 *   other same-origin  cache-first   Icons, manifest. Versioned by cache name.
 *
 * The cache name comes from the build ID (see next.config.mjs), so every deploy
 * lands in a fresh cache and activate() evicts the rest. There is no constant
 * to remember to bump.
 *
 * Offline behaviour is preserved on purpose (CLAUDE.md: offline = cached
 * read-only queue + reconnecting bar). Documents fall back to cache, the shell
 * is precached, and the queue's own last snapshot lives in localStorage.
 */

// SwRegister registers "/sw.js?v=<BUILD_ID>". Reading it back here ties the
// cache name to the build without a second source of truth.
const VERSION = new URL(self.location.href).searchParams.get("v") || "dev";
const CACHE = `clinicq-${VERSION}`;

const SHELL = ["/", "/login", "/settings", "/manifest.webmanifest", "/icons/icon-192.png"];

/* --------------------------------------------------------------------------
 * Request classification.
 *
 * These four predicates are pure and are mirrored by panel/sw.test.mjs. If you
 * change one, change it there too — the API matcher silently broke once when
 * the /api proxy was added, which is why both URL shapes are tested.
 * ----------------------------------------------------------------------- */

/**
 * Must go straight to the network and never touch the cache.
 *
 * Three shapes, all of which are real deployments:
 *   /api/*     proxy mode — same-origin rewrite through next.config.mjs
 *   /panel/*   direct mode — NEXT_PUBLIC_API_URL points at this origin
 *   any cross-origin request — direct mode against the droplet
 */
function isNetworkOnly(pathname, requestHostname, swHostname) {
  if (pathname.startsWith("/api/")) return true; // proxy mode
  if (pathname.startsWith("/panel/")) return true; // direct mode
  if (pathname === "/healthz") return true;
  if (requestHostname !== swHostname) return true; // absolute backend URL
  return false;
}

/** Content-hashed build output: a cache hit is always the correct bytes. */
function isStaticAsset(pathname) {
  return pathname.startsWith("/_next/static/");
}

/**
 * A document or an RSC payload — anything whose staleness can point the app at
 * chunk names that no longer exist.
 */
function isDocumentLike(mode, accept, hasRscParam, hasRscHeader) {
  if (mode === "navigate") return true;
  if (hasRscHeader) return true;
  if (hasRscParam) return true;
  if (accept && accept.includes("text/html")) return true;
  return false;
}

/* -------------------------------------------------------------------------- */

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then(async (cache) => {
      // Best-effort: one missing URL must not fail the whole install and leave
      // the old worker in charge, which is the failure this file exists to fix.
      await Promise.all(SHELL.map((u) => cache.add(u).catch(() => {})));
      await self.skipWaiting();
    }),
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

async function cacheFirst(req) {
  const cached = await caches.match(req);
  if (cached) return cached;
  const res = await fetch(req);
  if (res && res.ok) {
    const copy = res.clone();
    caches.open(CACHE).then((c) => c.put(req, copy));
  }
  return res;
}

async function networkFirst(req) {
  try {
    const res = await fetch(req);
    if (res && res.ok) {
      const copy = res.clone();
      caches.open(CACHE).then((c) => c.put(req, copy));
    }
    return res;
  } catch (err) {
    // Offline: serve the last good copy, then the app shell. The queue itself
    // renders read-only from its localStorage snapshot with the reconnecting
    // bar showing, so this path keeps documented offline behaviour intact.
    const cached = await caches.match(req);
    if (cached) return cached;
    const shell = await caches.match("/");
    if (shell) return shell;
    throw err;
  }
}

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;

  const url = new URL(req.url);

  // API: pass through untouched. Not respondWith — the browser handles it.
  if (isNetworkOnly(url.pathname, url.hostname, self.location.hostname)) return;

  if (isStaticAsset(url.pathname)) {
    event.respondWith(cacheFirst(req));
    return;
  }

  const documentLike = isDocumentLike(
    req.mode,
    req.headers.get("accept"),
    url.searchParams.has("_rsc"),
    Boolean(req.headers.get("RSC")),
  );

  event.respondWith(documentLike ? networkFirst(req) : cacheFirst(req));
});
