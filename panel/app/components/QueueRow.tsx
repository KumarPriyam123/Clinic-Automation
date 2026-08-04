"use client";

import { clock, relEta } from "../lib/format";
import { useLocale } from "../lib/locale";
import type { QueueEntry } from "../lib/types";
import { StatusChip } from "./StatusChip";

export function QueueRow({
  entry,
  position,
  now,
  onTap,
  disabled,
  showRelativeEta,
}: {
  entry: QueueEntry;
  position: number;
  now: number;
  onTap: (e: QueueEntry) => void;
  disabled?: boolean;
  /** False for any session that is not today: a countdown of "10h 1m" next to
   * an absolute 9:00 am is noise, and reads as a bug. Show the clock only. */
  showRelativeEta: boolean;
}) {
  const { t, lang } = useLocale();
  return (
    <button
      onClick={() => !disabled && onTap(entry)}
      disabled={disabled}
      className="flex min-h-touch w-full items-center gap-3 rounded-xl2 bg-surface px-3 py-2.5 text-left shadow-card transition active:scale-[0.99] active:bg-canvas disabled:opacity-70"
    >
      {/* token number = the patient's fixed identity at the desk */}
      <div className="flex h-12 w-12 shrink-0 flex-col items-center justify-center rounded-xl bg-canvas">
        <span className="text-[10px] font-medium leading-none text-faint">{t("token")}</span>
        <span className="text-xl font-bold leading-tight tabular-nums text-ink">
          {entry.token_number}
        </span>
      </div>

      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <p className="truncate text-base font-semibold text-ink">
            {entry.name || `${t("token")} #${entry.token_number}`}
          </p>
          {entry.next_up && (
            <span className="chip shrink-0 bg-consult-bg px-2 py-0.5 text-xs text-consult-fg">
              ▶ {t("nextUp")}
            </span>
          )}
        </div>
        <p className="mt-0.5 text-[13px] leading-snug text-muted">
          {t("target")} {clock(entry.priority_time)} · {t("eta")}{" "}
          <span className="font-medium text-ink">
            {showRelativeEta ? relEta(entry.eta, now, lang) : clock(entry.eta)}
          </span>
        </p>
      </div>

      <StatusChip
        status={entry.status}
        graceUntil={entry.grace_until}
        now={now}
        showCountdown={showRelativeEta}
      />
    </button>
  );
}
