"use client";

import { countdown } from "../lib/format";
import { useLocale } from "../lib/locale";
import type { EntryStatus } from "../lib/types";
import type { StringKey } from "@/lib/i18n";

const MAP: Record<string, { cls: string; key: StringKey }> = {
  booked: { cls: "bg-booked-bg text-booked-fg", key: "stBooked" },
  arrived: { cls: "bg-arrived-bg text-arrived-fg", key: "stArrived" },
  called: { cls: "bg-consult-bg text-consult-fg", key: "stCalled" },
  in_consult: { cls: "bg-consult-bg text-consult-fg", key: "stInConsult" },
  skipped: { cls: "bg-grace-bg text-grace-fg", key: "stGrace" },
  done: { cls: "bg-neutral-bg text-neutral-fg", key: "stDone" },
  cancelled: { cls: "bg-neutral-bg text-neutral-fg", key: "stCancelled" },
  expired: { cls: "bg-neutral-bg text-neutral-fg", key: "stExpired" },
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
  const { t } = useLocale();
  const m = MAP[status] ?? MAP.booked;
  const isGrace = status === "skipped" && graceUntil;
  return (
    <span className={`chip shrink-0 ${m.cls}`}>
      <span
        className={`h-2 w-2 shrink-0 rounded-full ${
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
      {t(m.key)}
      {isGrace && (
        <span className="ml-0.5 tabular-nums font-bold">{countdown(graceUntil, now)}</span>
      )}
    </span>
  );
}
