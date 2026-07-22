"use client";

import { clock, relEta } from "../lib/format";
import { STRINGS } from "../lib/i18n";
import type { QueueEntry } from "../lib/types";
import { StatusChip } from "./StatusChip";

export function QueueRow({
  entry,
  position,
  now,
  onTap,
  disabled,
}: {
  entry: QueueEntry;
  position: number;
  now: number;
  onTap: (e: QueueEntry) => void;
  disabled?: boolean;
}) {
  return (
    <button
      onClick={() => !disabled && onTap(entry)}
      disabled={disabled}
      className="flex min-h-touch w-full items-center gap-3 rounded-xl2 bg-surface px-3 py-2.5 text-left shadow-card transition active:scale-[0.99] active:bg-canvas disabled:opacity-70"
    >
      {/* token number = the patient's fixed identity at the desk */}
      <div className="flex h-12 w-12 shrink-0 flex-col items-center justify-center rounded-xl bg-canvas">
        <span className="text-[10px] font-medium leading-none text-faint">
          {STRINGS.token.hi}
        </span>
        <span className="text-xl font-bold leading-tight tabular-nums text-ink">
          {entry.token_number}
        </span>
      </div>

      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <p className="truncate text-base font-semibold text-ink">
            {entry.name || `${STRINGS.token.hi} #${entry.token_number}`}
          </p>
          {entry.next_up && (
            <span className="chip bg-consult-bg px-2 py-0.5 text-xs text-consult-fg">
              ▶ अगला
            </span>
          )}
        </div>
        <p className="mt-0.5 text-sm text-muted">
          {STRINGS.target.hi} {clock(entry.priority_time)} · {STRINGS.eta.hi}{" "}
          <span className="font-medium text-ink">{relEta(entry.eta, now)}</span>
        </p>
      </div>

      <StatusChip status={entry.status} graceUntil={entry.grace_until} now={now} />
    </button>
  );
}
