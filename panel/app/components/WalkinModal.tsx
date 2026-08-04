"use client";

import { useEffect, useRef, useState } from "react";
import { useLocale } from "../lib/locale";
import { Sheet } from "./Sheet";

/** Walk-in add — the only place the keyboard is needed. Name required (autofocus),
 * phone optional. Two taps total: [+ Walk-in] then [Add] after typing a name. */
export function WalkinModal({
  open,
  emergency,
  onClose,
  onSubmit,
}: {
  open: boolean;
  emergency?: boolean;
  onClose: () => void;
  onSubmit: (name: string, phone?: string) => void;
}) {
  const { t } = useLocale();
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const nameRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) {
      setName("");
      setPhone("");
      setTimeout(() => nameRef.current?.focus(), 120);
    }
  }, [open]);

  const submit = () => {
    if (!name.trim()) return;
    onSubmit(name.trim(), phone.trim() || undefined);
  };

  return (
    <Sheet open={open} onClose={onClose} title={emergency ? t("emergency") : t("addWalkin")}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
        className="grid gap-3"
      >
        <input
          ref={nameRef}
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder={t("name")}
          className="field h-touch"
          autoComplete="off"
          enterKeyHint="done"
        />
        <input
          value={phone}
          onChange={(e) => setPhone(e.target.value)}
          placeholder={t("phone")}
          className="field h-touch"
          inputMode="tel"
          autoComplete="off"
        />
        <button
          type="submit"
          disabled={!name.trim()}
          className={`h-touch w-full ${emergency ? "btn-danger" : "btn-primary"} disabled:opacity-50`}
        >
          ＋ {emergency ? t("emergency") : t("add")}
        </button>
      </form>
    </Sheet>
  );
}
