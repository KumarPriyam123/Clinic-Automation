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

/** "in 12 min" / "now" / "5 min late" style relative label for an ETA. */
export function relEta(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "—";
  const m = minutesUntil(iso, now);
  if (m <= 0) return "अभी / now";
  if (m < 60) return `${m} मिनट / min`;
  const h = Math.floor(m / 60);
  return `${h}घ ${m % 60}मि`;
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
