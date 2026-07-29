/**
 * SW URL-matching unit test — run with: node panel/sw.test.mjs
 *
 * Asserts the fetch handler's shouldPassToNetwork() logic never intercepts
 * /panel/* API calls. No test framework needed; uses Node built-in assert.
 *
 * This test must stay green: a regression here means the SW could serve stale
 * queue data as if it were live — a silent, pilot-breaking failure.
 */

import assert from "node:assert/strict";

// Inline the URL-matching predicate from sw.js (kept in sync manually;
// if the logic changes in sw.js, update here and bump CACHE_VERSION).
function shouldPassToNetwork(pathname, requestHostname, swHostname) {
  if (pathname.startsWith("/api/")) return true;    // proxy mode
  if (pathname.startsWith("/panel/")) return true;  // direct mode
  if (requestHostname !== swHostname) return true;
  return false;
}

const SW_HOST = "localhost"; // panel origin in dev / any prod origin

// --- Direct-mode API paths (/panel/*): MUST pass to network --------------
const directApiPaths = [
  "/panel/session/today",
  "/panel/queue",
  "/panel/next",
  "/panel/walkin",
  "/panel/emergency",
  "/panel/session/start",
  "/panel/session/close",
  "/panel/session/reopen",
  "/panel/session/cancel-today",
  "/panel/session/pause",
  "/panel/session/resume",
  "/panel/session/delay",
  "/panel/undo",
  "/panel/login",
  "/panel/entries/some-uuid/arrived",
  "/panel/entries/some-uuid/cancel",
  "/panel/settings",
];

for (const p of directApiPaths) {
  assert(
    shouldPassToNetwork(p, SW_HOST, SW_HOST),
    `FAIL: SW intercepted direct-mode path ${p}`,
  );
}

// --- Proxy-mode API paths (/api/*): MUST pass to network -----------------
// In proxy mode NEXT_PUBLIC_API_URL=/api, so all calls are same-origin /api/*.
// Without this check, shouldPassToNetwork would return false (same host, not
// /panel/*) and the SW would cache queue responses — silent stale-data bug.
const proxyApiPaths = [
  "/api/panel/session/today",
  "/api/panel/queue",
  "/api/panel/next",
  "/api/panel/walkin",
  "/api/panel/session/start",
  "/api/panel/session/close",
  "/api/panel/session/reopen",
  "/api/panel/undo",
  "/api/panel/login",
  "/api/panel/entries/some-uuid/arrived",
  "/api/healthz",
];

for (const p of proxyApiPaths) {
  assert(
    shouldPassToNetwork(p, SW_HOST, SW_HOST),
    `FAIL: SW intercepted proxy-mode path ${p} — /api/* must never be cached`,
  );
}

const apiPaths = [...directApiPaths, ...proxyApiPaths];

// --- Cross-origin (backend on different host): MUST pass through ----------
assert(
  shouldPassToNetwork("/panel/session/today", "api.backend.host", SW_HOST),
  "FAIL: cross-origin /panel/* should pass through",
);
assert(
  shouldPassToNetwork("/healthz", "backend.internal", SW_HOST),
  "FAIL: cross-origin healthz should pass through",
);

// --- Static shell assets: SW SHOULD intercept (cache-first) ---------------
const shellPaths = [
  "/",
  "/login",
  "/settings",
  "/manifest.webmanifest",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
];

for (const p of shellPaths) {
  assert(
    !shouldPassToNetwork(p, SW_HOST, SW_HOST),
    `FAIL: SW should intercept shell asset ${p}`,
  );
}

console.log(`✓  ${directApiPaths.length} direct-mode /panel/* paths pass through`);
console.log(`✓  ${proxyApiPaths.length} proxy-mode /api/* paths pass through`);
console.log(`✓  ${shellPaths.length} shell assets intercepted by SW`);
console.log("✓  Cross-origin requests pass through");
