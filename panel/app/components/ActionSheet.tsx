"use client";

import { useLocale } from "../lib/locale";
import type { QueueEntry } from "../lib/types";
import { Sheet } from "./Sheet";

/** Row action sheet — one tap on a queue row opens this; each action is one
 * more tap (arrived / cancel / call-now), meeting the <=2-tap bar. */
export function ActionSheet({
  entry,
  onClose,
  onArrived,
  onCallNow,
  onCancel,
}: {
  entry: QueueEntry | null;
  onClose: () => void;
  onArrived: (e: QueueEntry) => void;
  onCallNow: (e: QueueEntry) => void;
  onCancel: (e: QueueEntry) => void;
}) {
  const { t } = useLocale();
  const canArrive = entry ? entry.status === "booked" || entry.status === "skipped" : false;
  return (
    <Sheet
      open={!!entry}
      onClose={onClose}
      title={entry ? `${t("token")} #${entry.token_number} · ${entry.name || "—"}` : undefined}
    >
      {entry && (
        <div className="grid gap-2.5">
          {canArrive && (
            <button className="btn-primary h-touch w-full" onClick={() => onArrived(entry)}>
              ✓ {t("markArrived")}
            </button>
          )}
          <button className="btn-ghost h-touch w-full" onClick={() => onCallNow(entry)}>
            ▶ {t("callNow")}
          </button>
          <button
            className="btn-danger h-touch w-full bg-danger-soft text-danger"
            onClick={() => onCancel(entry)}
          >
            ✕ {t("cancelToken")}
          </button>
          <button className="btn-ghost mt-1 h-touch w-full border-0" onClick={onClose}>
            {t("close")}
          </button>
        </div>
      )}
    </Sheet>
  );
}
