"use client";

import { clock } from "../lib/format";
import { useLocale } from "../lib/locale";
import type { SessionMeta, SessionListItem } from "../lib/types";
import type { StringKey } from "@/lib/i18n";

const SESSION_KEY: Record<string, StringKey> = {
  morning: "sessionMorning",
  evening: "sessionEvening",
};

const STATUS_STYLE: Record<string, string> = {
  open: "bg-arrived-bg text-arrived-fg",
  paused: "bg-booked-bg text-booked-fg",
  scheduled: "bg-neutral-bg text-neutral-fg",
  closed: "bg-neutral-bg text-neutral-fg",
  cancelled: "bg-danger-soft text-danger",
};

const STATUS_KEY: Record<string, StringKey> = {
  open: "sesOpen",
  paused: "sesPaused",
  scheduled: "sesScheduled",
  closed: "sesClosed",
  cancelled: "sesCancelled",
};

export function SessionBanner({
  session,
  sessions,
  onSwitch,
}: {
  session: SessionMeta;
  sessions?: SessionListItem[];
  onSwitch: (id: string) => void;
}) {
  const { t } = useLocale();
  const nameKey = SESSION_KEY[session.name];
  const label = nameKey ? t(nameKey) : session.name;
  const statusKey = STATUS_KEY[session.status];
  const avgMin = Math.round(session.avg_consult_s / 60);

  return (
    <header className="min-w-0 rounded-xl2 bg-surface p-4 shadow-card">
      {/* The stats sit on their own full-width row rather than beside the title.
          English labels run wider than their Devanagari counterparts ("Waiting"
          vs the Hindi equivalent), and side-by-side they blew the header past
          the viewport at 360px and pushed the FAB off-screen. A 3-column grid
          cannot overflow: each cell is a third of whatever width it is given. */}
      <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
        <h1 className="min-w-0 truncate text-xl font-bold text-ink">{label} OPD</h1>
        <span
          className={`chip shrink-0 text-xs ${STATUS_STYLE[session.status] ?? STATUS_STYLE.scheduled}`}
        >
          {statusKey ? t(statusKey) : session.status}
        </span>
      </div>
      <p className="mt-0.5 text-sm text-muted">
        {clock(session.start_at)} – {clock(session.end_at)}
      </p>

      <div className="mt-3 grid grid-cols-3 gap-2 text-center">
        <Stat value={session.waiting} label={t("waiting")} tone="ink" />
        <Stat value={session.served} label={t("served")} tone="primary" />
        <Stat value={`${avgMin}′`} label={t("avg")} tone="muted" />
      </div>

      {/* A future day is a preview: you cannot serve a patient who has not
          been called yet, so every mutating control is disabled, not hidden. */}
      {session.read_only && (
        <p className="mt-3 rounded-xl bg-booked-bg px-3 py-2 text-sm font-semibold text-booked-fg">
          👁 {t("viewOnly")}
        </p>
      )}

      {sessions && sessions.length > 1 && (
        <div className="no-scrollbar mt-3 flex gap-2 overflow-x-auto">
          {sessions.map((s) => {
            const active = s.id === session.id;
            const key = SESSION_KEY[s.name];
            return (
              <button
                key={s.id}
                onClick={() => onSwitch(s.id)}
                className={`shrink-0 rounded-full px-4 py-1.5 text-sm font-semibold transition ${
                  active ? "bg-primary text-white" : "border border-line bg-canvas text-muted"
                }`}
              >
                {key ? t(key) : s.name}
              </button>
            );
          })}
        </div>
      )}
    </header>
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
    <div className="min-w-0 rounded-xl bg-canvas px-1 py-2">
      <p className={`text-2xl font-bold leading-none tabular-nums ${color}`}>{value}</p>
      <p className="mt-1 break-words text-[11px] font-medium leading-tight text-faint">{label}</p>
    </div>
  );
}
