-- Engine runtime columns on queue_entries (additive).
--   next_up          : head-of-line flag set when a skipped patient returns
--                      within grace (arrived_during_grace) — served before all
--                      others at the next NEXT.
--   last_notified_eta: the ETA last pushed to the patient, so eta_shift pings
--                      only fire when the ETA moves > 10 min (P5 scheduler).

alter table queue_entries
  add column next_up           boolean     not null default false,
  add column last_notified_eta timestamptz;
