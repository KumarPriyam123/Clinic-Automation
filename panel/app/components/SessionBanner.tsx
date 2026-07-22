"use client";

import { clock } from "../lib/format";
import { STRINGS } from "../lib/i18n";
import type { SessionMeta, SessionListItem } from "../lib/types";

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
  onSwitch,
}: {
  session: SessionMeta;
  sessions?: SessionListItem[];
  onSwitch: (id: string) => void;
}) {
  const label = SESSION_HI[session.name] ?? session.name;
  const avgMin = Math.round(session.avg_consult_s / 60);
  return (
    <header className="rounded-xl2 bg-surface p-4 shadow-card">
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
