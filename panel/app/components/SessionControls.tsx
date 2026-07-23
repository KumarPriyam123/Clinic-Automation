"use client";

import { useState } from "react";
import { STRINGS } from "../lib/i18n";
import type { NowServing, SessionMeta } from "../lib/types";
import { Sheet } from "./Sheet";

type Confirm = null | "close" | "cancel" | "reopen";

/** Session controls bottom-sheet. Destructive actions are a real two-step whose
 * confirm states the consequence with LIVE counts from the queue snapshot — a
 * single tap must never silently expire/message patients. */
export function SessionControls({
  open,
  session,
  nowServing,
  onClose,
  onStart,
  onPause,
  onResume,
  onDelay,
  onEmergency,
  onCloseToday,
  onCancelToday,
  onReopen,
}: {
  open: boolean;
  session: SessionMeta;
  nowServing: NowServing | null;
  onClose: () => void;
  onStart: () => void;
  onPause: () => void;
  onResume: () => void;
  onDelay: (min: number) => void;
  onEmergency: () => void;
  onCloseToday: () => void;
  onCancelToday: () => void;
  onReopen: () => void;
}) {
  const [confirm, setConfirm] = useState<Confirm>(null);

  const close = () => {
    setConfirm(null);
    onClose();
  };
  const act = (fn: () => void) => {
    setConfirm(null);
    onClose();
    fn();
  };

  const st = session.status;
  const waiting = session.waiting;
  const served = session.served;
  // reopen is a same-day recovery only (a closed session from today)
  const todayIST = new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });
  const canReopen = st === "closed" && session.date === todayIST;

  // --- dynamic, count-aware confirm bodies (staff-facing panel copy) --- //
  const closeLines: Line[] = [];
  if (nowServing) {
    closeLines.push({
      hi: `टोकन #${nowServing.token_number} (${nowServing.name || "—"}) अभी अंदर हैं — बंद करने पर उनका परामर्श पूरा मान लिया जाएगा।`,
      en: `Token #${nowServing.token_number} is in consult — closing marks their consult as done.`,
    });
  }
  if (waiting > 0) {
    closeLines.push({
      hi: `${waiting} मरीज़ इंतज़ार में हैं। बंद करने पर सभी को कल आने का संदेश भेजा जाएगा।`,
      en: `${waiting} waiting — all will be messaged to come tomorrow.`,
    });
  }
  if (closeLines.length === 0) {
    closeLines.push({ hi: "सत्र बंद किया जाएगा।", en: "The session will be closed." });
  }

  const cancelLines: Line[] = [];
  if (waiting > 0) {
    cancelLines.push({
      hi: `${waiting} मरीज़ों को "क्लिनिक आज बंद है" संदेश भेजा जाएगा।`,
      en: `"Clinic closed today" will be sent to ${waiting} patient(s).`,
    });
  } else {
    cancelLines.push({
      hi: "आज का सत्र रद्द किया जाएगा।",
      en: "Today's session will be cancelled.",
    });
  }
  if (served > 0) {
    cancelLines.push({
      hi: `${served} मरीज़ देखे जा चुके हैं — "आज रद्द करें" उस सत्र के लिए है जो हुआ ही नहीं। देखे जा चुके हों तो "आज बंद करें" सही है।`,
      en: `${served} already seen — "Cancel today" is for a session that never happened; "Close today" is usually right once patients are seen.`,
      nudge: true,
    });
  }

  const reopenLines: Line[] = [
    {
      hi: "फिर से खोलने पर जिन मरीज़ों को पहले ही संदेश भेजा जा चुका है वे वापस नहीं आएँगे। केवल नया काम (वॉक-इन, नई बुकिंग, अगला) फिर चालू होगा।",
      en: "Reopening does NOT bring back patients who were already notified. It only re-enables work (walk-ins, new bookings, NEXT).",
    },
  ];

  return (
    <Sheet open={open} onClose={close} title={STRINGS.controls.hi}>
      {/* A closed/cancelled session shows recovery (reopen only for today's close). */}
      {st === "closed" || st === "cancelled" ? (
        confirm === "reopen" ? (
          <ConfirmPanel
            lines={reopenLines}
            yes={STRINGS.reopenConfirmYes.hi}
            onYes={() => act(onReopen)}
            onNo={() => setConfirm(null)}
          />
        ) : (
          <div className="grid gap-2.5">
            <p className="px-1 text-sm text-muted">
              {st === "closed" ? "सत्र बंद है / session closed" : "सत्र रद्द है / cancelled"}
            </p>
            {canReopen && (
              <button className="btn-primary h-touch w-full" onClick={() => setConfirm("reopen")}>
                ↻ {STRINGS.reopen.hi}
              </button>
            )}
            <button className="btn-ghost h-touch w-full border-0" onClick={close}>
              {STRINGS.close.hi}
            </button>
          </div>
        )
      ) : confirm === "close" ? (
        <ConfirmPanel
          lines={closeLines}
          yes={STRINGS.closeConfirmYes.hi}
          onYes={() => act(onCloseToday)}
          onNo={() => setConfirm(null)}
        />
      ) : confirm === "cancel" ? (
        <ConfirmPanel
          lines={cancelLines}
          yes={STRINGS.cancelConfirmYes.hi}
          onYes={() => act(onCancelToday)}
          onNo={() => setConfirm(null)}
          danger
        />
      ) : (
        <div className="grid gap-2.5">
          {st === "scheduled" ? (
            <button className="btn-primary h-touch w-full" onClick={() => act(onStart)}>
              ▶ {STRINGS.start.hi}
            </button>
          ) : st === "paused" ? (
            <button className="btn-primary h-touch w-full" onClick={() => act(onResume)}>
              ▶ {STRINGS.resume.hi}
            </button>
          ) : (
            <button className="btn-ghost h-touch w-full" onClick={() => act(onPause)}>
              ⏸ {STRINGS.pause.hi}
            </button>
          )}

          <div>
            <p className="mb-1.5 px-1 text-sm font-medium text-muted">{STRINGS.late.hi}</p>
            <div className="grid grid-cols-3 gap-2">
              {[15, 30, 45].map((m) => (
                <button
                  key={m}
                  className="btn-ghost h-touch w-full text-xl"
                  onClick={() => act(() => onDelay(m))}
                >
                  +{m}
                </button>
              ))}
            </div>
          </div>

          <button className="btn-ghost h-touch w-full" onClick={() => act(onEmergency)}>
            ⚠ {STRINGS.emergency.hi}
          </button>

          <button
            className="btn-ghost h-touch w-full text-danger"
            onClick={() => setConfirm("close")}
          >
            ■ {STRINGS.closeToday.hi}
          </button>
          <button
            className="btn-ghost h-touch w-full text-danger"
            onClick={() => setConfirm("cancel")}
          >
            ✕ {STRINGS.cancelToday.hi}
          </button>
        </div>
      )}
    </Sheet>
  );
}

type Line = { hi: string; en: string; nudge?: boolean };

function ConfirmPanel({
  lines,
  yes,
  onYes,
  onNo,
  danger,
}: {
  lines: Line[];
  yes: string;
  onYes: () => void;
  onNo: () => void;
  danger?: boolean;
}) {
  return (
    <div className="grid gap-3">
      <div className="grid gap-2 rounded-2xl bg-canvas p-3">
        {lines.map((l, i) => (
          <div
            key={i}
            className={`rounded-xl p-2.5 ${
              l.nudge ? "bg-booked-bg text-booked-fg" : "bg-surface"
            }`}
          >
            <p className="text-[15px] font-semibold leading-snug text-ink">{l.hi}</p>
            <p className="mt-0.5 text-xs leading-snug text-muted">{l.en}</p>
          </div>
        ))}
      </div>
      <div className="grid grid-cols-2 gap-2">
        <button className="btn-ghost h-touch w-full" onClick={onNo}>
          {STRINGS.back.hi}
        </button>
        <button
          className={`${danger ? "btn-danger" : "btn-primary"} h-touch w-full`}
          onClick={onYes}
        >
          {yes}
        </button>
      </div>
    </div>
  );
}
