export type EntryStatus =
  | "booked"
  | "arrived"
  | "called"
  | "in_consult"
  | "skipped"
  | "done"
  | "cancelled"
  | "expired";

export type SessionStatus =
  | "scheduled"
  | "open"
  | "paused"
  | "closed"
  | "cancelled";

export interface SessionMeta {
  id: string;
  name: string;
  status: SessionStatus;
  date: string;
  start_at: string | null;
  end_at: string | null;
  token_cap: number;
  avg_consult_s: number;
  doctor_free_at: string | null;
  served: number;
  waiting: number;
  allowed_actions: string[];
  /** True for any day but today: preview only. The backend rejects mutations. */
  read_only: boolean;
}

export interface NowServing {
  entry_id: string;
  token_number: number;
  name: string;
  consult_start: string | null;
}

export interface QueueEntry {
  entry_id: string;
  token_number: number;
  name: string;
  status: EntryStatus;
  source: string;
  priority_time: string | null;
  eta: string | null;
  report_time: string | null;
  arrived_at: string | null;
  grace_until: string | null;
  next_up: boolean;
}

export interface SessionListItem {
  id: string;
  name: string;
  status: SessionStatus;
  date: string;
  start_at: string | null;
  end_at: string | null;
}

/** Bookings already waiting in tomorrow's queue — the after-hours capture. */
export interface Upcoming {
  date: string;
  count: number;
}

export interface QueueSnapshot {
  session: SessionMeta | null;
  now_serving: NowServing | null;
  entries: QueueEntry[];
  sessions?: SessionListItem[];
  upcoming?: Upcoming;
  can_undo?: boolean;
}

export interface TimetableRow {
  weekday: number;
  name: string;
  start_time: string;
  end_time: string;
  token_cap: number;
}

export interface SettingsPayload {
  clinic: {
    slug: string;
    name: string;
    doctor_name: string;
    specialty: string | null;
    fee_inr: number | null;
    language: "hi" | "en";
    settings: Record<string, unknown>;
  };
  timetable: TimetableRow[];
}
