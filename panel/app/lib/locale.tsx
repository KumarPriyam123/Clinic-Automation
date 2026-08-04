"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { getClinic } from "./api";
import { type Lang, type Pair, type StringKey, pick, strings } from "@/lib/i18n";

const LANG_KEY = "clinicq.lang";

/** SSR and the first client render must agree, so both start at `hi`. The real
 * locale is resolved in an effect (localStorage override → clinic default). */
const DEFAULT_LANG: Lang = "hi";

function isLang(v: string | null): v is Lang {
  return v === "hi" || v === "en";
}

/** Manual override, if the user has ever picked one. Wins over `clinic.language`. */
function storedLang(): Lang | null {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem(LANG_KEY);
  return isLang(raw) ? raw : null;
}

interface LocaleValue {
  lang: Lang;
  /** Persists the choice; it then wins over the clinic default on every load. */
  setLang: (lang: Lang) => void;
  /** Look up a dictionary key in the current locale. */
  t: (key: StringKey) => string;
  /** Resolve an already-built `Pair` (interpolated templates). */
  p: (pair: Pair) => string;
}

const LocaleContext = createContext<LocaleValue | null>(null);

export function LocaleProvider({ children }: { children: React.ReactNode }) {
  const [lang, setLangState] = useState<Lang>(DEFAULT_LANG);

  // Resolve after mount: manual override first, then the clinic's own language
  // from the login response. Keeping this in an effect avoids a hydration
  // mismatch against the server-rendered `hi` markup.
  useEffect(() => {
    const resolved = storedLang() ?? getClinic()?.language ?? DEFAULT_LANG;
    setLangState(resolved);
  }, []);

  // `<html lang>` must track the locale: assistive tech and font shaping both
  // read it, and a truthful `lang` is half of the anti-auto-translate signal.
  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);

  const setLang = useCallback((next: Lang) => {
    window.localStorage.setItem(LANG_KEY, next);
    setLangState(next);
  }, []);

  const value = useMemo<LocaleValue>(
    () => ({
      lang,
      setLang,
      t: (key: StringKey) => pick(strings[key], lang),
      p: (pair: Pair) => pick(pair, lang),
    }),
    [lang, setLang],
  );

  return <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>;
}

export function useLocale(): LocaleValue {
  const ctx = useContext(LocaleContext);
  if (!ctx) throw new Error("useLocale must be used inside <LocaleProvider>");
  return ctx;
}
