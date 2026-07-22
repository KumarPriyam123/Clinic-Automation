import type { QueueSnapshot, SettingsPayload } from "./types";

const BASE =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "http://localhost:8000";
const API = `${BASE}/panel`;

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

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, detail: unknown, message: string) {
    super(message);
    this.status = status;
    this.detail = detail;
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
  const res = await fetch(`${API}${path}`, { ...init, headers });
  if (res.status === 401 && auth) {
    logout();
    throw new ApiError(401, null, "session expired");
  }
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
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
