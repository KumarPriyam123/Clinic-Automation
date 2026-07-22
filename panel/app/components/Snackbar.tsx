"use client";

import { STRINGS } from "../lib/i18n";

/** 5-second UNDO snackbar shown after every mutation (backend /undo replays the
 * inverse). Sits just above the NEXT button, one big tap target. */
export function UndoSnackbar({ visible, onUndo }: { visible: boolean; onUndo: () => void }) {
  if (!visible) return null;
  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-[6.5rem] z-40 flex justify-center px-4">
      <div className="pointer-events-auto flex w-full max-w-md animate-pop items-center gap-3 rounded-2xl bg-ink px-4 py-2.5 text-white shadow-sheet">
        <span className="flex-1 text-sm font-medium">✓ {STRINGS.saved.hi}</span>
        <button
          onClick={onUndo}
          className="min-h-[2.75rem] rounded-xl bg-white/15 px-4 text-base font-bold text-white active:bg-white/25"
        >
          ↩ {STRINGS.undo.hi}
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
        className="pointer-events-auto animate-pop rounded-2xl bg-danger px-4 py-2.5 text-sm font-semibold text-white shadow-sheet"
      >
        {message}
      </button>
    </div>
  );
}

/** Fixed top bar shown while the panel can't reach the server. */
export function ReconnectBar({ visible }: { visible: boolean }) {
  if (!visible) return null;
  return (
    <div className="sticky top-0 z-40 flex items-center justify-center gap-2 bg-booked-bg py-1.5 text-sm font-semibold text-booked-fg">
      <span className="h-2 w-2 animate-pulse rounded-full bg-booked-fg" />
      {STRINGS.offline.hi} · {STRINGS.offline.en}
    </div>
  );
}
