"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import * as api from "./api";
import { chime } from "./sound";
import type { QueueSnapshot } from "./types";

const CACHE_KEY = "clinicq.lastQueue";
const POLL_MS = 4000;

function loadCache(): QueueSnapshot | null {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem(CACHE_KEY);
  return raw ? (JSON.parse(raw) as QueueSnapshot) : null;
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
  offline: boolean;
  loading: boolean;
  newFlash: number; // increments when a new patient lands (for a badge pulse)
  /** Run a mutation, adopt its snapshot, and surface a 5s undo affordance. */
  run: (fn: () => Promise<QueueSnapshot>) => Promise<void>;
  doUndo: () => Promise<void>;
  undoVisible: boolean;
  error: string | null;
  clearError: () => void;
}

export function useQueue(): QueueController {
  const [snap, setSnap] = useState<QueueSnapshot | null>(() => loadCache());
  const [sessionId, setSessionId] = useState<string | null>(
    () => loadCache()?.session?.id ?? null,
  );
  const [offline, setOffline] = useState(false);
  const [loading, setLoading] = useState(true);
  const [newFlash, setNewFlash] = useState(0);
  const [undoVisible, setUndoVisible] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const prevSig = useRef<string>(arrivalSignature(loadCache()));
  const undoTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mutating = useRef(false);

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
    setSnap(next);
    if (next.session) setSessionId(next.session.id);
    if (typeof window !== "undefined") {
      window.localStorage.setItem(CACHE_KEY, JSON.stringify(next));
    }
  }, []);

  const poll = useCallback(async () => {
    if (mutating.current) return;
    try {
      const data = sessionId
        ? await api.fetchQueue(sessionId)
        : await api.fetchToday();
      // fetchQueue drops the session list; keep the one today gave us
      if (sessionId && snap?.sessions) data.sessions = snap.sessions;
      setOffline(false);
      adopt(data, true);
    } catch (e) {
      if (e instanceof api.ApiError && e.status === 401) return;
      setOffline(true); // network down → keep showing cached, show reconnect bar
    } finally {
      setLoading(false);
    }
  }, [sessionId, snap?.sessions, adopt]);

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
        adopt(data, false);
        if (data.can_undo) {
          setUndoVisible(true);
          if (undoTimer.current) clearTimeout(undoTimer.current);
          undoTimer.current = setTimeout(() => setUndoVisible(false), 5000);
        }
      } catch (e) {
        if (e instanceof api.ApiError) {
          if (e.status === 401) return;
          const d = e.detail as { message?: string; reason?: string } | null;
          setError(d?.message ?? (typeof e.detail === "string" ? e.detail : "कुछ गड़बड़ / error"));
        } else {
          setOffline(true);
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
    offline,
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
