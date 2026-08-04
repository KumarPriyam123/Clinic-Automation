"use client";

import { elapsed } from "../lib/format";
import { useLocale } from "../lib/locale";
import type { NowServing as NS } from "../lib/types";

export function NowServing({ serving, now }: { serving: NS | null; now: number }) {
  const { t } = useLocale();
  if (!serving) {
    return (
      <div className="rounded-xl2 border border-dashed border-line bg-surface/60 px-5 py-6 text-center">
        <p className="text-sm font-medium uppercase tracking-wide text-faint">{t("nowServing")}</p>
        <p className="mt-1 text-lg font-semibold text-muted">{t("noneServing")}</p>
      </div>
    );
  }
  return (
    <div className="animate-pulse-ring rounded-xl2 bg-primary px-5 py-4 text-white shadow-card">
      <div className="flex items-center justify-between gap-2">
        <p className="min-w-0 truncate text-xs font-semibold uppercase tracking-widest text-white/70">
          {t("nowServing")}
        </p>
        <span className="shrink-0 rounded-full bg-white/15 px-2.5 py-0.5 text-xs font-semibold">
          {t("token")} #{serving.token_number}
        </span>
      </div>
      <div className="mt-2 flex items-end justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-3xl font-bold leading-tight">
            {serving.name || `${t("token")} #${serving.token_number}`}
          </p>
        </div>
        <div className="shrink-0 text-right">
          <p className="font-mono text-3xl font-bold tabular-nums leading-none">
            {elapsed(serving.consult_start, now)}
          </p>
          <p className="mt-1 text-[11px] uppercase tracking-wide text-white/70">{t("consult")}</p>
        </div>
      </div>
    </div>
  );
}
