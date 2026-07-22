-- Per-entry idempotency stamps for the scheduler's proactive pings (P5).
-- A crashed/re-run job must never double-send: each ping checks its column is
-- null before sending, then stamps it. last_notified_eta (migration 2) guards
-- eta_shift; these two guard pre_arrival and three_away.

alter table queue_entries
  add column notified_pre_arrival_at timestamptz,
  add column notified_three_away_at  timestamptz;
