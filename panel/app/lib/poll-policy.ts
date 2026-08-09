/**
 * When may the queue poller issue a request?
 *
 * Extracted from the effect body so the rules can be executed by a test rather
 * than only reasoned about. Measured before this existed: ~300 requests in
 * ~170s (≈1.8/s) against an intended 0.25/s, with two session ids alternating,
 * because every day/session switch left its predecessor running.
 *
 * Mirrored by panel/poll-policy.test.mjs; scripts/check_mirrors.sh fails the
 * build if they drift.
 */

export const POLL_MS = 4000;

/**
 * Interval polling is for today only.
 *
 * A future-dated session cannot change second to second — nobody is being
 * called from it — so it is fetched once when opened and then left alone.
 */
export function pollsOnInterval(day: string, today: string): boolean {
  return day === today;
}

/**
 * Whether a scheduled tick should actually reach the network.
 *
 * `hidden` is the overnight case: a panel left open on a phone must not spend a
 * clinic's mobile data until someone looks at it again.
 * `mutating` is the case where a mutation already owns the snapshot.
 */
export function shouldIssueRequest(cancelled: boolean, mutating: boolean, hidden: boolean): boolean {
  if (cancelled) return false;
  if (mutating) return false;
  if (hidden) return false;
  return true;
}
