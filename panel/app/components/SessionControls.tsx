"use client";

import { useState } from "react";
import { useLocale } from "../lib/locale";
import type { NowServing, SessionMeta } from "../lib/types";
import { type Pair, templates } from "@/lib/i18n";
import { Sheet } from "./Sheet";

type Confirm = null | "close" | "cancel" | "reopen";

type Line = { pair: Pair; nudge?: boolean };

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
  const { t } = useLocale();
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
  // reopen is a same-day recovery from closed OR cancelled (mis-tap recovery)
  const todayIST = new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });
  // Past its own end_at, the 60s sweep re-closes any session we reopen. Say so
  // rather than offering a button whose effect silently vanishes a minute later.
  const timePassed = session.end_at !== null && new Date(session.end_at).getTime() <= Date.now();
  const canReopen =
    (st === "closed" || st === "cancelled") && session.date === todayIST && !timePassed;

  // --- dynamic, count-aware confirm bodies (staff-facing panel copy) --- //
  const closeLines: Line[] = [];
  if (nowServing) {
    closeLines.push({
      pair: templates.closeInConsult(nowServing.token_number, nowServing.name),
    });
  }
  if (waiting > 0) closeLines.push({ pair: templates.closeWaiting(waiting) });
  if (closeLines.length === 0) closeLines.push({ pair: templates.closeGeneric() });

  const cancelLines: Line[] = [
    { pair: waiting > 0 ? templates.cancelWaiting(waiting) : templates.cancelGeneric() },
  ];
  if (served > 0) {
    cancelLines.push({ pair: templates.cancelServedNudge(served), nudge: true });
  }

  const reopenLines: Line[] = [{ pair: templates.reopenWarning() }];

  return (
    <Sheet open={open} onClose={close} title={t("controls")}>
      {/* A future day is a preview — none of these actions can apply to it. */}
      {session.read_only ? (
        <div className="grid gap-2.5">
          <div className="rounded-xl bg-booked-bg p-3 text-booked-fg">
            <p className="text-[15px] font-semibold leading-snug">{t("viewOnly")}</p>
          </div>
          <button className="btn-ghost h-touch w-full border-0" onClick={close}>
            {t("close")}
          </button>
        </div>
      ) : /* A closed/cancelled session shows recovery (reopen only for today's close/cancel). */
      st === "closed" || st === "cancelled" ? (
        confirm === "reopen" ? (
          <ConfirmPanel
            lines={reopenLines}
            yes={t("reopenConfirmYes")}
            no={t("back")}
            onYes={() => act(onReopen)}
            onNo={() => setConfirm(null)}
          />
        ) : (
          <div className="grid gap-2.5">
            <p className="px-1 text-sm text-muted">
              {st === "closed" ? t("sessionClosedNote") : t("sessionCancelledNote")}
            </p>
            {canReopen ? (
              <button className="btn-primary h-touch w-full" onClick={() => setConfirm("reopen")}>
                ↻ {t("reopen")}
              </button>
            ) : (
              timePassed &&
              session.date === todayIST && (
                <div className="rounded-xl bg-booked-bg p-3 text-booked-fg">
                  <p className="text-[15px] font-semibold leading-snug">{t("sessionTimePassed")}</p>
                </div>
              )
            )}
            <button className="btn-ghost h-touch w-full border-0" onClick={close}>
              {t("close")}
            </button>
          </div>
        )
      ) : confirm === "close" ? (
        <ConfirmPanel
          lines={closeLines}
          yes={t("closeConfirmYes")}
          no={t("back")}
          onYes={() => act(onCloseToday)}
          onNo={() => setConfirm(null)}
        />
      ) : confirm === "cancel" ? (
        <ConfirmPanel
          lines={cancelLines}
          yes={t("cancelConfirmYes")}
          no={t("back")}
          onYes={() => act(onCancelToday)}
          onNo={() => setConfirm(null)}
          danger
        />
      ) : (
        <div className="grid gap-2.5">
          {st === "scheduled" ? (
            <button className="btn-primary h-touch w-full" onClick={() => act(onStart)}>
              ▶ {t("start")}
            </button>
          ) : st === "paused" ? (
            <button className="btn-primary h-touch w-full" onClick={() => act(onResume)}>
              ▶ {t("resume")}
            </button>
          ) : (
            <button className="btn-ghost h-touch w-full" onClick={() => act(onPause)}>
              ⏸ {t("pause")}
            </button>
          )}

          <div>
            <p className="mb-1.5 px-1 text-sm font-medium text-muted">{t("late")}</p>
            <div className="grid grid-cols-3 gap-2">
              {[15, 30, 45].map((m) => (
                <button
                  key={m}
                  className="btn-ghost h-touch w-full px-2 text-xl"
                  onClick={() => act(() => onDelay(m))}
                >
                  +{m}
                </button>
              ))}
            </div>
          </div>

          <button className="btn-ghost h-touch w-full" onClick={() => act(onEmergency)}>
            ⚠ {t("emergency")}
          </button>

          <button
            className="btn-ghost h-touch w-full text-danger"
            onClick={() => setConfirm("close")}
          >
            ■ {t("closeToday")}
          </button>
          <button
            className="btn-ghost h-touch w-full text-danger"
            onClick={() => setConfirm("cancel")}
          >
            ✕ {t("cancelToday")}
          </button>
        </div>
      )}
    </Sheet>
  );
}

function ConfirmPanel({
  lines,
  yes,
  no,
  onYes,
  onNo,
  danger,
}: {
  lines: Line[];
  yes: string;
  no: string;
  onYes: () => void;
  onNo: () => void;
  danger?: boolean;
}) {
  const { p } = useLocale();
  return (
    <div className="grid gap-3">
      <div className="grid gap-2 rounded-2xl bg-canvas p-3">
        {lines.map((l, i) => (
          <div
            key={i}
            className={`rounded-xl p-2.5 ${l.nudge ? "bg-booked-bg text-booked-fg" : "bg-surface"}`}
          >
            <p className="text-[15px] font-semibold leading-snug text-ink">{p(l.pair)}</p>
          </div>
        ))}
      </div>
      <div className="grid grid-cols-2 gap-2">
        <button className="btn-ghost h-touch w-full px-2" onClick={onNo}>
          <span className="truncate">{no}</span>
        </button>
        <button
          className={`${danger ? "btn-danger" : "btn-primary"} h-touch w-full px-2`}
          onClick={onYes}
        >
          <span className="truncate">{yes}</span>
        </button>
      </div>
    </div>
  );
}
