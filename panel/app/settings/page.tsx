"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import * as api from "../lib/api";
import { getToken, logout } from "../lib/api";
import { useLocale } from "../lib/locale";
import type { SettingsPayload, TimetableRow } from "../lib/types";
import type { StringKey } from "@/lib/i18n";

/** `timetable.weekday` is 0=Monday. */
const WEEKDAY_KEYS: StringKey[] = ["wd0", "wd1", "wd2", "wd3", "wd4", "wd5", "wd6"];

export default function SettingsPage() {
  const router = useRouter();
  const { t } = useLocale();
  const [data, setData] = useState<SettingsPayload | null>(null);
  const [tt, setTt] = useState<TimetableRow[]>([]);
  const [pin, setPin] = useState("");
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [err, setErr] = useState<StringKey | null>(null);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    api
      .fetchSettings()
      .then((d) => {
        setData(d);
        setTt(d.timetable);
      })
      .catch(() => setErr("loadFailed"));
  }, [router]);

  if (!data) {
    return <main className="flex min-h-screen items-center justify-center text-muted">…</main>;
  }

  const patchClinic = (p: Partial<SettingsPayload["clinic"]>) =>
    setData({ ...data, clinic: { ...data.clinic, ...p } });
  const patchSetting = (k: string, v: unknown) =>
    patchClinic({ settings: { ...data.clinic.settings, [k]: v } });
  const patchRow = (i: number, p: Partial<TimetableRow>) =>
    setTt(tt.map((r, idx) => (idx === i ? { ...r, ...p } : r)));

  const gapOffers = data.clinic.settings.gap_offers !== false;

  const save = async () => {
    setBusy(true);
    setSaved(false);
    setErr(null);
    try {
      const payload: Record<string, unknown> = {
        name: data.clinic.name,
        doctor_name: data.clinic.doctor_name,
        specialty: data.clinic.specialty,
        fee_inr: data.clinic.fee_inr,
        language: data.clinic.language,
        settings: data.clinic.settings,
        timetable: tt,
      };
      if (pin) {
        if (!/^\d{6}$/.test(pin)) {
          setErr("pinSixDigits");
          setBusy(false);
          return;
        }
        payload.new_pin = pin;
      }
      const res = await api.saveSettings(payload);
      setData(res);
      setTt(res.timetable);
      setPin("");
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch {
      setErr("saveFailed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="min-h-screen pb-28">
      <div className="mx-auto w-full max-w-md px-4 pt-4">
        <div className="mb-4 flex items-center gap-3">
          <Link
            href="/"
            className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-line bg-surface text-xl active:bg-canvas"
          >
            ‹
          </Link>
          <h1 className="truncate text-xl font-bold text-ink">{t("settings")}</h1>
        </div>

        {/* clinic profile */}
        <Card title={t("cardClinic")}>
          <Field
            label={t("fieldName")}
            value={data.clinic.name}
            onChange={(v) => patchClinic({ name: v })}
          />
          <Field
            label={t("fieldDoctor")}
            value={data.clinic.doctor_name}
            onChange={(v) => patchClinic({ doctor_name: v })}
          />
          <Field
            label={t("fieldSpecialty")}
            value={data.clinic.specialty ?? ""}
            onChange={(v) => patchClinic({ specialty: v })}
          />
          <Field
            label={t("fieldFee")}
            value={data.clinic.fee_inr?.toString() ?? ""}
            inputMode="numeric"
            onChange={(v) => patchClinic({ fee_inr: v ? Number(v.replace(/\D/g, "")) : null })}
          />
        </Card>

        {/* clinic-level options. NOTE: this language field is the language
            PATIENTS get on WhatsApp; the panel's own locale is the ⋯ menu. */}
        <Card title={t("cardLangOptions")}>
          <Row label={t("clinicLanguage")}>
            <div className="flex shrink-0 gap-2">
              {(["hi", "en"] as const).map((l) => (
                <button
                  key={l}
                  onClick={() => patchClinic({ language: l })}
                  className={`h-11 min-w-[4rem] rounded-xl px-3 text-base font-semibold ${
                    data.clinic.language === l
                      ? "bg-primary text-white"
                      : "border border-line bg-surface text-muted"
                  }`}
                >
                  {l === "hi" ? t("langHi") : t("langEn")}
                </button>
              ))}
            </div>
          </Row>
          <Row label={t("gapOffers")}>
            <Toggle on={gapOffers} onToggle={() => patchSetting("gap_offers", !gapOffers)} />
          </Row>
        </Card>

        {/* weekly timetable */}
        <Card title={t("cardTimetable")}>
          <div className="grid gap-2">
            {tt.length === 0 && <p className="text-sm text-faint">{t("noTimetableRows")}</p>}
            {tt.map((r, i) => (
              <div key={i} className="rounded-xl border border-line bg-canvas p-2.5">
                <div className="mb-2 flex items-center justify-between gap-2">
                  <span className="truncate text-sm font-semibold text-ink">
                    {t(WEEKDAY_KEYS[r.weekday] ?? "wd0")} · {r.name}
                  </span>
                  <button
                    onClick={() => setTt(tt.filter((_, idx) => idx !== i))}
                    className="shrink-0 text-sm font-semibold text-danger"
                  >
                    {t("remove")}
                  </button>
                </div>
                <div className="grid grid-cols-3 gap-2">
                  <TimeInput
                    label={t("startTime")}
                    value={r.start_time}
                    onChange={(v) => patchRow(i, { start_time: v })}
                  />
                  <TimeInput
                    label={t("endTime")}
                    value={r.end_time}
                    onChange={(v) => patchRow(i, { end_time: v })}
                  />
                  <label className="grid gap-1">
                    <span className="truncate px-0.5 text-[11px] text-faint">{t("tokenCap")}</span>
                    <input
                      value={r.token_cap}
                      inputMode="numeric"
                      onChange={(e) =>
                        patchRow(i, { token_cap: Number(e.target.value.replace(/\D/g, "")) || 0 })
                      }
                      className="h-11 w-full rounded-lg border border-line bg-surface px-2 text-center text-base tabular-nums outline-none focus:border-primary"
                    />
                  </label>
                </div>
              </div>
            ))}
            <button
              onClick={() =>
                setTt([
                  ...tt,
                  { weekday: 0, name: "morning", start_time: "09:00", end_time: "13:00", token_cap: 40 },
                ])
              }
              className="btn-ghost h-touch w-full border-dashed px-3"
            >
              <span className="truncate">＋ {t("addTimetableRow")}</span>
            </button>
          </div>
        </Card>

        {/* change PIN */}
        <Card title={t("cardChangePin")}>
          <input
            value={pin}
            onChange={(e) => setPin(e.target.value.replace(/\D/g, "").slice(0, 6))}
            placeholder={t("newPinPlaceholder")}
            inputMode="numeric"
            className="field h-touch text-center text-2xl tracking-[0.4em]"
          />
        </Card>

        {err && (
          <p className="mb-3 rounded-xl bg-danger-soft px-4 py-2.5 text-center text-sm font-semibold text-danger">
            {t(err)}
          </p>
        )}

        <button onClick={logout} className="btn-ghost mb-24 h-touch w-full text-danger">
          {t("logout")}
        </button>
      </div>

      {/* fixed save bar */}
      <div className="safe-bottom fixed inset-x-0 bottom-0 z-30 bg-gradient-to-t from-canvas via-canvas/95 to-transparent px-4 pb-3 pt-6">
        <button
          onClick={save}
          disabled={busy}
          className="btn-primary h-next w-full px-4 text-xl disabled:opacity-60"
        >
          <span className="truncate">
            {saved ? `✓ ${t("saved")}` : busy ? "…" : t("save")}
          </span>
        </button>
      </div>
    </main>
  );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-3 rounded-xl2 bg-surface p-4 shadow-card">
      <h2 className="mb-3 text-sm font-bold uppercase tracking-wide text-faint">{title}</h2>
      <div className="grid gap-3">{children}</div>
    </section>
  );
}

function Field({
  label,
  value,
  onChange,
  inputMode,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  inputMode?: "text" | "numeric";
}) {
  return (
    <label className="grid gap-1">
      <span className="px-0.5 text-xs font-medium text-muted">{label}</span>
      <input
        value={value}
        inputMode={inputMode}
        onChange={(e) => onChange(e.target.value)}
        className="h-12 w-full rounded-xl border border-line bg-canvas px-3 text-base text-ink outline-none focus:border-primary"
      />
    </label>
  );
}

function TimeInput({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <label className="grid gap-1">
      <span className="truncate px-0.5 text-[11px] text-faint">{label}</span>
      <input
        type="time"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="h-11 w-full min-w-0 rounded-lg border border-line bg-surface px-1 text-center text-base outline-none focus:border-primary"
      />
    </label>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="min-w-0 text-base font-medium text-ink">{label}</span>
      {children}
    </div>
  );
}

function Toggle({ on, onToggle }: { on: boolean; onToggle: () => void }) {
  return (
    <button
      onClick={onToggle}
      className={`relative h-8 w-14 shrink-0 rounded-full transition ${on ? "bg-primary" : "bg-neutral-bg"}`}
      aria-pressed={on}
    >
      <span
        className={`absolute top-1 h-6 w-6 rounded-full bg-white shadow transition-all ${
          on ? "left-7" : "left-1"
        }`}
      />
    </button>
  );
}
