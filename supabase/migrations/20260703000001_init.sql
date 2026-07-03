-- ClinicQ initial schema (build doc §4). Multi-tenant by clinic_id from day one.
-- All timestamps timestamptz UTC; clinic tz = Asia/Kolkata for display.

create extension if not exists pgcrypto;  -- gen_random_uuid()

-- clinics: one row per clinic (multi-tenant from day one)
create table clinics (
  id            uuid primary key default gen_random_uuid(),
  slug          text unique not null,           -- panel login
  pin_hash      text not null,                  -- 6-digit PIN, bcrypt
  name          text not null,
  doctor_name   text not null,
  specialty     text,
  address       text,
  fee_inr       int,
  wa_phone_number_id text,                      -- Meta phone number id
  wa_display_number  text,
  language      text not null default 'hi',     -- 'hi' | 'en'
  timezone      text not null default 'Asia/Kolkata',
  settings      jsonb not null default '{}',    -- policy overrides (§3 defaults)
  created_at    timestamptz default now()
);

-- weekly timetable template (sessions are stamped out from this)
create table timetable (
  id         uuid primary key default gen_random_uuid(),
  clinic_id  uuid references clinics not null,
  weekday    int not null,                      -- 0=Mon … 6=Sun
  name       text not null,                     -- 'morning' | 'evening'
  start_time time not null,
  end_time   time not null,
  token_cap  int not null default 40
);

-- a concrete session (one queue) on one date
create table sessions (
  id              uuid primary key default gen_random_uuid(),
  clinic_id       uuid references clinics not null,
  date            date not null,
  name            text not null,
  start_at        timestamptz not null,
  end_at          timestamptz not null,
  token_cap       int not null,
  status          text not null default 'scheduled',
      -- scheduled | open | paused | closed | cancelled
  doctor_free_at  timestamptz,                  -- live clock; null until opened
  avg_consult_s   int not null default 420,     -- rolling avg, seeded 7 min
  consults_done   int not null default 0,
  updated_at      timestamptz not null default now(),  -- maintained by trigger
  unique (clinic_id, date, name)
);

create table patients (
  id           uuid primary key default gen_random_uuid(),
  clinic_id    uuid references clinics not null,
  wa_number    text not null,                   -- E.164
  profile_name text not null default 'self',    -- family sub-profile
  display_name text,
  strikes      int not null default 0,
  blocked_until timestamptz,
  created_at   timestamptz default now(),
  unique (clinic_id, wa_number, profile_name)
);

create table queue_entries (
  id             uuid primary key default gen_random_uuid(),
  session_id     uuid references sessions not null,
  clinic_id      uuid references clinics not null,
  patient_id     uuid references patients not null,
  token_number   int not null,                  -- fixed at booking, per session
  priority_time  timestamptz not null,          -- THE sort key
  booked_at      timestamptz not null default now(),
  status         text not null default 'booked',
      -- booked|arrived|called|in_consult|done|skipped|expired|cancelled
  source         text not null default 'whatsapp',  -- whatsapp|walkin|panel
  eta            timestamptz,
  report_time    timestamptz,
  arrived_at     timestamptz,
  called_at      timestamptz,
  consult_start  timestamptz,
  done_at        timestamptz,
  grace_until    timestamptz,
  skip_count     int not null default 0,
  gap_offered_at timestamptz,
  updated_at     timestamptz not null default now(),  -- maintained by trigger
  unique (session_id, token_number)
);
create index qe_sort on queue_entries (session_id, priority_time, booked_at);
create index qe_status on queue_entries (session_id, status);

-- append-only audit log → powers analytics + ETA learning
create table events (
  id         bigint generated always as identity primary key,
  clinic_id  uuid not null,
  session_id uuid,
  entry_id   uuid,
  type       text not null,   -- booked|cancelled|arrived|called|skipped|
                              -- grace_expired|done|gap_offered|gap_taken|
                              -- delay_broadcast|session_opened|session_closed|walkin
  payload    jsonb not null default '{}',
  created_at timestamptz default now()
);

-- WhatsApp delivery log (idempotency by wamid, debugging, cost tracking)
create table wa_messages (
  id          bigint generated always as identity primary key,
  clinic_id   uuid,
  wa_number   text not null,
  direction   text not null,             -- in | out
  wamid       text unique,               -- dedupe inbound webhooks
  kind        text,                      -- text|button|template:<name>
  payload     jsonb,
  created_at  timestamptz default now()
);

-- per-user conversation state for multi-turn booking
create table conversations (
  wa_number   text not null,
  clinic_id   uuid not null,
  state       text not null default 'idle',
      -- idle|choosing_session|choosing_time|choosing_profile|confirm_cancel
  context     jsonb not null default '{}',
  updated_at  timestamptz default now(),
  primary key (wa_number, clinic_id)
);

-- updated_at trigger (addition): touch on every UPDATE of sessions & queue_entries
create or replace function set_updated_at()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

create trigger trg_sessions_updated_at
  before update on sessions
  for each row execute function set_updated_at();

create trigger trg_queue_entries_updated_at
  before update on queue_entries
  for each row execute function set_updated_at();
