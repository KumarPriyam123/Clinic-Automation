import { type Lang, pick, strings } from "@/lib/i18n";

const IST = "Asia/Kolkata";

/** Clock time in IST, e.g. "10:45 AM" — how the clinic reads a target/ETA. */
export function clock(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString("en-IN", {
    timeZone: IST,
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  });
}

/** Whole minutes from now until `iso` (negative if past). */
export function minutesUntil(iso: string | null | undefined, now = Date.now()): number {
  if (!iso) return 0;
  return Math.round((new Date(iso).getTime() - now) / 60000);
}

/** "12 min" / "now" style relative label for an ETA, in the panel's locale.
 *
 * `lang` is required on purpose: a defaulted locale is how mixed-language
 * screens creep back in. Only meaningful for TODAY's sessions — a future-dated
 * session shows `clock()` instead (a 10-hour countdown reads as a bug). */
export function relEta(
  iso: string | null | undefined,
  now: number,
  lang: Lang,
): string {
  if (!iso) return "—";
  const m = minutesUntil(iso, now);
  if (m <= 0) return pick(strings.relNow, lang);
  if (m < 60) return `${m} ${pick(strings.relMin, lang)}`;
  const h = Math.floor(m / 60);
  return `${h}${pick(strings.relHourShort, lang)} ${m % 60}${pick(strings.relMinShort, lang)}`;
}

/** mm:ss elapsed since a start instant — the live consult timer. */
export function elapsed(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "00:00";
  const s = Math.max(0, Math.floor((now - new Date(iso).getTime()) / 1000));
  const mm = String(Math.floor(s / 60)).padStart(2, "0");
  const ss = String(s % 60).padStart(2, "0");
  return `${mm}:${ss}`;
}

/** mm:ss remaining until a grace deadline (clamped at 0). */
export function countdown(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "0:00";
  const s = Math.max(0, Math.floor((new Date(iso).getTime() - now) / 1000));
  const mm = Math.floor(s / 60);
  const ss = String(s % 60).padStart(2, "0");
  return `${mm}:${ss}`;
}
