/**
 * Poller behaviour test — run with: node panel/poll-policy.test.mjs
 *
 * Simulates the React effect lifecycle (mount, cleanup-before-re-run on a dep
 * change) around the REAL policy functions and counts the requests that would
 * be issued. This is the closest thing to the DevTools measurement that can run
 * in CI: before the fix, ~300 requests landed in ~170s against an intended
 * 0.25/s, with two session ids alternating forever.
 *
 * The policy functions below mirror app/lib/poll-policy.ts;
 * scripts/check_mirrors.sh fails the build if they drift.
 */

import assert from "node:assert/strict";

// --- mirrored from app/lib/poll-policy.ts -------------------------------- //
export function pollsOnInterval(day, today) {
  return day === today;
}

export function shouldIssueRequest(cancelled, mutating, hidden) {
  if (cancelled) return false;
  if (mutating) return false;
  if (hidden) return false;
  return true;
}
// ------------------------------------------------------------------------ //

const POLL_MS = 4000;
const TODAY = "2026-08-10";
const TOMORROW = "2026-08-11";

let checks = 0;
const eq = (a, b, msg) => {
  checks++;
  assert.equal(a, b, msg);
};

/**
 * Minimal model of the effect in useQueue.ts: one live instance at a time,
 * cleanup runs before the next mount, an interval only when the policy allows
 * it, and each tick gated by shouldIssueRequest.
 */
function makeHarness() {
  const requests = [];
  let now = 0;
  let live = null; // the single mounted effect
  let hidden = false;

  const mount = ({ day, sessionId }) => {
    if (live) live.cleanup();
    const onInterval = pollsOnInterval(day, TODAY);
    const inst = {
      day,
      sessionId,
      cancelled: false,
      nextDue: onInterval ? now + POLL_MS : Infinity,
      onInterval,
      cleanup() {
        this.cancelled = true;
        this.nextDue = Infinity;
      },
    };
    live = inst;
    tick(inst); // effects fetch immediately on mount
  };

  const tick = (inst) => {
    if (!shouldIssueRequest(inst.cancelled, false, hidden)) return;
    requests.push({ at: now, day: inst.day, sessionId: inst.sessionId });
  };

  const advance = (ms) => {
    const end = now + ms;
    while (live && live.nextDue <= end) {
      now = live.nextDue;
      tick(live);
      live.nextDue = now + POLL_MS;
    }
    now = end;
  };

  const setHidden = (v) => {
    const wasHidden = hidden;
    hidden = v;
    if (!live) return;
    if (v) {
      live.nextDue = Infinity; // interval stopped, in-flight aborted
    } else if (wasHidden) {
      tick(live); // one immediate refetch on return...
      if (live.onInterval) live.nextDue = now + POLL_MS; // ...then normal cadence
    }
  };

  return {
    requests,
    mount,
    advance,
    setHidden,
    now: () => now,
    reset: () => {
      requests.length = 0;
    },
  };
}

/* == 20 rapid tab switches must not accumulate pollers =================== */
{
  const h = makeHarness();
  h.mount({ day: TODAY, sessionId: "A" });
  for (let i = 0; i < 20; i++) {
    h.mount({ day: TODAY, sessionId: i % 2 === 0 ? "B" : "A" });
    h.advance(50); // switches faster than the poll interval
  }
  h.reset();
  h.advance(60_000); // one quiet minute after the switching stops

  eq(h.requests.length, 15, "steady state is not exactly one request per 4s");
  const ids = [...new Set(h.requests.map((r) => r.sessionId))];
  eq(ids.length, 1, `more than one session polled in steady state: ${ids}`);
  eq(ids[0], "A", "polled a session other than the last one selected");
}

/* == Zero requests for a non-selected session ============================ */
{
  const h = makeHarness();
  h.mount({ day: TODAY, sessionId: "A" });
  h.advance(20_000);
  h.mount({ day: TODAY, sessionId: "B" });
  h.reset();
  h.advance(40_000);
  eq(
    h.requests.filter((r) => r.sessionId !== "B").length,
    0,
    "requests were still issued for the abandoned session",
  );
}

/* == Tomorrow: one fetch on open, no interval ============================ */
{
  const h = makeHarness();
  h.mount({ day: TOMORROW, sessionId: null });
  eq(h.requests.length, 1, "opening tomorrow did not fetch exactly once");
  h.advance(120_000); // two minutes
  eq(h.requests.length, 1, "tomorrow was polled on an interval");
  eq(pollsOnInterval(TOMORROW, TODAY), false, "tomorrow claims interval polling");
  eq(pollsOnInterval(TODAY, TODAY), true, "today does not poll on an interval");
}

/* == Hidden tab: zero requests, then one immediate refetch on return ===== */
{
  const h = makeHarness();
  h.mount({ day: TODAY, sessionId: "A" });
  h.advance(8_000);
  h.reset();

  h.setHidden(true);
  h.advance(8 * 60 * 60 * 1000); // left open overnight
  eq(h.requests.length, 0, "a hidden tab kept polling");

  h.setHidden(false);
  eq(h.requests.length, 1, "returning did not trigger exactly one refetch");

  h.reset();
  h.advance(12_000);
  eq(h.requests.length, 3, "normal cadence did not resume after returning");
}

/* == The gate itself ===================================================== */
eq(shouldIssueRequest(false, false, false), true, "a normal tick was blocked");
eq(shouldIssueRequest(true, false, false), false, "a cancelled effect issued a request");
eq(shouldIssueRequest(false, true, false), false, "polled while a mutation was in flight");
eq(shouldIssueRequest(false, false, true), false, "polled while the document was hidden");

console.log("✓  20 rapid switches settle to exactly one request per 4s");
console.log("✓  zero requests for any non-selected session");
console.log("✓  tomorrow fetches once on open, never on an interval");
console.log("✓  hidden tab issues nothing; returning refetches once, then resumes");
console.log(`✓  ${checks} assertions passed`);
