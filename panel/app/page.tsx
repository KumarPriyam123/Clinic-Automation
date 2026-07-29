"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import * as api from "./lib/api";
import { getClinic, getToken } from "./lib/api";
import { STRINGS } from "./lib/i18n";
import { armSound } from "./lib/sound";
import { useQueue, useTick } from "./lib/useQueue";
import type { QueueEntry, QueueSnapshot } from "./lib/types";
import { SessionBanner } from "./components/SessionBanner";
import { NowServing } from "./components/NowServing";
import { QueueRow } from "./components/QueueRow";
import { NextButton } from "./components/NextButton";
import { ActionSheet } from "./components/ActionSheet";
import { WalkinModal } from "./components/WalkinModal";
import { SessionControls } from "./components/SessionControls";
import { ErrorToast, OfflineBanner, ReconnectBar, StaleErrorScreen, UndoSnackbar } from "./components/Snackbar";
import { STALE_MS } from "./lib/useQueue";

export default function LiveQueue() {
  const router = useRouter();
  const [ready, setReady] = useState(false);
  const q = useQueue();
  const now = useTick(true);

  const [activeRow, setActiveRow] = useState<QueueEntry | null>(null);
  const [walkinOpen, setWalkinOpen] = useState(false);
  const [emergencyMode, setEmergencyMode] = useState(false);
  const [controlsOpen, setControlsOpen] = useState(false);

  useEffect(() => {
    if (!getToken()) router.replace("/login");
    else setReady(true);
  }, [router]);

  const clinic = getClinic();
  const session = q.snap?.session ?? null;
  const sid = session?.id ?? q.sessionId ?? null;
  const isOpen = session?.status === "open";

  // Stale-data guard: if we've been offline for >10min, hide the queue entirely.
  // A receptionist must never act on data that old.
  const snapshotAge = q.lastLiveAt !== null ? now - q.lastLiveAt : null;
  const isStale = q.offline && snapshotAge !== null && snapshotAge > STALE_MS;
  // First-load offline (never had a response): show reconnect bar, not stale banner.
  const isFirstLoadOffline = q.offline && q.lastLiveAt === null && !q.loading;

  const locked = q.offline; // disables all mutating controls while offline

  async function hardReload() {
    if ("serviceWorker" in navigator) {
      const regs = await navigator.serviceWorker.getRegistrations();
      await Promise.all(regs.map((r) => r.unregister()));
    }
    if ("caches" in window) {
      const keys = await caches.keys();
      await Promise.all(keys.map((k) => caches.delete(k)));
    }
    window.location.reload();
  }

  const openWalkin = (emergency: boolean) => {
    armSound();
    setEmergencyMode(emergency);
    setWalkinOpen(true);
    setControlsOpen(false);
  };

  const submitWalkin = (name: string, phone?: string) => {
    if (!sid) return;
    setWalkinOpen(false);
    q.run(() =>
      emergencyMode ? api.emergency(sid, name, phone) : api.walkin(sid, name, phone),
    );
  };

  const rowAction = (fn: (id: string) => Promise<QueueSnapshot>) => (e: QueueEntry) => {
    setActiveRow(null);
    q.run(() => fn(e.entry_id));
  };

  const waitingCount = useMemo(
    () => q.snap?.entries.filter((e) => e.status === "arrived" || e.status === "booked").length ?? 0,
    [q.snap],
  );

  if (!ready) return <main className="min-h-screen" />;

  return (
    <main className="min-h-screen pb-safe-next">
      {/* Sticky banners — only one shows at a time */}
      <ReconnectBar visible={isFirstLoadOffline} />
      <OfflineBanner offline={q.offline} lastLiveAt={q.lastLiveAt} now={now} />

      <div className="mx-auto w-full max-w-md px-3 pt-3">
        {/* top bar */}
        <div className="mb-3 flex items-center justify-between px-1">
          <div className="min-w-0">
            <p className="truncate text-sm font-bold text-ink">{clinic?.name ?? "ClinicQ"}</p>
            <p className="text-xs text-faint">
              {clinic?.slug} · {STRINGS.appName.en}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setControlsOpen(true)}
              className="flex h-11 items-center gap-1.5 rounded-xl border border-line bg-surface px-3 text-sm font-semibold text-ink active:bg-canvas"
            >
              ⚙ {STRINGS.controls.hi}
            </button>
            <Link
              href="/settings"
              className="flex h-11 w-11 items-center justify-center rounded-xl border border-line bg-surface text-lg active:bg-canvas"
              aria-label={STRINGS.settings.en}
            >
              ⋯
            </Link>
          </div>
        </div>

        {isStale ? (
          /* Offline >10min: hide queue entirely — old data is worse than no data */
          <StaleErrorScreen onReload={hardReload} />
        ) : session ? (
          <div className="grid gap-3">
            <SessionBanner
              session={session}
              sessions={q.snap?.sessions}
              onSwitch={(id) => q.setSessionId(id)}
            />
            <NowServing serving={q.snap?.now_serving ?? null} now={now} />

            {/* walk-in — 2 taps total (this opens the modal, then Add) */}
            <button
              onClick={() => openWalkin(false)}
              disabled={locked}
              className="flex min-h-touch w-full items-center justify-center gap-2 rounded-xl2 border-2 border-dashed border-primary/40 bg-primary-soft text-lg font-bold text-primary-ink active:bg-primary-soft/70 disabled:opacity-50"
            >
              ＋ {STRINGS.addWalkin.hi}
            </button>

            <section className="grid gap-2">
              {q.snap && q.snap.entries.length === 0 ? (
                <div className="rounded-xl2 bg-surface px-5 py-10 text-center shadow-card">
                  <p className="text-base font-semibold text-muted">{STRINGS.emptyQueue.hi}</p>
                  <p className="mt-1 text-sm text-faint">{STRINGS.emptyHint.hi}</p>
                </div>
              ) : (
                q.snap?.entries.map((e, i) => (
                  <QueueRow
                    key={e.entry_id}
                    entry={e}
                    position={i}
                    now={now}
                    disabled={locked}
                    onTap={setActiveRow}
                  />
                ))
              )}
            </section>
          </div>
        ) : (
          <div className="mt-16 rounded-xl2 bg-surface px-6 py-12 text-center shadow-card">
            <p className="text-lg font-semibold text-ink">आज कोई सत्र नहीं</p>
            <p className="mt-1 text-sm text-muted">No session scheduled today</p>
            <Link href="/settings" className="btn-ghost mt-5 inline-flex">
              {STRINGS.settings.hi} →
            </Link>
          </div>
        )}
      </div>

      {session && (
        <NextButton
          waiting={waitingCount}
          disabled={locked || !isOpen}
          onClick={() => sid && q.run(() => api.next(sid))}
        />
      )}

      <UndoSnackbar visible={q.undoVisible} onUndo={q.doUndo} />
      <ErrorToast message={q.error} onClose={q.clearError} />

      <ActionSheet
        entry={activeRow}
        onClose={() => setActiveRow(null)}
        onArrived={rowAction(api.entryArrived)}
        onCallNow={rowAction(api.entryCallNow)}
        onCancel={rowAction(api.entryCancel)}
      />

      <WalkinModal
        open={walkinOpen}
        emergency={emergencyMode}
        onClose={() => setWalkinOpen(false)}
        onSubmit={submitWalkin}
      />

      {session && (
        <SessionControls
          open={controlsOpen}
          session={session}
          nowServing={q.snap?.now_serving ?? null}
          onClose={() => setControlsOpen(false)}
          onStart={() => sid && q.run(() => api.startSession(sid))}
          onPause={() => sid && q.run(() => api.pauseSession(sid))}
          onResume={() => sid && q.run(() => api.resumeSession(sid))}
          onDelay={(m) => sid && q.run(() => api.delay(sid, m))}
          onEmergency={() => openWalkin(true)}
          onCloseToday={() => sid && q.run(() => api.closeSession(sid))}
          onCancelToday={() => sid && q.run(() => api.cancelToday(sid))}
          onReopen={() => sid && q.run(() => api.reopenSession(sid))}
        />
      )}
    </main>
  );
}
