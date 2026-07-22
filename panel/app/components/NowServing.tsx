"use client";

import { elapsed } from "../lib/format";
import { STRINGS } from "../lib/i18n";
import type { NowServing as NS } from "../lib/types";

export function NowServing({ serving, now }: { serving: NS | null; now: number }) {
  if (!serving) {
    return (
      <div className="rounded-xl2 border border-dashed border-line bg-surface/60 px-5 py-6 text-center">
        <p className="text-sm font-medium uppercase tracking-wide text-faint">
          {STRINGS.nowServing.hi}
        </p>
        <p className="mt-1 text-lg font-semibold text-muted">{STRINGS.noneServing.hi}</p>
      </div>
    );
  }
  return (
    <div className="animate-pulse-ring rounded-xl2 bg-primary px-5 py-4 text-white shadow-card">
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold uppercase tracking-widest text-white/70">
          {STRINGS.nowServing.hi} · {STRINGS.nowServing.en}
        </p>
        <span className="rounded-full bg-white/15 px-2.5 py-0.5 text-xs font-semibold">
          {STRINGS.token.hi} #{serving.token_number}
        </span>
      </div>
      <div className="mt-2 flex items-end justify-between">
        <div className="min-w-0">
          <p className="truncate text-3xl font-bold leading-tight">
            {serving.name || `${STRINGS.token.hi} #${serving.token_number}`}
          </p>
        </div>
        <div className="shrink-0 text-right">
          <p className="font-mono text-3xl font-bold tabular-nums leading-none">
            {elapsed(serving.consult_start, now)}
          </p>
          <p className="mt-1 text-[11px] uppercase tracking-wide text-white/70">consult</p>
        </div>
      </div>
    </div>
  );
}
