"use client";

import { countdown } from "../lib/format";
import { STRINGS } from "../lib/i18n";
import type { EntryStatus } from "../lib/types";

const MAP: Record<string, { cls: string; key: keyof typeof STRINGS.status }> = {
  booked: { cls: "bg-booked-bg text-booked-fg", key: "booked" },
  arrived: { cls: "bg-arrived-bg text-arrived-fg", key: "arrived" },
  called: { cls: "bg-consult-bg text-consult-fg", key: "called" },
  in_consult: { cls: "bg-consult-bg text-consult-fg", key: "in_consult" },
  skipped: { cls: "bg-grace-bg text-grace-fg", key: "grace" },
  done: { cls: "bg-neutral-bg text-neutral-fg", key: "done" },
  cancelled: { cls: "bg-neutral-bg text-neutral-fg", key: "cancelled" },
  expired: { cls: "bg-neutral-bg text-neutral-fg", key: "expired" },
};

export function StatusChip({
  status,
  graceUntil,
  now,
}: {
  status: EntryStatus;
  graceUntil?: string | null;
  now?: number;
}) {
  const m = MAP[status] ?? MAP.booked;
  const label = STRINGS.status[m.key];
  const isGrace = status === "skipped" && graceUntil;
  return (
    <span className={`chip ${m.cls}`}>
      <span
        className={`h-2 w-2 rounded-full ${
          status === "arrived"
            ? "bg-arrived-fg"
            : status === "in_consult" || status === "called"
              ? "bg-consult-fg animate-pulse"
              : status === "skipped"
                ? "bg-grace-fg"
                : status === "booked"
                  ? "bg-booked-fg"
                  : "bg-neutral-fg"
        }`}
      />
      {label.hi}
      {isGrace && (
        <span className="ml-0.5 tabular-nums font-bold">{countdown(graceUntil, now)}</span>
      )}
    </span>
  );
}
