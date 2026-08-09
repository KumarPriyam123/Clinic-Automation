/**
 * Which session does the panel act on?
 *
 * These two functions encode one invariant, and it is a patient-safety
 * invariant rather than a UI nicety:
 *
 *   SELECTION IS USER INTENT. Adoption of a server snapshot may RESOLVE an
 *   unresolved selection; it may never RETARGET a resolved one.
 *
 * Before this existed, `useQueue.adopt()` called `setSessionId(snapshot.session.id)`
 * unconditionally, and the panel derived every mutation's target from the
 * adopted snapshot (`snap.session.id`). Two consequences, both live-queue bugs:
 *
 *  1. An in-flight `/queue?session_id=A` that resolved *after* the user switched
 *     away wrote A back over the new selection. The effect then re-ran, polled
 *     immediately, and the two responses flipped the selection back and forth
 *     indefinitely — the observed ~1.8 req/s with two ids alternating.
 *
 *  2. Because mutations read the adopted id, whichever response landed last
 *     decided which session NEXT served. That is serving a patient from the
 *     wrong session, which is the worst thing this product can do.
 *
 * Kept in its own module, free of React, so the rule can be tested directly.
 * Mirrored by panel/session-target.test.mjs; scripts/check_mirrors.sh fails if
 * the two drift apart.
 */

/**
 * May a snapshot carrying `incomingId` be adopted while `selectedId` is chosen?
 *
 * `null` incoming means a day with no session at all — a legitimate payload for
 * the selected day, so it is accepted rather than treated as a mismatch.
 */
export function shouldAdopt(selectedId: string | null, incomingId: string | null): boolean {
  if (selectedId === null) return true; // nothing chosen yet; the day route picks
  if (incomingId === null) return true; // "no session that day" for this selection
  return incomingId === selectedId; // otherwise it is stale or for another session
}

/**
 * The selection after adopting a snapshot carrying `incomingId`.
 *
 * Resolve-only. Once the user (or the day route on their behalf) has settled on
 * a session, no arriving response may move it; only an explicit selection can.
 */
export function nextSelectedId(
  selectedId: string | null,
  incomingId: string | null,
): string | null {
  if (selectedId === null) return incomingId;
  return selectedId;
}
