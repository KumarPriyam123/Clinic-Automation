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
// if the logic changes in sw.js, update here and the CACHE_VERSION).
function shouldPassToNetwork(pathname, requestHostname, swHostname) {
  if (pathname.startsWith("/panel/")) return true;
  if (requestHostname !== swHostname) return true;
  return false;
}

const SW_HOST = "localhost"; // panel origin in dev / any prod origin

// --- API paths: MUST pass to network (never intercepted) -----------------
const apiPaths = [
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

for (const p of apiPaths) {
  assert(
    shouldPassToNetwork(p, SW_HOST, SW_HOST),
    `FAIL: SW intercepted API path ${p} — must never cache /panel/* responses`,
  );
}

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

console.log(`✓  ${apiPaths.length} API paths pass through — SW never caches /panel/* responses`);
console.log(`✓  ${shellPaths.length} shell assets intercepted by SW`);
console.log("✓  Cross-origin requests pass through");
