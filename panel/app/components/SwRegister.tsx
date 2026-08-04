"use client";

import { useEffect } from "react";

/** One id per build, injected by next.config.mjs. */
const BUILD_ID = process.env.NEXT_PUBLIC_BUILD_ID ?? "dev";

/** Registers the PWA service worker once, after load, in production-like use.
 *
 * The `?v=<BUILD_ID>` is load-bearing, not decoration. Registering a *different*
 * script URL is what makes the browser fetch and install a new worker; with a
 * fixed "/sw.js" a device can sit on an installed worker and keep serving a
 * previous build's assets. It also feeds the worker its cache name, so each
 * deploy gets a fresh cache and activate() evicts the old ones.
 */
export function SwRegister() {
  useEffect(() => {
    if (typeof navigator === "undefined" || !("serviceWorker" in navigator)) return;
    const onLoad = () => {
      navigator.serviceWorker.register(`/sw.js?v=${encodeURIComponent(BUILD_ID)}`).catch(() => {
        /* offline shell is best-effort */
      });
    };
    if (document.readyState === "complete") onLoad();
    else window.addEventListener("load", onLoad, { once: true });
    return () => window.removeEventListener("load", onLoad);
  }, []);
  return null;
}
