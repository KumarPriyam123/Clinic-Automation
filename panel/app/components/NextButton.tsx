"use client";

import { useLocale } from "../lib/locale";

/** The one button that does 90% of the job: full-width, 72px tall, fixed to the
 * bottom, thumb-reachable. Serves the first ARRIVED patient (engine rule 3). */
export function NextButton({
  onClick,
  disabled,
  waiting,
}: {
  onClick: () => void;
  disabled?: boolean;
  waiting: number;
}) {
  const { t } = useLocale();
  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-0 z-30">
      <div className="safe-bottom pointer-events-auto bg-gradient-to-t from-canvas via-canvas/95 to-transparent px-4 pb-3 pt-6">
        <button
          onClick={onClick}
          disabled={disabled}
          className="flex h-next w-full items-center justify-center gap-3 rounded-2xl bg-primary px-4 text-2xl font-bold text-white shadow-lift transition active:scale-[0.985] active:bg-primary-dark disabled:bg-neutral-fg/40 disabled:text-white/70"
        >
          <span className="truncate">{t("next")}</span>
          <span className="shrink-0 text-lg font-medium text-white/70">›</span>
          {waiting > 0 && (
            <span className="ml-1 shrink-0 rounded-full bg-white/20 px-2.5 py-0.5 text-base tabular-nums">
              {waiting}
            </span>
          )}
        </button>
      </div>
    </div>
  );
}
