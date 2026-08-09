"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import * as api from "./lib/api";
import { getClinic, getToken } from "./lib/api";
import { useLocale } from "./lib/locale";
import { armSound } from "./lib/sound";
import { dayIST, todayIST, useQueue, useTick } from "./lib/useQueue";
import type { QueueEntry, QueueSnapshot } from "./lib/types";
import { DayTabs } from "./components/DayTabs";
import { SessionBanner } from "./components/SessionBanner";
import { NowServing } from "./components/NowServing";
import { QueueRow } from "./components/QueueRow";
import { NextButton } from "./components/NextButton";
import { ActionSheet } from "./components/ActionSheet";
import { OverflowMenu } from "./components/OverflowMenu";
import { WalkinModal } from "./components/WalkinModal";
import { SessionControls } from "./components/SessionControls";
import { ErrorToast, OfflineBanner, ReconnectBar, StaleErrorScreen, UndoSnackbar } from "./components/Snackbar";
import { STALE_MS } from "./lib/useQueue";

export default function LiveQueue() {
  const router = useRouter();
  const { t } = useLocale();
  const [ready, setReady] = useState(false);
  const q = useQueue();
  const now = useTick(true);

  const [activeRow, setActiveRow] = useState<QueueEntry | null>(null);
  const [walkinOpen, setWalkinOpen] = useState(false);
  const [emergencyMode, setEmergencyMode] = useState(false);
  const [controlsOpen, setControlsOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    if (!getToken()) router.replace("/login");
    else setReady(true);
  }, [router]);

  const clinic = getClinic();
  const session = q.snap?.session ?? null;
  // The mutation target is the SELECTED session, never the adopted snapshot's.
  // `snap.session` is whatever response landed last; deriving `sid` from it is
  // how NEXT could serve a patient from a session the user had switched away
  // from. See lib/session-target.ts.
  const sid = q.sessionId;
  const isOpen = session?.status === "open";
  const today = todayIST();
  const viewingToday = q.day === today;
  // The tomorrow tab must have a destination even before any booking exists,
  // so fall back to a locally computed date when `upcoming` is absent.
  const tomorrow = q.snap?.upcoming?.date ?? dayIST(1);
  const tomorrowCount = q.snap?.upcoming?.count ?? 0;
  // A future day is a read-only preview — you cannot serve, admit or mark
  // present a patient in a session that has not happened yet. Controls stay
  // visible but disabled so the reason is obvious.
  const readOnly = session?.read_only ?? false;

  // Stale-data guard: if we've been offline for >10min, hide the queue entirely.
  // A receptionist must never act on data that old.
  const snapshotAge = q.lastLiveAt !== null ? now - q.lastLiveAt : null;
  const isStale = q.offline && snapshotAge !== null && snapshotAge > STALE_MS;
  // First-load offline (never had a response): show reconnect bar, not stale banner.
  const isFirstLoadOffline = q.offline && q.lastLiveAt === null && !q.loading;

  // disables all mutating controls: offline, or previewing a future day
  const locked = q.offline || readOnly;

  async function hardReload() {
    setMenuOpen(false);
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
        <div className="mb-3 flex items-center justify-between gap-2 px-1">
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-bold text-ink">{clinic?.name ?? "ClinicQ"}</p>
            <p className="truncate text-xs text-faint">
              {clinic?.slug} · {t("appName")}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <button
              onClick={() => setControlsOpen(true)}
              className="flex h-11 max-w-[9rem] items-center gap-1.5 rounded-xl border border-line bg-surface px-3 text-sm font-semibold text-ink active:bg-canvas"
              aria-label={t("controls")}
            >
              <span className="shrink-0">⚙</span>
              <span className="truncate">{t("controlsShort")}</span>
            </button>
            <button
              onClick={() => setMenuOpen(true)}
              className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-line bg-surface text-lg active:bg-canvas"
              aria-label={t("more")}
            >
              ⋯
            </button>
          </div>
        </div>

        {/* Day switcher — always rendered, even with nothing booked tomorrow and
            even when tomorrow has no session. A control that comes and goes with
            the data reads as a malfunction. */}
        <DayTabs
          day={q.day}
          today={today}
          tomorrow={tomorrow}
          tomorrowCount={tomorrowCount}
          onDay={q.setDay}
        />

        {isStale ? (
          /* Offline >10min: hide queue entirely — old data is worse than no data */
          <StaleErrorScreen onReload={hardReload} />
        ) : session ? (
          /* minmax(0,1fr) caps the track: a grid item's default min-width:auto
             lets a wide child push the whole column past the viewport. */
          <div className="grid grid-cols-[minmax(0,1fr)] gap-3">
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
              className="flex min-h-touch w-full items-center justify-center gap-2 rounded-xl2 border-2 border-dashed border-primary/40 bg-primary-soft px-3 text-lg font-bold text-primary-ink active:bg-primary-soft/70 disabled:opacity-50"
            >
              <span className="shrink-0">＋</span>
              <span className="truncate">{t("addWalkin")}</span>
            </button>

            <section className="grid grid-cols-[minmax(0,1fr)] gap-2">
              {q.snap && q.snap.entries.length === 0 ? (
                <EmptyCard
                  title={viewingToday ? t("emptyQueue") : t("noBookingsYet")}
                  hint={viewingToday ? t("emptyHint") : t("noBookingsYetHint")}
                />
              ) : (
                q.snap?.entries.map((e, i) => (
                  <QueueRow
                    key={e.entry_id}
                    entry={e}
                    position={i}
                    now={now}
                    disabled={locked}
                    /* Rule: no relative countdown on a session that isn't today. */
                    showRelativeEta={session.date === today}
                    onTap={setActiveRow}
                  />
                ))
              )}
            </section>
          </div>
        ) : !viewingToday ? (
          /* The clinic is simply closed that weekday — distinct from "session
             exists, nobody booked". Always offer the way back. */
          <div className="mt-10 rounded-xl2 bg-surface px-6 py-12 text-center shadow-card">
            <p className="text-lg font-semibold text-ink">
              {q.day === tomorrow ? t("noSessionTomorrow") : t("noSessionThatDay")}
            </p>
            {q.day === tomorrow && (
              <p className="mt-1 text-sm text-muted">{t("noSessionTomorrowHint")}</p>
            )}
            <button className="btn-primary mt-5 h-touch px-6" onClick={() => q.setDay(today)}>
              ← {t("today")}
            </button>
          </div>
        ) : (
          <div className="mt-10 rounded-xl2 bg-surface px-6 py-12 text-center shadow-card">
            <p className="text-lg font-semibold text-ink">{t("noSessionToday")}</p>
            <Link href="/settings" className="btn-ghost mt-5 inline-flex">
              {t("settings")} →
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
      <ErrorToast message={q.error ? t(q.error) : null} onClose={q.clearError} />

      <OverflowMenu open={menuOpen} onClose={() => setMenuOpen(false)} onReload={hardReload} />

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

function EmptyCard({ title, hint }: { title: string; hint: string }) {
  return (
    <div className="rounded-xl2 bg-surface px-5 py-10 text-center shadow-card">
      <p className="text-base font-semibold text-muted">{title}</p>
      <p className="mt-1 text-sm text-faint">{hint}</p>
    </div>
  );
}
