"use client";

import { useEffect, useState } from "react";
import { API_BASE } from "../lib/api";

/**
 * Developer guard: this bundle is being served from a dev machine but is wired
 * to a remote backend.
 *
 * During P8, `panel/.env.local` held the production URL and local test probes
 * reached the live pilot clinic. That was read-only and harmless. The same
 * misconfiguration during a mutation phase means a test run calling NEXT or a
 * session mutation against a real clinic's queue.
 *
 * Deliberately NOT translated and deliberately not in `lib/i18n.ts`: this is a
 * developer surface, never shown to a clinic, and the dictionary is for patient
 * and staff copy only.
 */

function isLocalHostname(hostname: string): boolean {
  return hostname === "localhost" || hostname === "127.0.0.1";
}

/** True when `base` is an absolute URL pointing somewhere other than this machine. */
export function isRemoteApiBase(base: string): boolean {
  // A relative base ("/api") is same-origin by construction and always safe.
  if (!/^https?:\/\//i.test(base)) return false;
  try {
    return !isLocalHostname(new URL(base).hostname);
  } catch {
    return false;
  }
}

/**
 * Gated on HOSTNAME, not NODE_ENV.
 *
 * `next build && next start` on a laptop sets NODE_ENV=production, which is
 * exactly the run you most want warned about — a NODE_ENV gate would go silent
 * there. Keying on hostname also makes the banner structurally incapable of
 * appearing on the deployed panel: app.clinicq.kpriyam.me is never "localhost",
 * so the first condition can never hold in production no matter how the API
 * base is configured.
 */
export function shouldWarn(hostname: string, base: string): boolean {
  return isLocalHostname(hostname) && isRemoteApiBase(base);
}

export function ProdBackendWarning() {
  // Rendered only after mount: the check reads window.location, and the server
  // has no hostname to test.
  const [warn, setWarn] = useState(false);

  useEffect(() => {
    setWarn(shouldWarn(window.location.hostname, API_BASE));
  }, []);

  if (!warn) return null;

  return (
    <div
      role="alert"
      className="fixed inset-x-0 top-0 z-[100] flex flex-wrap items-center justify-center gap-x-2 bg-red-600 px-3 py-1.5 text-center text-xs font-bold uppercase tracking-wide text-white"
    >
      <span>⚠ PROD BACKEND</span>
      <span className="font-mono text-[11px] font-normal normal-case tracking-normal opacity-90">
        {API_BASE}
      </span>
    </div>
  );
}
