# ClinicQ — WhatsApp Token Queue for Local Clinics
### Complete Build Plan + Phase-wise Claude Code Prompts · v1.0 · July 2026

*(Working name "ClinicQ" — rename anytime; it appears only in code/repo names below.)*

---

## 1. What we're building (one-pager)

**Product:** A WhatsApp-based virtual token queue for single-doctor local clinics in India. Patients book, track their live position/ETA, and check in — entirely on WhatsApp. The clinic runs the queue from a dead-simple mobile web panel with one big **NEXT** button.

**Buyer:** Single-doctor clinics (GP, pediatrics, medicine) in Tier-2/3 cities that today run on a paper register + phone calls. Nobody sells to them; you do, in person.

**The one job:** *No patient waits blind, no doctor sits idle, no enquiry is lost.*

**Why patients adopt instantly:** they already live on WhatsApp (including older patients). No app install, no OTP, no payment wall.

**Why the doctor pays:** fewer no-shows (25–40% reduction is the industry-reported range for WhatsApp reminders), after-hours bookings captured, a calmer waiting room, and a weekly WhatsApp digest proving it in numbers.

**Pricing:** pilot free for 2 months (design partners) → ₹1,999/month intro (₹1,500–3,000 band). Optional setup fee later. Outcome add-ons (per recovered patient) are a v2 experiment.

**What we are deliberately NOT building in v1:** billing, pharmacy, prescriptions, EMR, multi-doctor UI, voice calls, payments. (Schema stays multi-tenant + extensible so Phase-2 records can plug in later.)

---

## 2. System architecture

```
 Patient (WhatsApp)                    Clinic (phone/desktop browser)
        │                                        │
        ▼                                        ▼
 Meta WhatsApp Cloud API              Next.js PWA "Clinic Panel" (Vercel)
        │  webhooks / send API                   │ REST (poll 4s) + actions
        ▼                                        ▼
 ┌──────────────────────────────────────────────────────────┐
 │  FastAPI backend  (DigitalOcean droplet, Cloudflare      │
 │  Tunnel public URL)                                      │
 │   • /webhook  (WhatsApp in)                              │
 │   • /api/*    (panel)                                    │
 │   • Queue Engine  ← pure, deterministic, fully tested    │
 │   • Conversation state machine (buttons-first)           │
 │   • LLM intent parser (free text only) — Gemini Flash /  │
 │     Claude Haiku, JSON-schema output                     │
 │   • APScheduler jobs: grace sweeper, ETA-drift pings,    │
 │     gap offers, session auto-close, daily digest         │
 └──────────────────────────────────────────────────────────┘
        │
        ▼
 Supabase Postgres  (single source of truth, multi-tenant by clinic_id)
```

**Key decisions (locked for v1 — each removes a failure mode):**

| Decision | v1 choice | Why / upgrade path |
|---|---|---|
| Queue state | **Postgres only** (`ORDER BY priority_time`), row-lock per session | A clinic queue is ~10–80 rows; Redis ZSET is a scale optimization for v1.1+, not a v1 need |
| Panel live updates | **Polling every 4s** + optimistic UI | Kills Realtime/RLS auth complexity for pilot; Supabase Realtime in v1.1 |
| LLM role | **Parses intent only. Never mutates state, never generates medical content.** | Reliability + cost. All state transitions are deterministic code |
| Conversation UX | **Buttons/lists first**, LLM only for free text | 80% of flows never touch the LLM |
| Panel auth | Clinic slug + 6-digit PIN → JWT | Phone-OTP needs an SMS provider; PIN is fine for pilot, OTP in v1.1 |
| Background jobs | APScheduler inside the FastAPI process | One process, one droplet. Move to a worker when >50 clinics |
| Deploy | Backend on your existing DO droplet + Cloudflare Tunnel; panel on Vercel; DB on Supabase | All infra you already run |

---

## 3. Core queue rules (the heart — this section is the spec)

**Three rules, no special cases:**

1. **Sort by `priority_time`, not booking order.** Every entry's sort key = `max(requested_time, now)` (the `max` blocks claiming past times to leapfrog people already waiting). "Come now / next available" ⇒ `priority_time = now`. Tie-break: `booked_at` (FIFO). Booking 11:00 after someone booked 12:00 correctly places you ahead. Cancel = delete row; everyone behind shifts up.

2. **ETA = forward walk from the doctor's live clock.**
   ```
   clock = max(now, session.doctor_free_at)        # doctor_free_at updated on every NEXT
   for e in active_entries ordered by (priority_time, booked_at):
       e.eta = max(clock, e.priority_time)          # never before your target time
       clock = e.eta + session.avg_consult          # rolling avg, seeded 7 min
   ```
   Doctor taps "late 30 min" ⇒ `doctor_free_at += 30m` ⇒ every ETA shifts ⇒ affected patients pinged. A cancel, a walk-in, an emergency insert — all are just re-walks.

3. **Present beats absent — presence is checked only at the moment of calling.** NEXT serves the **first ARRIVED token in priority order**. Not arrived ⇒ passed over instantly (doctor never waits), status → SKIPPED with a grace hold.

**Two times per token:** `turn_time` (= ETA) and `report_time = turn_time − buffer`, where `buffer = clamp(2 × avg_consult, 10 min, 30 min)`. Token # is assigned at booking, sequential per session, and **never changes** (it's the patient's identity at the desk); *position* is dynamic and communicated separately.

**Timers (three distinct clocks — never merge them):**

| Event | Timer | Value |
|---|---|---|
| Passed over when not present | instant | 0 — evaluated at NEXT, no timer runs |
| Grace hold after skip | short | `G = max(10 min, 2 × avg_consult)`; arrive within G ⇒ re-inserted at head of line; one extension max |
| Hard expiry | session end | any BOOKED/SKIPPED still absent ⇒ EXPIRED + strike + rebook nudge |

**Skip guard:** only skip-and-move when an ARRIVED patient is ready to take the slot. If the queue is otherwise empty (e.g. last patient of the night), let grace ride — holding beats expiring.

**Gap pull-forward (doctor never idles):** after any cancel/no-show, if `doctor_free_at + 10 min < next.priority_time`:
1. Auto-pull the earliest **ARRIVED** patient regardless of their target time (they only benefit).
2. Else offer the slot to the next 2–3 remote patients in order — button "Yes, coming earlier"; first YES rewrites their `priority_time = now`; offer expires in 5 min; max one offer ping per patient per session.
3. Else a walk-in (priority_time = now) naturally lands in the hole.
4. Else it's a genuine break.

**Token lifecycle:** `BOOKED → ARRIVED → CALLED → IN_CONSULT → DONE`, side exits `CANCELLED · SKIPPED(grace) · EXPIRED`.

**Anti-abuse ladder (v1 = layers 1–2 only):** ① WhatsApp number = SIM-backed identity; one **active** token per number (up to 3 named family profiles). ② Strikes *counted* on no-show/expiry (not enforced yet). ③ v1.1: 2 strikes ⇒ next booking needs ₹10–20 refundable UPI token fee; 3 ⇒ 2-week block. ④ Per-clinic toggle for token fee, default OFF. ⑤ Receptionist can delete junk from panel.

**Policy defaults (all per-clinic settings):** grace `max(10m, 2×avg)` · gap threshold 10 min · gap-offer expiry 5 min · ETA-change ping threshold 10 min (don't spam smaller drifts) · booking window 2 days ahead · token cap per session (doctor sets) · stop issuing tokens 30 min before close or at cap · family profiles ≤ 3.

---

## 4. Database schema (Supabase Postgres)

```sql
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
```

`avg_consult_s` update on every DONE: `avg = round(0.7*avg + 0.3*actual)` (rolling, per session; write back to a per-clinic learned prior nightly).

---

## 5. WhatsApp conversation design

**Golden rule:** buttons and lists first; the LLM only interprets free text into a fixed intent schema. Anything medical gets a fixed template reply ("please discuss with the doctor at your visit") — the LLM never generates medical content.

### 5.1 Booking flow (inside the free 24-h service window)

```
Patient: "hi" / anything / scans QR poster (wa.me deep link)
Bot: Welcome + consent line (first contact only)
     → LIST: [Aaj Subah (12 slots left) | Aaj Shaam (26) | Kal Subah]
Patient picks session
Bot: → BUTTONS: [Jaldi se jaldi] [Apna time batayein]
     free text "7 baje aunga" → LLM → priority_time = today 19:00
Bot: "Kiske liye?" → BUTTONS: [Khud] [Family member]  (name if family)
Bot: CONFIRMATION CARD (interactive msg):
     "✅ Token #14 · Dr. Sharma aapko ~7:20 baje dekhenge
      · 7:05 tak clinic pahunchein"
     [📍 Main aa gaya/gayi]  [❌ Cancel]
```

**Intents (LLM JSON schema):** `book | cancel | status | arrived | reschedule | greeting | medical_question | other` + entities `{session_pref, time_pref, profile_name, confidence}`. Confidence < 0.7 ⇒ re-ask with buttons, never guess.

**Always-on keywords (no LLM):** `status/kitna time` → live position + ETA · `cancel` → confirm → cancel · button taps map directly to events.

### 5.2 Template messages (business-initiated — submit to Meta as UTILITY, in `hi` and `en`)

| # | Name | Trigger | Hindi body (English mirror too) | Buttons |
|---|------|---------|--------------------------------|---------|
| 1 | `booking_confirmed` | booking outside 24-h window | नमस्ते {{1}} जी! अपॉइंटमेंट पक्का ✅ टोकन नं. {{2}} • डॉक्टर आपको लगभग {{3}} बजे देखेंगे • कृपया {{4}} बजे तक क्लिनिक पहुँचें। पहुँचने पर नीचे बटन दबाएँ। | 📍 मैं आ गया/गई · ❌ कैंसिल |
| 2 | `pre_arrival` | T−(buffer+15m) | रिमाइंडर: आपका टोकन {{1}} • अनुमानित समय {{2}} • कृपया {{3}} तक पहुँचें। पहुँचते ही 'मैं आ गया/गई' दबाएँ। | 📍 मैं आ गया/गई |
| 3 | `three_away` | 3 tokens ahead | आपसे पहले सिर्फ़ 3 मरीज़ हैं। अनुमानित समय {{1}}। अगर क्लिनिक नहीं पहुँचे हैं तो अभी निकलें 🙏 | 📍 मैं आ गया/गई |
| 4 | `you_are_next` | called | अब आपकी बारी है! कृपया रिसेप्शन पर आ जाएँ। टोकन {{1}} | — |
| 5 | `skipped_grace` | skipped | आपकी बारी आई पर आप क्लिनिक पर नहीं थे। {{1}} मिनट तक आपकी जगह रोकी गई है — पहुँचते ही बटन दबाएँ, आपको अगला नंबर मिलेगा। | 📍 मैं आ गया/गई |
| 6 | `eta_shift` | ETA moved >10 min | अपडेट: आपका नया अनुमानित समय {{1}} है (टोकन {{2}})। | — |
| 7 | `delay_broadcast` | doctor late | सूचना: डॉक्टर आज {{1}} मिनट देरी से आएँगे। आपका नया समय: {{2}}। असुविधा के लिए खेद 🙏 | — |
| 8 | `closed_broadcast` | clinic closed today | क्षमा करें, आज क्लिनिक बंद है ({{1}})। कल के लिए बुक करें? | 📅 कल बुक करें |
| 9 | `gap_offer` | gap detected | एक जगह खाली हुई! डॉक्टर आपको ~{{1}} बजे देख सकते हैं (पहले {{2}} था)। 5 मिनट में जवाब दें। | ✅ हाँ, पहले आऊँगा |
| 10 | `expired_rebook` | session close | आज आपकी अपॉइंटमेंट पूरी नहीं हो सकी। कल के लिए बुक करें? | 📅 कल बुक करें |
| 11 | `doctor_digest` | daily, to doctor | आज: {{1}} मरीज़ देखे • {{2}} नो-शो • औसत {{3}} मिनट • {{4}} WhatsApp बुकिंग • कल सुबह {{5}} बुक हो चुके | — |

**Consent line (appended to first-ever reply, DPDP-lite):** "ℹ️ बुकिंग के लिए हम आपका नाम व नंबर सुरक्षित रखते हैं। हटाने के लिए STOP लिखें।" `STOP` ⇒ cancel active tokens + delete patient rows + confirm.

### 5.3 Meta/WhatsApp realities (plan around these, they're the real lead times)

- **Start dev on day 1 with Meta's free test number** (5 whitelisted recipients — you + doctor + friends). Production needs: Meta Business verification (days→2 weeks), a phone number **not** currently on the WhatsApp app, permanent system-user token, webhook subscription to `messages`.
- Business-initiated messages outside the 24-h window **must** be approved templates → submit all 11 as UTILITY early; avoid marketing-sounding words to dodge rejection.
- Costs: user-initiated service conversations are free; utility messages are paise-level. Whole journey ≈ ₹1–3 per patient worst case vs ₹2k/month revenue — ignore for now, log `wa_messages` and check Meta's current India rate card before scale.
- Rate/quality: new numbers start at ~250 business-initiated conversations/day; scales with verification + quality rating. Fine for pilot.

---

## 6. Phase plan & timeline (≈4 weeks part-time)

| Phase | When | What ships | Definition of done |
|---|---|---|---|
| **P0 — Validate + unblock** | Week 0 (start today, parallel) | 3 doctor conversations, 1 design partner; Meta business verification + test number; repo scaffold + CLAUDE.md | Doctor said yes; you can send yourself a WhatsApp via API |
| **P1 — Schema** | W1 d1–2 | Migrations, seed script, config loader | `supabase db reset` clean; seeded demo clinic |
| **P2 — Queue engine** | W1 d3–7 | Pure engine + full test suite (the 16 scenarios) | `pytest` green; every conversation edge case is a passing test |
| **P3 — WhatsApp layer** | W2 d1–3 | Webhook, sender, template registry, idempotency | Echo bot works on test number; buttons round-trip |
| **P4 — Conversation + LLM** | W2 d4–7 | Booking/cancel/status/arrived flows, intent parser, guardrails | Full booking → arrived → done journey on your phone, in Hindi |
| **P5 — Jobs + notifications** | W3 d1–3 | Grace sweeper, pings, gap offers, broadcasts, digest | Simulated session fires every message at the right moment |
| **P6 — Clinic panel PWA** | W3 d4–7 | Live queue, NEXT, walk-in, session controls, settings, undo | Receptionist flow ≤2 taps per action on a cheap Android |
| **P7 — Deploy + pilot** | W4 | Droplet deploy, Vercel, Meta prod number, onboarding kit, QR poster | Design-partner clinic runs one full real session |
| **v1.1 backlog** | post-pilot | Realtime sync, TV waiting-room view, analytics digest page, strikes enforcement + token fee, missed-call→WhatsApp (Exotel), patient lookup, phone-OTP auth, offline cache | — |

**Critical path = Meta business verification + doctor yes. Both start today, both are outside your control — everything else is just typing.**

---

## 7. Claude Code prompts (P0 → P7)

How to use: run these **in order** inside Claude Code (desktop app or terminal), one phase per session. Prompt 0 writes a `CLAUDE.md` that carries the spec, so later prompts stay short and Claude Code always has context. After each phase: run the tests, commit, then start the next prompt. If Claude Code asks something a prompt doesn't answer, the answer is in `CLAUDE.md` or §3–5 of this doc — paste the relevant section in.

---

### Prompt 0 — Repo scaffold + CLAUDE.md (the context anchor)

````text
Create a new monorepo called `CLINIC APPOINTMENT` with this structure:

CLINIC APPOINTMENT/
  CLAUDE.md
  backend/          # FastAPI, Python 3.11
    app/
      main.py       # FastAPI app factory, /healthz
      config.py     # pydantic-settings, reads .env
    tests/
    pyproject.toml
    .env.example
  panel/            # Next.js 14 (app router), TypeScript strict, Tailwind — placeholder page only
  supabase/
    migrations/     # empty for now
  docs/

Then write CLAUDE.md with EXACTLY this content (it is the project constitution — every future session must obey it):

---
# ClinicQ — project constitution

## What this is
A WhatsApp-based virtual token queue for single-doctor Indian clinics. Patients book/track/check-in on WhatsApp; the clinic runs the queue from a mobile-first web panel. Multi-tenant by clinic_id from day one.

## Architecture (fixed)
- FastAPI backend (droplet) = webhook receiver + panel REST API + queue engine + APScheduler jobs.
- Supabase Postgres = single source of truth. NO Redis in v1. Panel polls REST every 4s.
- WhatsApp Cloud API for all patient interaction. Buttons/lists first; LLM parses free text only.
- THE LLM NEVER MUTATES STATE AND NEVER GENERATES MEDICAL CONTENT. It maps free text to intent JSON. All transitions are deterministic code in the queue engine.

## The three queue rules (never violate)
1. Queue is sorted by priority_time = max(requested_time, now); tie-break booked_at. "Come now" means priority_time = now. Cancel = delete; others shift up.
2. ETA = forward walk: clock = max(now, session.doctor_free_at); for each active entry in (priority_time, booked_at) order: eta = max(clock, priority_time); clock = eta + avg_consult.
3. Present beats absent, checked ONLY at call time: NEXT serves the first ARRIVED entry in priority order. Absent = instantly SKIPPED with grace_until = now + max(10min, 2 x avg_consult). Only skip when an ARRIVED replacement exists; if queue is otherwise empty, hold instead of skipping.

## Token lifecycle
BOOKED -> ARRIVED -> CALLED -> IN_CONSULT -> DONE; side exits CANCELLED, SKIPPED(grace), EXPIRED (session end or grace timeout => +1 strike).
token_number: sequential per session, assigned at booking, NEVER changes. Position/ETA are dynamic.
Two times per token: turn_time (=eta) and report_time = eta - clamp(2 x avg_consult, 10min, 30min).

## Gap pull-forward (after cancel/expiry, if doctor_free_at + 10min < next.priority_time)
1) auto-pull earliest ARRIVED patient; 2) else offer to next 2-3 remote patients (first YES sets their priority_time = now; offer expires 5 min; max 1 offer/patient/session); 3) else walk-ins fill it; 4) else genuine break.

## Anti-abuse (v1)
One ACTIVE token per (clinic, wa_number); max 3 family profiles per number; strikes counted on expiry, NOT enforced yet; no payments.

## Conventions
- Python 3.11, full type hints, pydantic v2 models, black+ruff, pytest (no network in tests — fake clock injected everywhere).
- All timestamps timestamptz UTC in DB; clinic tz = Asia/Kolkata for display.
- Every state change writes an `events` row (append-only) — analytics depends on it.
- All WhatsApp sends go through one send() gateway that logs to wa_messages; inbound deduped by wamid.
- Language: every patient-facing string exists in hi + en; clinic.language decides.
- Panel: Next.js 14 app router, TS strict, Tailwind, mobile-first, minimum touch target 56px, every mutating action has a 5s UNDO.

## Env vars
DATABASE_URL, SUPABASE_URL, SUPABASE_SERVICE_KEY, WA_TOKEN, WA_PHONE_NUMBER_ID, WA_VERIFY_TOKEN, WA_APP_SECRET, LLM_PROVIDER, LLM_API_KEY, JWT_SECRET, ENV
---

Also: git init, first commit, backend /healthz returns {"ok": true}, panel renders "ClinicQ panel". Provide run instructions in README.md.
````

---

### Prompt 1 — Database migrations + seed

````text
Read CLAUDE.md. Create Supabase SQL migrations in supabase/migrations/ implementing exactly this schema:

[PASTE SECTION 4 SCHEMA FROM THE BUILD DOC HERE — all 8 tables + indexes, unchanged]

Additions:
1. An updated_at trigger on queue_entries and sessions.
2. supabase/seed.sql: one demo clinic (slug 'demo', PIN 123456 bcrypt-hashed, language 'hi', Dr. Demo, fee 300), timetable Mon-Sat morning 09:00-13:00 cap 40 and evening 17:00-21:00 cap 40.
3. backend/app/db.py: asyncpg pool + small query helpers (no ORM; raw SQL with typed row mappers).
4. backend/app/models.py: pydantic models mirroring the tables + Status/SessionStatus enums.
5. A `make db-reset` target that resets and seeds a local/linked Supabase.

Definition of done: db reset runs clean; a pytest connects (via testcontainers-postgres or DATABASE_URL_TEST), inserts a clinic, reads it back typed.
````

---

### Prompt 2 — The queue engine (most important prompt — do not compress it)

````text
Read CLAUDE.md (the three rules are law). Build backend/app/engine/ as PURE, deterministic, fully-tested logic. No WhatsApp, no HTTP in this phase. Inject `now: datetime` into every function (FakeClock in tests). Every public function: loads state (row-locking the session with SELECT ... FOR UPDATE), applies one transition, recomputes ETAs, writes an events row, and returns EngineResult{changed_entries, notifications: list[NotificationIntent]} — notifications are DATA (type + entry_id + params), dispatched by a later phase, never sent from here.

Public API (engine/api.py):
- open_session(session_id) / pause / resume / close_session   # close => expire pending per rules
- book(clinic_id, session_id, patient_id, requested_time|None, source) -> entry
    - enforce: one ACTIVE token per (clinic, wa_number) across today's sessions
    - priority_time = max(requested_time or now, now); token_number = next per session
    - reject if session at cap / closed / would exceed end_at => return OverflowSuggestion(next sessions with space)
- cancel(entry_id) => status=cancelled + gap check
- mark_arrived(entry_id)        # from button tap OR panel; sets arrived_at
- next_patient(session_id):
    - finish current IN_CONSULT => DONE; avg_consult_s = round(0.7*avg + 0.3*actual); doctor_free_at = now
    - serve first ARRIVED by (priority_time, booked_at) => CALLED then IN_CONSULT immediately (v1)
    - every BOOKED entry ahead of the served one => SKIPPED, grace_until per rule 3, skip_count+1 — BUT apply the skip guard: if no ARRIVED entry exists anywhere, serve nothing and hold
- arrived_during_grace(entry_id) => re-insert at head (set priority_time = now minus 1s AND a next_up flag; served before all others at next NEXT)
- sweep(now) => grace expiries (SKIPPED past grace_until => EXPIRED, strike++, notification) — scheduler calls every 60s
- delay_session(session_id, minutes) => doctor_free_at += m => recompute + eta_shift notifications (only for shifts > 10 min)
- cancel_session_today(session_id) => all active => cancelled + closed_broadcast notifications
- emergency_insert(session_id, patient) => priority_time = now minus 1s
- gap_check(session_id) in CLAUDE.md order: pull ARRIVED -> create gap offers (gap_offered_at, expire via sweep) -> nothing
- accept_gap_offer(entry_id) => priority_time = now if offer still valid
- recompute_etas(session_id) — rule 2 exactly; also sets report_time; returns entries whose eta moved > 10 min

Tests (tests/test_engine.py, FakeClock — ALL must pass):
 t1  book 12:00 then 11:00 then 10:00 => order [10,11,12]
 t2  cancel middle => shift up + ETAs recompute + moved-up notification intents
 t3  requested past time => clamped to now (no leapfrogging waiters)
 t4  two "now" bookings => FIFO by booked_at
 t5  walk-in inserts at now, lands ahead of future-time bookings
 t6  ETA walk respects doctor_free_at and never lands before priority_time
 t7  NEXT with front absent + someone ARRIVED behind => absent SKIPPED instantly, arrived served
 t8  skipped arrives within grace => served at very next NEXT
 t9  grace expiry via sweep => EXPIRED + strike + notification
 t10 skip guard: front absent, nobody ARRIVED => nothing served, nobody skipped
 t11 cancel opens >=10min gap + an ARRIVED later-time patient exists => auto-pulled
 t12 gap offer accepted => priority_time=now, queue reorders; expired offer => no-op
 t13 booking beyond session end/cap => OverflowSuggestion with alternatives
 t14 second active token same wa_number => rejected (family profile shares the same 1-active cap)
 t15 emergency insert goes front, others' ETAs shift, notifications only where shift > 10 min
 t16 delay_session(30) => all ETAs +30, eta_shift notifications emitted
 t17 close_session => pending => EXPIRED + rebook notifications; avg_consult persisted

Definition of done: pytest green; engine has ZERO imports from whatsapp/llm/web modules.
````

---

### Prompt 3 — WhatsApp Cloud API layer

````text
Read CLAUDE.md. Build backend/app/wa/:

1. webhook.py — GET /webhook (hub.challenge verify with WA_VERIFY_TOKEN) and POST /webhook:
   - validate X-Hub-Signature-256 with WA_APP_SECRET
   - dedupe by wamid against wa_messages (insert-or-skip)
   - normalize inbound to InboundMessage{wa_number, kind: text|button_reply|list_reply, text, button_id, timestamp} and hand to a handler callback (wired in Prompt 4). ACK 200 fast; process in a background task.
2. sender.py — one async send() gateway over Graph API v20+:
   - send_text, send_buttons(max 3), send_list, send_template(name, lang, params, buttons)
   - 24-hour-window logic: is_window_open(wa_number) from last inbound in wa_messages; callers pass preferred free-form + fallback template name; gateway picks
   - retries with backoff on 5xx/429; logs every send to wa_messages
3. templates.py — registry of the 11 templates from the build doc section 5.2, hi + en bodies, param builders, button ids. Central place; nothing else hardcodes strings.
4. notify.py — NotificationDispatcher: consumes EngineResult.notifications and maps each NotificationIntent type to the right template/free-form via the gateway. This is the ONLY bridge from engine to WhatsApp.
5. CLI: `python -m app.wa.smoke +91XXXXXXXXXX` sends a test button message (for the Meta test number).

Tests: signature validation, wamid dedupe, window logic (mock clock), template param rendering hi/en. Mock the Graph API with respx — no network in tests.
````

---

### Prompt 4 — Conversation flow + LLM intent parser

````text
Read CLAUDE.md. Build backend/app/convo/:

1. flow.py — state machine keyed on conversations(wa_number, clinic_id), states: idle -> choosing_session -> choosing_time -> choosing_profile -> (booked), plus confirm_cancel. Rules:
   - Button/list replies drive transitions directly (ids: sess:<session_id>, time:asap, profile:self, arrived:<entry_id>, cancel:<entry_id>, gapyes:<entry_id>, rebook:tomorrow).
   - Free text => llm.parse() => intent JSON => same transition table. confidence < 0.7 => re-ask with buttons, never guess.
   - Keywords bypass everything: "status"/"kitna time"/Hindi equivalents => live position+ETA; "cancel"; "STOP" => DPDP delete flow (cancel active tokens, delete patient rows, confirm).
   - First-ever contact => append consent line.
   - Session list shows remaining capacity; only sessions within booking window with space.
   - On book: engine.book; on OverflowSuggestion render alternatives as a list message.
   - medical_question intent => fixed safe reply template. Never LLM-generated medical text.
2. llm.py — provider-agnostic (LLM_PROVIDER env: gemini-flash | claude-haiku), one function parse(text, context) -> Intent with strict JSON schema {intent: book|cancel|status|arrived|reschedule|greeting|medical_question|other, session_pref, time_pref (HH:MM|null), profile_name|null, confidence}. Must handle Hinglish + Devanagari ("kal subah 10 baje", "shaam ko aaunga"). Temperature 0. Any parse error => intent=other.
3. Wire webhook handler -> flow -> engine -> dispatcher. End-to-end path complete.

Tests: scripted conversations as fixtures (inbound in, expected sends out): happy booking hi + en, specific-time booking, status, cancel, arrived tap, family member, overflow, medical question, gibberish (low confidence => buttons re-ask), STOP flow.
Definition of done: on the Meta test number I can book -> get confirmation with Arrived button -> tap it -> see status change in DB.
````

---

### Prompt 5 — Schedulers + proactive notifications

````text
Read CLAUDE.md. Build backend/app/jobs/ on APScheduler (AsyncIOScheduler started in FastAPI lifespan):

1. every 60s sweep(): engine.sweep (grace + gap-offer expiries) + session auto-open (scheduled->open at start_at; stamp sessions from timetable daily at 00:05 IST for today+2) + auto-close at end_at (engine.close_session).
2. every 60s ping_scan() for open sessions:
   - pre_arrival at eta - (buffer + 15 min), once per entry
   - three_away when exactly 3 active entries ahead, once per entry
   - eta_shift only when |new - last_notified_eta| > 10 min (store last_notified_eta on the entry)
   (you_are_next fires from the dispatcher on CALLED — verify idempotent)
3. daily 21:45 IST doctor_digest per clinic computed from events: seen, no-shows, avg consult, WA bookings, tomorrow-morning count.
4. Idempotency columns (notified_pre_arrival_at etc.) — a job crash must never double-send.
5. Simulation harness: scripts/simulate_session.py runs a fake session with N scripted patients (dry-run printing sends, or real sends to the test number), time compressed 60:1. This is the demo + QA tool.

Tests: FakeClock-driven — assert each notification fires exactly once at the right minute across a scripted session that includes a delay, a cancel-gap, a skip + grace-expiry, and a close.
````

---

### Prompt 6 — Clinic panel PWA

````text
Read CLAUDE.md. Build the panel/ Next.js app. Audience: a 45-year-old receptionist on a cheap Android, one thumb, interrupted constantly. One screen does 90% of the job. Design: calm clinical palette (soft near-white background, one deep teal primary, amber/green/gray status chips), Noto Sans (Devanagari support), 56px+ touch targets, Hindi-first labels with English fallback, generous spacing — sober utility, not a dashboard showpiece.

Backend first: backend/app/api/panel.py — JWT auth (POST /login {slug, pin} => token), then:
GET /session/today · GET /queue?session_id · POST /next · POST /walkin {name, phone?} · POST /entries/{id}/arrived|cancel|call-now · POST /session/delay {minutes} · POST /session/pause|resume|close · POST /session/cancel-today · POST /emergency {name, phone?} · GET/PUT /settings. Every mutating route returns the fresh queue snapshot. POST /undo replays the inverse of the last action (store last-action per clinic, 5s validity).

Pages:
1. /login — slug + PIN, huge inputs.
2. / (Live Queue):
   - session banner (name, timing, status, avg consult, served/waiting counts)
   - NOW SERVING card: token #, name, live consult timer
   - giant fixed-bottom NEXT button (full-width, 72px tall)
   - queue list sorted by priority_time: token, name, status chip (booked amber / arrived green / grace with countdown / in-consult blue), target time, ETA; row tap => action sheet (Mark arrived · Cancel · Call now)
   - [+ Walk-in] => modal name + optional phone, 2 taps total
   - after EVERY mutation: 5s UNDO snackbar
   - poll GET /queue every 4s, optimistic updates, subtle sound + badge on new booking/arrival
3. Session controls bottom-sheet: Start/End · Late +15/+30/+45 · Pause · Emergency insert · Close today (single confirm each).
4. /settings — clinic profile, weekly timetable editor, token caps, toggles (gap offers, language), change PIN.
5. PWA: manifest + icons, installable; offline shows cached last queue read-only with a "reconnecting" bar.

Definition of done: on a 360px viewport, the receptionist completes walk-in, mark-arrived, NEXT, and undo — each in <=2 taps; keyboard needed only for walk-in name.
````

---

### Prompt 7 — Deploy + pilot kit

````text
Read CLAUDE.md. Ship it:

1. backend: Dockerfile + docker-compose.yml (uvicorn, restart always) or a systemd unit — target an Ubuntu 24 DigitalOcean droplet. Cloudflare Tunnel config exposing https://<subdomain> -> :8000 (the webhook needs a stable TLS URL). Healthcheck + log rotation.
2. panel: vercel.json + env docs; API base via env var.
3. docs/DEPLOY.md — exact runbook:
   - Meta: business verification, create app, add WhatsApp product, register production number (must NOT be a number active on the WhatsApp app), permanent system-user token, webhook subscribe to `messages`, submit the 11 templates (hi + en, UTILITY category)
   - Supabase: project, run migrations, service key
   - .env matrix dev vs prod; end-to-end smoke checklist
4. docs/ONBOARDING.md — the done-for-you clinic setup script (60 min): collect timetable/fee/language -> seed clinic row + PIN -> print & laminate QR poster -> 15-min receptionist training (NEXT, walk-in, arrived, undo — nothing else) -> doctor's phone gets digest + panel bookmark -> dry run with 3 staff phones -> go live next morning.
5. scripts/qr_poster.py — A4 poster PDF: clinic name, "WhatsApp par number lagaiye" headline, big QR to wa.me/<number>?text=Namaste, 3-step how-to in Hindi, small ClinicQ footer.
6. Minimal ops: /metrics endpoint (bookings today, sends, errors) + uptime monitor note.
````

---

## 8. Pilot & GTM playbook

**Week 0 — the doctor conversation (before writing any code).** Script: "Doctor sahab, do sawaal — (1) abhi appointment kaise lete hain? (2) pichhle hafte kitne mareez bina bataye nahi aaye?" Let the pain surface, then a 90-second demo on *your* phone: book on WhatsApp → confirmation with token + time → tap "मैं आ गया" → panel updates live. Close: "Main 2 mahine free laga deta hoon, setup bhi main karunga. Aapke staff ko sirf ek button dabana hai — NEXT."

**Design partner deal:** 2 months free, you do 100% of setup, in exchange for (a) honest weekly feedback, (b) permission to publish their numbers as a case study, (c) two referral intros if it works.

**The three numbers to instrument from day 1** — they are your entire future sales deck:
1. No-show rate, before vs after.
2. After-hours bookings captured (revenue the phone line was losing).
3. Average waiting-room time (arrived → called).

Target case study: *"No-shows 24% → 9% in 6 weeks; 31 after-hours bookings/month recovered ≈ ₹15–25k."*

**Clinics 2–10:** referrals from clinic 1 (doctors cluster — same building, same pharma reps, IMA meets) plus walk-ins with the laminated poster and the live demo. Pricing after pilots: ₹1,999/month, no setup fee for the first 10, month-to-month, cancel anytime — remove every excuse to say no.

**Patient-side distribution is automatic:** the QR poster at reception + the receptionist telling callers "WhatsApp kar dijiye" migrates the patient base for you within weeks.

---

## 9. Metrics, risks, costs

**Instrument (the events table already captures all of it):** bookings by source (WA / walk-in / panel) · no-show & expiry rate · **ETA error** = |eta_at_booking − called_at| (your accuracy KPI — drive it under 15 min) · avg consult per doctor · gap-offer acceptance rate · daily active patients per clinic.

**Top risks → mitigations:**

| Risk | Mitigation |
|---|---|
| Meta verification / template approval delays | Start P0 today; develop on the test number; submit all 11 templates in week 1 |
| Receptionist doesn't tap NEXT (kills the live clock) | 15-min training on exactly 4 actions; undo everywhere; doctor's-own-WhatsApp "next" fallback in v1.1; the digest makes value visible to the boss |
| ETA wildly wrong in week 1 (cold-start average) | Seed 7 min, rolling update from consult 1; copy always says "lagbhag / around" |
| Older patients without smartphones | Walk-in flow is first-class; receptionist can mark arrived for anyone |
| Flaky clinic internet | Panel works on phone data; offline read-cache in v1.1 |
| DPDP / health data | v1 stores only name + number + timestamps (zero medical data), consent line + STOP deletion flow. Revisit properly (ABDM/ABHA, retention, encryption) before any Phase-2 records work |
| CMS vendors bundle a lookalike | Moat = a segment nobody serves in person + per-clinic learned timing data + the Phase-2/3 roadmap (records-as-byproduct → doctor's memory assistant) |

**Running costs (pilot):** Supabase free tier + your existing droplet + Vercel free + LLM ≈ ₹0.02–0.05/booking + WhatsApp utility messages ≈ ₹1–3 per patient journey. Effectively zero against ₹1,999/clinic/month.

---

## 10. What to do TODAY (in order)

1. Message the doctor you know best → book the Week-0 conversation.
2. Start Meta Business verification + create the app + get the **test number** sending (longest external lead time — days to two weeks).
3. Run **Prompt 0** in Claude Code.
4. Don't buy anything, name it later, and don't touch the panel until the engine's 17 tests are green.

*Roadmap after v1 proves out (from our strategy discussion): Phase 2 = records-as-byproduct (prescription photo/voice → visit history, ABDM-aware), Phase 3 = doctor's memory assistant (retrieval + summaries, never diagnosis), then specialty-deep journeys. The queue is the wedge; the timing data and the patient graph are the moat.*
