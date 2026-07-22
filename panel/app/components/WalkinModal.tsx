"use client";

import { useEffect, useRef, useState } from "react";
import { STRINGS } from "../lib/i18n";
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
    <Sheet
      open={open}
      onClose={onClose}
      title={emergency ? STRINGS.emergency.hi : STRINGS.addWalkin.hi}
    >
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
          placeholder={STRINGS.name.hi}
          className="field h-touch"
          autoComplete="off"
          enterKeyHint="done"
        />
        <input
          value={phone}
          onChange={(e) => setPhone(e.target.value)}
          placeholder={STRINGS.phone.hi}
          className="field h-touch"
          inputMode="tel"
          autoComplete="off"
        />
        <button
          type="submit"
          disabled={!name.trim()}
          className={`h-touch w-full ${emergency ? "btn-danger" : "btn-primary"} disabled:opacity-50`}
        >
          {emergency ? `＋ ${STRINGS.emergency.hi}` : `＋ ${STRINGS.add.hi}`}
        </button>
      </form>
    </Sheet>
  );
}
