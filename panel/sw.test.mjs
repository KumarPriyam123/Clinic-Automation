/**
 * SW request-classification unit test — run with: node panel/sw.test.mjs
 *
 * Asserts the fetch handler routes each request class to the right strategy.
 * No test framework; Node built-in assert.
 *
 * This test must stay green. A regression in isNetworkOnly() means the SW can
 * serve a stale queue as if it were live; a regression in isDocumentLike()
 * means a cached document can point the app at chunk names that no longer
 * exist. Both are silent, and both have happened.
 */

import assert from "node:assert/strict";

// Inlined from public/sw.js — kept in sync by hand. A service worker cannot be
// imported here (it runs in its own global scope), so if you change a predicate
// there, change it here too.
function isNetworkOnly(pathname, requestHostname, swHostname) {
  if (pathname.startsWith("/api/")) return true; // proxy mode
  if (pathname.startsWith("/panel/")) return true; // direct mode
  if (pathname === "/healthz") return true;
  if (requestHostname !== swHostname) return true; // absolute backend URL
  return false;
}

function isStaticAsset(pathname) {
  return pathname.startsWith("/_next/static/");
}

function isDocumentLike(mode, accept, hasRscParam, hasRscHeader) {
  if (mode === "navigate") return true;
  if (hasRscHeader) return true;
  if (hasRscParam) return true;
  if (accept && accept.includes("text/html")) return true;
  return false;
}

const SW_HOST = "app.clinicq.kpriyam.me";
let checks = 0;
const ok = (cond, msg) => {
  checks++;
  assert(cond, msg);
};

// --- API: never cached, in EVERY deployment shape ------------------------- //
// Direct mode — NEXT_PUBLIC_API_URL points at this origin.
const directApiPaths = [
  "/panel/session/today",
  "/panel/session/day",
  "/panel/queue",
  "/panel/next",
  "/panel/walkin",
  "/panel/emergency",
  "/panel/session/start",
  "/panel/session/pause",
  "/panel/session/resume",
  "/panel/session/close",
  "/panel/session/reopen",
  "/panel/session/cancel-today",
  "/panel/session/delay",
  "/panel/undo",
  "/panel/login",
  "/panel/settings",
  "/panel/entries/some-uuid/arrived",
  "/panel/entries/some-uuid/cancel",
  "/panel/entries/some-uuid/call-now",
];
for (const p of directApiPaths) {
  ok(isNetworkOnly(p, SW_HOST, SW_HOST), `direct-mode API cached: ${p}`);
}

// Proxy mode — same-origin /api/* rewrite. This matcher silently broke once
// when the proxy was introduced: same host and not /panel/*, so the old logic
// fell through to "cache it".
const proxyApiPaths = [
  "/api/panel/session/today",
  "/api/panel/queue",
  "/api/panel/next",
  "/api/panel/walkin",
  "/api/panel/session/close",
  "/api/panel/undo",
  "/api/panel/login",
  "/api/panel/entries/some-uuid/arrived",
  "/api/healthz",
];
for (const p of proxyApiPaths) {
  ok(isNetworkOnly(p, SW_HOST, SW_HOST), `proxy-mode API cached: ${p}`);
}

// Absolute backend URL on another host.
ok(isNetworkOnly("/panel/session/today", "clinicq.kpriyam.me", SW_HOST), "cross-origin API cached");
ok(isNetworkOnly("/healthz", "clinicq.kpriyam.me", SW_HOST), "cross-origin healthz cached");
ok(isNetworkOnly("/healthz", SW_HOST, SW_HOST), "same-origin healthz cached");

// --- Static build output: cache-first is safe (content-hashed) ------------ //
const staticPaths = [
  "/_next/static/chunks/app/page-abc123.js",
  "/_next/static/chunks/main-app-def456.js",
  "/_next/static/css/app/layout-789.css",
  "/_next/static/media/noto-sans.woff2",
];
for (const p of staticPaths) {
  ok(!isNetworkOnly(p, SW_HOST, SW_HOST), `static asset treated as API: ${p}`);
  ok(isStaticAsset(p), `static asset not recognised: ${p}`);
}

// --- Documents and RSC: must NOT be classified as static ------------------ //
const shellPaths = ["/", "/login", "/settings"];
for (const p of shellPaths) {
  ok(!isStaticAsset(p), `document classified as hashed static: ${p}`);
  ok(!isNetworkOnly(p, SW_HOST, SW_HOST), `document treated as API: ${p}`);
}

// A navigation is document-like.
ok(isDocumentLike("navigate", null, false, false), "navigation not document-like");
// Next's RSC payloads arrive as a header, or as an _rsc query param on prefetch.
ok(isDocumentLike("cors", null, false, true), "RSC header not document-like");
ok(isDocumentLike("cors", null, true, false), "_rsc param not document-like");
// An HTML accept header counts even without navigate mode.
ok(isDocumentLike("cors", "text/html,application/xhtml+xml", false, false), "HTML accept missed");

// Hashed assets must NOT be document-like, or they lose cache-first.
ok(!isDocumentLike("cors", "*/*", false, false), "generic asset wrongly document-like");
ok(!isDocumentLike("no-cors", "image/png", false, false), "image wrongly document-like");

// --- Manifest and icons: cache-first, not API, not document --------------- //
for (const p of ["/manifest.webmanifest", "/icons/icon-192.png", "/apple-touch-icon.png"]) {
  ok(!isNetworkOnly(p, SW_HOST, SW_HOST), `asset treated as API: ${p}`);
  ok(!isStaticAsset(p), `non-build asset claimed as /_next/static: ${p}`);
}

console.log(`✓  ${directApiPaths.length} direct-mode /panel/* paths are network-only`);
console.log(`✓  ${proxyApiPaths.length} proxy-mode /api/* paths are network-only`);
console.log("✓  cross-origin backend requests are network-only");
console.log(`✓  ${staticPaths.length} hashed build assets are cache-first`);
console.log("✓  documents and RSC payloads are network-first");
console.log(`✓  ${checks} assertions passed`);
