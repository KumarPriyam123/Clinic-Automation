"use client";

import { useState } from "react";
import { STRINGS } from "../lib/i18n";
import type { SessionMeta } from "../lib/types";
import { Sheet } from "./Sheet";

/** Session controls bottom-sheet (single confirm on destructive actions). */
export function SessionControls({
  open,
  session,
  onClose,
  onStart,
  onPause,
  onResume,
  onDelay,
  onEmergency,
  onCloseToday,
  onCancelToday,
}: {
  open: boolean;
  session: SessionMeta;
  onClose: () => void;
  onStart: () => void;
  onPause: () => void;
  onResume: () => void;
  onDelay: (min: number) => void;
  onEmergency: () => void;
  onCloseToday: () => void;
  onCancelToday: () => void;
}) {
  const [confirm, setConfirm] = useState<null | "close" | "cancel">(null);

  const act = (fn: () => void) => {
    setConfirm(null);
    onClose();
    fn();
  };

  const st = session.status;
  return (
    <Sheet open={open} onClose={() => { setConfirm(null); onClose(); }} title={STRINGS.controls.hi}>
      <div className="grid gap-2.5">
        {st === "scheduled" || st === "closed" ? (
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

        {/* destructive: single inline confirm */}
        {confirm === "close" ? (
          <ConfirmRow label={STRINGS.closeToday.hi} onYes={() => act(onCloseToday)} onNo={() => setConfirm(null)} />
        ) : (
          <button className="btn-ghost h-touch w-full text-danger" onClick={() => setConfirm("close")}>
            ■ {STRINGS.closeToday.hi}
          </button>
        )}
        {confirm === "cancel" ? (
          <ConfirmRow label={STRINGS.cancelToday.hi} onYes={() => act(onCancelToday)} onNo={() => setConfirm(null)} danger />
        ) : (
          <button className="btn-ghost h-touch w-full text-danger" onClick={() => setConfirm("cancel")}>
            ✕ {STRINGS.cancelToday.hi}
          </button>
        )}
      </div>
    </Sheet>
  );
}

function ConfirmRow({
  label,
  onYes,
  onNo,
  danger,
}: {
  label: string;
  onYes: () => void;
  onNo: () => void;
  danger?: boolean;
}) {
  return (
    <div className="flex items-center gap-2 rounded-2xl bg-danger-soft p-2">
      <span className="flex-1 pl-2 text-sm font-semibold text-danger">
        {STRINGS.confirm.hi} {label}
      </span>
      <button className="btn-ghost h-touch min-w-[4rem] border-0" onClick={onNo}>
        {STRINGS.no.hi}
      </button>
      <button
        className={`${danger ? "btn-danger" : "btn-danger"} h-touch min-w-[5rem]`}
        onClick={onYes}
      >
        {STRINGS.yes.hi}
      </button>
    </div>
  );
}
