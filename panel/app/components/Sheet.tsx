"use client";

import { useEffect } from "react";

/** A bottom sheet with a scrim. Big touch targets, thumb-reachable, dismiss by
 * tapping the scrim. Used for the row action sheet and session controls. */
export function Sheet({
  open,
  onClose,
  title,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title?: string;
  children: React.ReactNode;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex flex-col justify-end">
      <div className="absolute inset-0 animate-fade-in bg-ink/40" onClick={onClose} />
      <div className="safe-bottom relative animate-sheet-up rounded-t-3xl bg-surface p-4 shadow-sheet">
        <div className="mx-auto mb-3 h-1.5 w-10 rounded-full bg-line" />
        {title && (
          <h2 className="mb-3 px-1 text-center text-base font-semibold text-muted">{title}</h2>
        )}
        {children}
      </div>
    </div>
  );
}
