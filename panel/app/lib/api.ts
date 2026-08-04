import type { QueueSnapshot, SettingsPayload } from "./types";

// Default: same-origin /api so a single ngrok tunnel on :3000 works out of the
// box.  Set NEXT_PUBLIC_API_URL to an absolute backend URL (e.g. the droplet)
// for Vercel production — that mode bypasses the Next.js proxy rewrite entirely.
const BASE =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "/api";
const API = `${BASE}/panel`;

/** The resolved API base, exported so the dev-only prod-backend guard can see
 * what this bundle was actually built against. */
export const API_BASE = BASE;

const TOKEN_KEY = "clinicq.token";
const CLINIC_KEY = "clinicq.clinic";

export interface ClinicInfo {
  name: string;
  slug: string;
  language: "hi" | "en";
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function getClinic(): ClinicInfo | null {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem(CLINIC_KEY);
  return raw ? (JSON.parse(raw) as ClinicInfo) : null;
}

function setSession(token: string, clinic: ClinicInfo) {
  window.localStorage.setItem(TOKEN_KEY, token);
  window.localStorage.setItem(CLINIC_KEY, JSON.stringify(clinic));
}

export function logout() {
  window.localStorage.removeItem(TOKEN_KEY);
  window.localStorage.removeItem(CLINIC_KEY);
  window.location.href = "/login";
}

/** The server answered, and said no. `status` is a real HTTP status. */
export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, detail: unknown, message: string) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

/**
 * The request never reached the server, or the answer was unreadable: DNS
 * failure, offline radio, a CORS block on a new panel origin, a TLS error.
 *
 * This class exists because collapsing it into ApiError is what let the login
 * screen tell a clinic their PIN was wrong when the browser had in fact refused
 * to send the request at all. "The server said no" and "there was no server"
 * are different facts and the person reading the screen cannot tell them apart
 * unless the code does.
 */
export class NetworkError extends Error {
  cause: unknown;
  constructor(cause: unknown) {
    super("network unreachable");
    this.cause = cause;
  }
}

async function request<T>(
  path: string,
  init: RequestInit = {},
  { auth = true }: { auth?: boolean } = {},
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init.headers as Record<string, string>),
  };
  if (auth) {
    const token = getToken();
    if (!token) throw new ApiError(401, null, "not authenticated");
    headers.Authorization = `Bearer ${token}`;
  }

  let res: Response;
  try {
    res = await fetch(`${API}${path}`, { ...init, headers });
  } catch (e) {
    // fetch only rejects when the request never completed — never for a 4xx/5xx.
    throw new NetworkError(e);
  }

  if (res.status === 401 && auth) {
    logout();
    throw new ApiError(401, null, "session expired");
  }

  // A body we cannot parse is a broken response, not a network failure: keep the
  // status so the caller still reports "server error 502" rather than guessing.
  let data: unknown = null;
  try {
    const text = await res.text();
    data = text ? JSON.parse(text) : null;
  } catch {
    if (res.ok) throw new ApiError(res.status, null, `unparsable ${res.status}`);
    data = null;
  }

  if (!res.ok) {
    const detail = (data as { detail?: unknown } | null)?.detail ?? data;
    throw new ApiError(res.status, detail, `${res.status}`);
  }
  return data as T;
}

// --- auth ---------------------------------------------------------------- //
export async function login(slug: string, pin: string): Promise<ClinicInfo> {
  const res = await request<{ token: string; clinic: ClinicInfo }>(
    "/login",
    { method: "POST", body: JSON.stringify({ slug, pin }) },
    { auth: false },
  );
  setSession(res.token, res.clinic);
  return res.clinic;
}

// --- queue --------------------------------------------------------------- //
export const fetchToday = () => request<QueueSnapshot>("/session/today");
/** Any single day (ISO "YYYY-MM-DD"). Days other than today come back read_only. */
export const fetchDay = (date: string) =>
  request<QueueSnapshot>(`/session/day?date=${date}`);
export const fetchQueue = (sessionId: string) =>
  request<QueueSnapshot>(`/queue?session_id=${sessionId}`);

const body = (o: unknown) => JSON.stringify(o);

export const next = (sessionId: string) =>
  request<QueueSnapshot>("/next", { method: "POST", body: body({ session_id: sessionId }) });

export const walkin = (sessionId: string, name: string, phone?: string) =>
  request<QueueSnapshot>(`/walkin?session_id=${sessionId}`, {
    method: "POST",
    body: body({ name, phone: phone || null }),
  });

export const emergency = (sessionId: string, name: string, phone?: string) =>
  request<QueueSnapshot>(`/emergency?session_id=${sessionId}`, {
    method: "POST",
    body: body({ name, phone: phone || null }),
  });

export const entryArrived = (entryId: string) =>
  request<QueueSnapshot>(`/entries/${entryId}/arrived`, { method: "POST" });
export const entryCancel = (entryId: string) =>
  request<QueueSnapshot>(`/entries/${entryId}/cancel`, { method: "POST" });
export const entryCallNow = (entryId: string) =>
  request<QueueSnapshot>(`/entries/${entryId}/call-now`, { method: "POST" });

export const delay = (sessionId: string, minutes: number) =>
  request<QueueSnapshot>(`/session/delay?session_id=${sessionId}`, {
    method: "POST",
    body: body({ minutes }),
  });
export const startSession = (sessionId: string) =>
  request<QueueSnapshot>("/session/start", { method: "POST", body: body({ session_id: sessionId }) });
export const pauseSession = (sessionId: string) =>
  request<QueueSnapshot>("/session/pause", { method: "POST", body: body({ session_id: sessionId }) });
export const resumeSession = (sessionId: string) =>
  request<QueueSnapshot>("/session/resume", { method: "POST", body: body({ session_id: sessionId }) });
export const closeSession = (sessionId: string) =>
  request<QueueSnapshot>("/session/close", { method: "POST", body: body({ session_id: sessionId }) });
export const reopenSession = (sessionId: string) =>
  request<QueueSnapshot>("/session/reopen", { method: "POST", body: body({ session_id: sessionId }) });
export const cancelToday = (sessionId: string) =>
  request<QueueSnapshot>("/session/cancel-today", {
    method: "POST",
    body: body({ session_id: sessionId }),
  });

export const undo = () => request<QueueSnapshot>("/undo", { method: "POST" });

// --- settings ------------------------------------------------------------ //
export const fetchSettings = () => request<SettingsPayload>("/settings");
export const saveSettings = (payload: Record<string, unknown>) =>
  request<SettingsPayload>("/settings", { method: "PUT", body: body(payload) });
