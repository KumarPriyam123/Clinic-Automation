"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import * as api from "./api";
import { chime } from "./sound";
import type { QueueSnapshot } from "./types";
import type { StringKey } from "@/lib/i18n";

/**
 * Backend rejection `reason` → panel dictionary key.
 *
 * The API's own `message` field is a bilingual "hi / en" string. Rendering it
 * would put both languages on a screen the user just set to one, so the panel
 * translates the machine-readable reason itself and never displays server prose.
 */
const REASON_STRING: Record<string, StringKey> = {
  cap: "sessionFull",
  closed: "sessionClosedNote",
  past_end: "sessionTimePassed",
  not_today: "viewOnly",
  session_ended: "sessionTimePassed",
  invalid_transition: "invalidTransition",
};

const CACHE_KEY = "clinicq.lastQueue";
const POLL_MS = 4000;
export const STALE_MS = 10 * 60 * 1000; // 10 min — beyond this show error, not data

/** Today's date in IST as "YYYY-MM-DD" — matches the session.date field. */
export function todayIST(): string {
  return new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });
}

/** `days` from today, in IST, as "YYYY-MM-DD". */
export function dayIST(offset: number): string {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() + offset);
  return d.toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });
}

/**
 * Load the last cached snapshot, discarding it if the session's date doesn't
 * match today in IST.  A cross-day cache is the primary cause of stale data:
 * sessionId from yesterday's snapshot drives polls to the wrong session.
 */
function loadCache(): QueueSnapshot | null {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem(CACHE_KEY);
  if (!raw) return null;
  const snap = JSON.parse(raw) as QueueSnapshot;
  if (snap.session?.date && snap.session.date !== todayIST()) {
    // Cross-day cache: discard so first poll calls fetchToday() for correct session.
    window.localStorage.removeItem(CACHE_KEY);
    return null;
  }
  return snap;
}

/** Count entries that represent a fresh patient landing (booking or arrival). */
function arrivalSignature(snap: QueueSnapshot | null): string {
  if (!snap) return "";
  return snap.entries
    .filter((e) => e.status === "booked" || e.status === "arrived")
    .map((e) => e.entry_id)
    .sort()
    .join(",");
}

export interface QueueController {
  snap: QueueSnapshot | null;
  sessionId: string | null;
  setSessionId: (id: string) => void;
  /** The day being viewed, ISO "YYYY-MM-DD" in IST. */
  day: string;
  setDay: (date: string) => void;
  offline: boolean;
  /** Unix ms of the last successful poll. null until first success. */
  lastLiveAt: number | null;
  loading: boolean;
  newFlash: number; // increments when a new patient lands (for a badge pulse)
  /** Run a mutation, adopt its snapshot, and surface a 5s undo affordance. */
  run: (fn: () => Promise<QueueSnapshot>) => Promise<void>;
  doUndo: () => Promise<void>;
  undoVisible: boolean;
  /** Dictionary key, not prose — the view resolves it in the current locale. */
  error: StringKey | null;
  clearError: () => void;
}

export function useQueue(): QueueController {
  const [snap, setSnap] = useState<QueueSnapshot | null>(() => loadCache());
  const [sessionId, setSessionId] = useState<string | null>(
    () => loadCache()?.session?.id ?? null,
  );
  const [day, setDayState] = useState<string>(() => todayIST());
  const [offline, setOffline] = useState(false);
  const [lastLiveAt, setLastLiveAt] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [newFlash, setNewFlash] = useState(0);
  const [undoVisible, setUndoVisible] = useState(false);
  const [error, setError] = useState<StringKey | null>(null);

  const prevSig = useRef<string>(arrivalSignature(loadCache()));
  const undoTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mutating = useRef(false);
  const snapRef = useRef<QueueSnapshot | null>(loadCache());

  const adopt = useCallback((next: QueueSnapshot, fromPoll: boolean) => {
    // detect a newly-landed patient only during background polling
    const sig = arrivalSignature(next);
    if (fromPoll && prevSig.current && sig !== prevSig.current) {
      const before = new Set(prevSig.current.split(",").filter(Boolean));
      const grew = sig.split(",").filter(Boolean).some((id) => !before.has(id));
      if (grew) {
        chime();
        setNewFlash((n) => n + 1);
      }
    }
    prevSig.current = sig;
    // /queue and EVERY mutation response omit `sessions` and `upcoming` — only
    // the day routes carry them. Carry the last known values forward or the
    // session switcher and the tomorrow badge disappear after the first NEXT.
    const prev = snapRef.current;
    const merged: QueueSnapshot = {
      ...next,
      sessions: next.sessions ?? prev?.sessions,
      upcoming: next.upcoming ?? prev?.upcoming,
    };
    snapRef.current = merged;
    setSnap(merged);
    if (merged.session) setSessionId(merged.session.id);
    if (typeof window !== "undefined") {
      window.localStorage.setItem(CACHE_KEY, JSON.stringify(merged));
    }
  }, []);

  const poll = useCallback(async () => {
    if (mutating.current) return;
    try {
      const data = sessionId
        ? await api.fetchQueue(sessionId)
        : day === todayIST()
          ? await api.fetchToday()
          : await api.fetchDay(day);
      setOffline(false);
      setLastLiveAt(Date.now());
      adopt(data, true);
    } catch (e) {
      if (e instanceof api.ApiError && e.status === 401) return;
      // Either the request never landed (NetworkError) or the server refused it
      // (5xx). Both mean the same thing for the queue on screen: it is no longer
      // live. `offline` is that fact, not a claim about the radio.
      setOffline(true);
    } finally {
      setLoading(false);
    }
  }, [sessionId, day, adopt]);

  /** Switch the day in view. Clearing sessionId lets the day route pick. */
  const setDay = useCallback((next: string) => {
    setDayState(next);
    setSessionId(null);
  }, []);

  useEffect(() => {
    poll();
    const id = setInterval(poll, POLL_MS);
    return () => clearInterval(id);
  }, [poll]);

  const run = useCallback(
    async (fn: () => Promise<QueueSnapshot>) => {
      mutating.current = true;
      try {
        const data = await fn();
        setOffline(false);
        setLastLiveAt(Date.now());
        adopt(data, false);
        if (data.can_undo) {
          setUndoVisible(true);
          if (undoTimer.current) clearTimeout(undoTimer.current);
          undoTimer.current = setTimeout(() => setUndoVisible(false), 5000);
        }
      } catch (e) {
        if (e instanceof api.NetworkError) {
          // Request never left the browser — the queue is not live any more.
          setOffline(true);
        } else if (e instanceof api.ApiError) {
          if (e.status === 401) return;
          const d = e.detail as { reason?: string } | null;
          const key = d?.reason ? REASON_STRING[d.reason] : undefined;
          setError(key ?? "genericError");
        } else {
          // A bug in our own code, not a transport failure. Say something true
          // and generic rather than blaming the network.
          setError("genericError");
        }
      } finally {
        mutating.current = false;
      }
    },
    [adopt],
  );

  const doUndo = useCallback(async () => {
    setUndoVisible(false);
    if (undoTimer.current) clearTimeout(undoTimer.current);
    await run(() => api.undo());
  }, [run]);

  return {
    snap,
    sessionId,
    setSessionId,
    day,
    setDay,
    offline,
    lastLiveAt,
    loading,
    newFlash,
    run,
    doUndo,
    undoVisible,
    error,
    clearError: () => setError(null),
  };
}

/** A 1-second ticker for live timers (consult clock, grace countdown). */
export function useTick(active = true): number {
  const [, force] = useState(0);
  useEffect(() => {
    if (!active) return;
    const id = setInterval(() => force((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, [active]);
  return Date.now();
}
