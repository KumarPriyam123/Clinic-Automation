"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError, NetworkError, getToken, login } from "../lib/api";
import { useLocale } from "../lib/locale";
import { armSound } from "../lib/sound";
import type { StringKey } from "@/lib/i18n";

/** What actually went wrong, never a guess.
 *
 * `wrongPin` is the ONLY message allowed on a 401, and 401 is the only thing
 * allowed to produce it. The panel used to show it for every failure — a CORS
 * block on a new origin then read as "your PIN stopped working", which is the
 * one thing that was never wrong. */
interface LoginError {
  key: StringKey;
  /** HTTP status, shown small and muted so a clinic's screenshot is diagnostic. */
  status?: number;
}

function classify(e: unknown): LoginError {
  if (e instanceof NetworkError) return { key: "cannotReachServer" };
  if (e instanceof ApiError) {
    if (e.status === 401) return { key: "wrongPin" };
    return { key: "serverError", status: e.status };
  }
  return { key: "serverError" };
}

export default function LoginPage() {
  const router = useRouter();
  const { t } = useLocale();
  const [slug, setSlug] = useState("");
  const [pin, setPin] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<LoginError | null>(null);

  useEffect(() => {
    if (getToken()) router.replace("/");
  }, [router]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setErr(null);
    try {
      armSound(); // first user gesture — unlock the arrival chime for the queue
      await login(slug.trim(), pin.trim());
      router.replace("/");
    } catch (e) {
      setErr(classify(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="flex min-h-screen flex-col justify-center px-6 pb-10">
      <div className="mx-auto w-full max-w-sm">
        <div className="mb-8 text-center">
          <div className="mx-auto mb-3 flex h-16 w-16 items-center justify-center rounded-2xl bg-primary text-3xl font-bold text-white shadow-card">
            Q
          </div>
          <h1 className="text-2xl font-bold text-ink">{t("appName")}</h1>
          <p className="text-sm text-muted">{t("login")}</p>
        </div>

        <form onSubmit={submit} className="grid gap-4">
          <label className="grid gap-1.5">
            <span className="px-1 text-sm font-medium text-muted">{t("slug")}</span>
            <input
              value={slug}
              onChange={(e) => setSlug(e.target.value)}
              placeholder="demo"
              autoCapitalize="none"
              autoCorrect="off"
              autoComplete="username"
              className="field h-16 tracking-wide"
            />
          </label>
          <label className="grid gap-1.5">
            <span className="px-1 text-sm font-medium text-muted">{t("pin")}</span>
            <input
              value={pin}
              onChange={(e) => setPin(e.target.value.replace(/\D/g, "").slice(0, 6))}
              placeholder="••••••"
              inputMode="numeric"
              autoComplete="current-password"
              className="field h-16 text-center text-3xl tracking-[0.5em]"
            />
          </label>

          {err && (
            <p className="rounded-xl bg-danger-soft px-4 py-2.5 text-center text-sm font-semibold text-danger">
              {t(err.key)}
              {err.status !== undefined && (
                <span className="ml-1.5 font-normal opacity-70">HTTP {err.status}</span>
              )}
            </p>
          )}

          <button
            type="submit"
            disabled={busy || slug.trim().length === 0 || pin.length < 6}
            className="btn-primary h-16 w-full px-4 text-xl disabled:opacity-50"
          >
            <span className="truncate">{busy ? "…" : `${t("enter")} →`}</span>
          </button>
        </form>
      </div>
    </main>
  );
}
