"use client";

import { clock } from "../lib/format";
import { STRINGS } from "../lib/i18n";
import type { SessionMeta, SessionListItem, Upcoming } from "../lib/types";

const SESSION_HI: Record<string, string> = { morning: "सुबह", evening: "शाम" };

const STATUS_STYLE: Record<string, string> = {
  open: "bg-arrived-bg text-arrived-fg",
  paused: "bg-booked-bg text-booked-fg",
  scheduled: "bg-neutral-bg text-neutral-fg",
  closed: "bg-neutral-bg text-neutral-fg",
  cancelled: "bg-danger-soft text-danger",
};

const STATUS_HI: Record<string, string> = {
  open: "चालू",
  paused: "रुका",
  scheduled: "बाकी",
  closed: "बंद",
  cancelled: "रद्द",
};

export function SessionBanner({
  session,
  sessions,
  upcoming,
  day,
  today,
  onSwitch,
  onDay,
}: {
  session: SessionMeta;
  sessions?: SessionListItem[];
  upcoming?: Upcoming;
  /** Day currently in view, ISO "YYYY-MM-DD" (IST). */
  day: string;
  today: string;
  onSwitch: (id: string) => void;
  onDay: (date: string) => void;
}) {
  const label = SESSION_HI[session.name] ?? session.name;
  const avgMin = Math.round(session.avg_consult_s / 60);
  const viewingToday = day === today;
  // Show the day tabs whenever there is something to switch to: bookings
  // already sitting in tomorrow's queue, or the receptionist is over there.
  const showDays = !viewingToday || (upcoming?.count ?? 0) > 0;

  return (
    <header className="rounded-xl2 bg-surface p-4 shadow-card">
      {showDays && (
        <div className="mb-3 flex items-center gap-2">
          <DayTab
            active={viewingToday}
            label={STRINGS.today.hi}
            onClick={() => onDay(today)}
          />
          <DayTab
            active={!viewingToday}
            label={STRINGS.tomorrow.hi}
            badge={upcoming?.count}
            onClick={() => upcoming && onDay(upcoming.date)}
          />
        </div>
      )}

      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-bold text-ink">{label} OPD</h1>
            <span
              className={`chip text-xs ${STATUS_STYLE[session.status] ?? STATUS_STYLE.scheduled}`}
            >
              {STATUS_HI[session.status] ?? session.status}
            </span>
          </div>
          <p className="mt-0.5 text-sm text-muted">
            {clock(session.start_at)} – {clock(session.end_at)}
          </p>
        </div>
        <div className="flex gap-2 text-center">
          <Stat value={session.waiting} label={STRINGS.waiting.hi} tone="ink" />
          <Stat value={session.served} label={STRINGS.served.hi} tone="primary" />
          <Stat value={`${avgMin}′`} label={STRINGS.avg.hi} tone="muted" />
        </div>
      </div>

      {/* A future day is a preview: you cannot serve a patient who has not
          been called yet, so every mutating control is disabled, not hidden. */}
      {session.read_only && (
        <p className="mt-3 rounded-xl bg-booked-bg px-3 py-2 text-sm font-semibold text-booked-fg">
          👁 {STRINGS.viewOnly.hi}
          <span className="block text-xs font-medium opacity-80">{STRINGS.viewOnly.en}</span>
        </p>
      )}

      {sessions && sessions.length > 1 && (
        <div className="no-scrollbar mt-3 flex gap-2 overflow-x-auto">
          {sessions.map((s) => {
            const active = s.id === session.id;
            return (
              <button
                key={s.id}
                onClick={() => onSwitch(s.id)}
                className={`shrink-0 rounded-full px-4 py-1.5 text-sm font-semibold transition ${
                  active
                    ? "bg-primary text-white"
                    : "border border-line bg-canvas text-muted"
                }`}
              >
                {SESSION_HI[s.name] ?? s.name}
              </button>
            );
          })}
        </div>
      )}
    </header>
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
      {label}
      {badge !== undefined && badge > 0 && (
        <span
          className={`rounded-full px-2 py-0.5 text-xs font-bold tabular-nums ${
            active ? "bg-white/25 text-white" : "bg-primary text-white"
          }`}
        >
          {badge}
        </span>
      )}
    </button>
  );
}

function Stat({
  value,
  label,
  tone,
}: {
  value: number | string;
  label: string;
  tone: "ink" | "primary" | "muted";
}) {
  const color =
    tone === "primary" ? "text-primary" : tone === "muted" ? "text-muted" : "text-ink";
  return (
    <div className="min-w-[3rem] rounded-xl bg-canvas px-2.5 py-1.5">
      <p className={`text-2xl font-bold leading-none tabular-nums ${color}`}>{value}</p>
      <p className="mt-0.5 text-[11px] font-medium text-faint">{label}</p>
    </div>
  );
}
