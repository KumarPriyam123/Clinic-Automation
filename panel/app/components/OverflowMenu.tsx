"use client";

import Link from "next/link";
import { useLocale } from "../lib/locale";
import type { Lang } from "@/lib/i18n";
import { Sheet } from "./Sheet";

const LANGS: { value: Lang; key: "langHi" | "langEn" }[] = [
  { value: "hi", key: "langHi" },
  { value: "en", key: "langEn" },
];

/** The `⋯` overflow sheet: language, settings, hard reload.
 *
 * The language toggle lives here rather than on the main surface deliberately —
 * it must not compete with NEXT for thumb space, and it must not be reachable
 * by an accidental tap during a session. */
export function OverflowMenu({
  open,
  onClose,
  onReload,
}: {
  open: boolean;
  onClose: () => void;
  onReload: () => void;
}) {
  const { t, lang, setLang } = useLocale();

  return (
    <Sheet open={open} onClose={onClose} title={t("more")}>
      <div className="grid gap-3">
        <div>
          <p className="mb-1.5 px-1 text-sm font-medium text-muted">{t("language")}</p>
          <div className="grid grid-cols-2 gap-2">
            {LANGS.map((l) => (
              <button
                key={l.value}
                onClick={() => setLang(l.value)}
                aria-pressed={lang === l.value}
                className={`h-touch w-full rounded-2xl px-3 text-lg font-semibold transition ${
                  lang === l.value
                    ? "bg-primary text-white"
                    : "border border-line bg-surface text-muted"
                }`}
              >
                {t(l.key)}
              </button>
            ))}
          </div>
        </div>

        <Link href="/settings" className="btn-ghost h-touch w-full" onClick={onClose}>
          ⚙ {t("settings")}
        </Link>

        {/* Unregisters the SW, clears caches, hard-reloads. First thing to try
            if the screen looks wrong (see ONBOARDING.md). */}
        <button className="btn-ghost h-touch w-full" onClick={onReload}>
          ↺ {t("reload")}
        </button>

        <button className="btn-ghost mt-1 h-touch w-full border-0" onClick={onClose}>
          {t("close")}
        </button>
      </div>
    </Sheet>
  );
}
