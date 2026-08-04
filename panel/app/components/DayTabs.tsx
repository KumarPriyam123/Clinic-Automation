"use client";

import { useLocale } from "../lib/locale";

/** Today / tomorrow day switcher.
 *
 * Renders UNCONDITIONALLY, including when tomorrow has zero bookings or no
 * session at all. A control that appears and disappears with the data reads as
 * a malfunction: two screenshots of the same build looked like two different
 * apps. The tomorrow tab is always tappable — a disabled tab is still a dead
 * control that invites tapping — and the page shows the matching empty state. */
export function DayTabs({
  day,
  today,
  tomorrow,
  tomorrowCount,
  onDay,
}: {
  /** Day currently in view, ISO "YYYY-MM-DD" (IST). */
  day: string;
  today: string;
  tomorrow: string;
  /** Active entries already booked for tomorrow; 0 renders no badge. */
  tomorrowCount: number;
  onDay: (date: string) => void;
}) {
  const { t } = useLocale();
  const viewingToday = day === today;
  return (
    <div className="mb-3 flex items-center gap-2">
      <DayTab active={viewingToday} label={t("today")} onClick={() => onDay(today)} />
      <DayTab
        active={!viewingToday}
        label={t("tomorrow")}
        badge={tomorrowCount}
        onClick={() => onDay(tomorrow)}
      />
    </div>
  );
}

function DayTab({
  active,
  label,
  badge,
  onClick,
}: {
  active: boolean;
  label: string;
  badge?: number;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`flex min-h-touch flex-1 items-center justify-center gap-1.5 rounded-xl px-3 text-[15px] font-bold transition ${
        active ? "bg-primary text-white" : "border border-line bg-canvas text-muted"
      }`}
    >
      <span className="truncate">{label}</span>
      {badge !== undefined && badge > 0 && (
        <span
          className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-bold tabular-nums ${
            active ? "bg-white/25 text-white" : "bg-primary text-white"
          }`}
        >
          {badge}
        </span>
      )}
    </button>
  );
}
