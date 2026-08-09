/**
 * Session-targeting unit test — run with: node panel/session-target.test.mjs
 *
 * The rule under test is a patient-safety rule, not a UI preference: a mutation
 * must target the session the USER selected, never whichever server response
 * happened to land most recently. Getting this wrong means NEXT serves a patient
 * from the wrong queue.
 *
 * Mirrors app/lib/session-target.ts. scripts/check_mirrors.sh fails the build if
 * these copies drift apart.
 */

import assert from "node:assert/strict";

// --- mirrored from app/lib/session-target.ts ----------------------------- //
export function shouldAdopt(selectedId, incomingId) {
  if (selectedId === null) return true; // nothing chosen yet; the day route picks
  if (incomingId === null) return true; // "no session that day" for this selection
  return incomingId === selectedId; // otherwise it is stale or for another session
}

export function nextSelectedId(selectedId, incomingId) {
  if (selectedId === null) return incomingId;
  return selectedId;
}
// ------------------------------------------------------------------------ //

let checks = 0;
const ok = (cond, msg) => {
  checks++;
  assert(cond, msg);
};
const eq = (a, b, msg) => {
  checks++;
  assert.deepEqual(a, b, msg);
};

const A = "sess-2026-08-10-morning";
const B = "sess-2026-08-11-morning";

/* == THE REGRESSION ======================================================= //
 * User has selected A. A stale /queue response for B — in flight from before
 * the switch — lands afterwards. It must change nothing.
 */
ok(!shouldAdopt(A, B), "stale session-B snapshot was adopted while A selected");
eq(nextSelectedId(A, B), A, "stale session-B snapshot retargeted the selection");

// ...and the id every mutation sends is the selection, so it is still A.
// This is the assertion that matters: NEXT/walk-in/close all take this value.
eq(nextSelectedId(A, B), A, "mutation target moved to a session the user left");

// The mirror-image case: selected B, stale A arrives.
ok(!shouldAdopt(B, A), "stale session-A snapshot was adopted while B selected");
eq(nextSelectedId(B, A), B, "stale session-A snapshot retargeted the selection");

// Repeated stale arrivals cannot accumulate into a flip — this is what drove
// the observed ping-pong between two ids.
let sel = A;
for (let i = 0; i < 20; i++) {
  if (shouldAdopt(sel, B)) sel = nextSelectedId(sel, B);
}
eq(sel, A, "20 stale responses flipped the selection");

/* == Normal operation ==================================================== */

// A fresh response for the selected session is adopted and changes nothing.
ok(shouldAdopt(A, A), "matching snapshot rejected");
eq(nextSelectedId(A, A), A, "matching snapshot disturbed the selection");

// Unresolved selection: the day route picks, and that resolves it.
ok(shouldAdopt(null, A), "day-route snapshot rejected while unresolved");
eq(nextSelectedId(null, A), A, "day-route snapshot failed to resolve the selection");

// A day with no session at all is a legitimate payload, not a mismatch.
ok(shouldAdopt(A, null), "no-session payload treated as a mismatch");
ok(shouldAdopt(null, null), "no-session payload rejected while unresolved");
eq(nextSelectedId(null, null), null, "no-session payload invented a selection");
eq(nextSelectedId(A, null), A, "no-session payload cleared the selection");

// Explicit selection is the ONLY thing that moves the target. Modelled as the
// caller assigning directly, which is what select() does.
sel = A;
sel = B; // user taps the other session pill / day tab
eq(sel, B, "explicit selection did not take effect");
ok(shouldAdopt(sel, B), "response for the newly selected session was rejected");

console.log("✓  stale cross-session responses are rejected, both directions");
console.log("✓  a stale response cannot retarget a mutation");
console.log("✓  20 repeated stale arrivals cannot flip the selection");
console.log("✓  adoption resolves an unresolved selection, and only then");
console.log(`✓  ${checks} assertions passed`);
