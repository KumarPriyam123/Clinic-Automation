"use client";

import { useLocale } from "../lib/locale";
import { STALE_MS } from "../lib/useQueue";

/** 5-second UNDO snackbar shown after every mutation (backend /undo replays the
 * inverse). Sits just above the NEXT button, one big tap target. */
export function UndoSnackbar({ visible, onUndo }: { visible: boolean; onUndo: () => void }) {
  const { t } = useLocale();
  if (!visible) return null;
  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-[6.5rem] z-40 flex justify-center px-4">
      <div className="pointer-events-auto flex w-full max-w-md animate-pop items-center gap-3 rounded-2xl bg-ink px-4 py-2.5 text-white shadow-sheet">
        <span className="min-w-0 flex-1 truncate text-sm font-medium">✓ {t("saved")}</span>
        <button
          onClick={onUndo}
          className="min-h-touch shrink-0 rounded-xl bg-white/15 px-4 text-base font-bold text-white active:bg-white/25"
        >
          ↩ {t("undo")}
        </button>
      </div>
    </div>
  );
}

/** Transient error toast (session full, network, etc.). */
export function ErrorToast({ message, onClose }: { message: string | null; onClose: () => void }) {
  if (!message) return null;
  return (
    <div className="pointer-events-none fixed inset-x-0 top-3 z-50 flex justify-center px-4">
      <button
        onClick={onClose}
        className="pointer-events-auto flex min-h-touch max-w-full animate-pop items-center rounded-2xl bg-danger px-4 py-2.5 text-sm font-semibold text-white shadow-sheet"
      >
        {message}
      </button>
    </div>
  );
}

/** Sticky banner shown while offline.
 *
 * - If snapshotAgeMs < STALE_MS: amber banner with "N min ago" — data visible but
 *   all mutating controls are already disabled via `locked` in the parent.
 * - If snapshotAgeMs >= STALE_MS: the parent hides the queue entirely and shows
 *   StaleErrorScreen instead; this banner is hidden.
 *
 * `lastLiveAt` null means we've never had a successful poll (first load offline).
 */
export function OfflineBanner({
  offline,
  lastLiveAt,
  now,
}: {
  offline: boolean;
  lastLiveAt: number | null;
  now: number;
}) {
  const { t } = useLocale();
  if (!offline) return null;
  if (lastLiveAt === null) {
    // No data at all — StaleErrorScreen handles this
    return null;
  }
  const ageMs = now - lastLiveAt;
  if (ageMs >= STALE_MS) return null; // parent shows error screen instead
  const ageMin = Math.max(1, Math.round(ageMs / 60000));
  return (
    <div className="sticky top-0 z-40 flex flex-wrap items-center justify-center gap-x-2 bg-amber-100 px-3 py-2 text-center text-sm font-bold text-amber-900">
      <span className="h-2 w-2 shrink-0 animate-pulse rounded-full bg-amber-600" />
      <span>
        {t("staleData")} · {ageMin} {t("minutesAgo")}
      </span>
    </div>
  );
}

/** Full-screen error shown when offline > 10 min — hides all queue data.
 * A receptionist must never act on data older than 10 minutes. */
export function StaleErrorScreen({ onReload }: { onReload: () => void }) {
  const { t } = useLocale();
  return (
    <div className="mt-16 rounded-xl2 bg-surface px-6 py-12 text-center shadow-card">
      <p className="text-2xl">⚡</p>
      <p className="mt-3 text-lg font-bold text-danger">{t("noConnection")}</p>
      <p className="mt-1 text-sm text-muted">{t("noConnectionHint")}</p>
      <button onClick={onReload} className="btn-primary mt-6 w-full">
        ↺ {t("reload")}
      </button>
    </div>
  );
}

/** Fixed top bar shown while the panel can't reach the server (legacy — kept for
 * the first-load-offline case before any snapshot exists). */
export function ReconnectBar({ visible }: { visible: boolean }) {
  const { t } = useLocale();
  if (!visible) return null;
  return (
    <div className="sticky top-0 z-40 flex items-center justify-center gap-2 px-3 py-1.5 text-center text-sm font-semibold bg-booked-bg text-booked-fg">
      <span className="h-2 w-2 shrink-0 animate-pulse rounded-full bg-booked-fg" />
      {t("offline")}
    </div>
  );
}
