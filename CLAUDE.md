# CLAUDE.md — ClinicQ project constitution

Read this file at the start of every session. It is the source of truth for architecture, queue logic, and conventions. If a request conflicts with anything here, flag the conflict before writing code.

## What this project is

A WhatsApp-based **virtual token queue** for single-doctor Indian clinics. Patients book, track live position/ETA, and check in — entirely on WhatsApp (no app). The clinic runs the queue from a mobile-first web panel with one big **NEXT** button. Multi-tenant by `clinic_id` from day one. v1 goal: one pilot clinic running real sessions.

The product's one job: **no patient waits blind, no doctor sits idle, no enquiry is lost.**

## Repo layout

```
Clinic-Automation/          # repo root (NOT "clinicq/")
  CLAUDE.md
  backend/            # FastAPI, Python 3.11
    app/
      main.py         # app factory, /healthz, lifespan starts scheduler
      config.py       # pydantic-settings (.env)
      db.py           # asyncpg pool + typed query helpers (no ORM)
      models.py       # pydantic models + enums
      engine/         # PURE queue logic (no wa/llm/web imports — enforced)
      wa/             # webhook, sender gateway, templates registry, dispatcher
      convo/          # conversation state machine + LLM intent parser
      jobs/           # APScheduler: sweep, ping_scan, digest, session stamping
      api/panel.py    # JWT-auth REST for the clinic panel
    tests/
  panel/              # Next.js 14 app router, TS strict, Tailwind, PWA
  supabase/migrations # full DDL lives here (source of truth for schema)
  scripts/            # create_clinic, dev_reset_session, migrate, qr_poster,
                      # reset_avg_consult, seed_demo_queue, simulate_session,
                      # wa_preflight, guard_local_db.sh, run_tests.sh
  docs/               # DEPLOY.md, ONBOARDING.md
```

## Commands

On Git Bash (Windows), invoke Python tools as `python -m <tool>` — bare `uvicorn` / `pytest` may resolve to a different interpreter than the project venv.

- Backend dev: `cd backend && python -m uvicorn app.main:app --reload` (serves on :8000)
- **Tests: `make test`** — must be green before every commit. See below; do not use bare `pytest`.
- Lint/format: `ruff check . && black .`
- DB: `make db-reset` (reset + seed a demo clinic, slug `demo`, PIN `123456`). Guarded: refuses to run unless `DATABASE_URL` is localhost. The live pilot clinic is `clinicq-test`, **not** `demo` — `demo` exists only in local seed data, and it must stay that way.
- Panel dev: `cd panel && npm run dev`
- WhatsApp smoke test: `python -m app.wa.smoke +91XXXXXXXXXX`
- Session simulator (demo/QA): `python scripts/simulate_session.py --dry-run`

### Why `make test` and not `pytest`

Bare `pytest` reports **130 passed, 16 skipped** and prints a green bar with exit code 0. Those 16 skips are not marginal: they are every `undo` test, the panel route tests, and the Postgres parity and concurrency tests — most of what actually touches the database. A green bar that omits them is a false green, and it is exactly what a deploy decision gets made on.

`make test` starts the disposable Postgres (`clinicq_pg`), sets `DATABASE_URL_TEST`, and runs the suite with `REQUIRE_PG_TESTS=1`. Expected result: **146 passed, 0 skipped.** It also runs `panel/sw.test.mjs`.

`REQUIRE_PG_TESTS=1` turns "skipped because there is no database" into a hard failure (exit 4, `backend/tests/conftest.py`). Set it in CI and before any deploy.

## Architecture (fixed — do not re-litigate)

- FastAPI backend on a DigitalOcean droplet behind Cloudflare Tunnel = webhook receiver + panel REST API + queue engine + APScheduler jobs. One process.
- Supabase Postgres = single source of truth. **No Redis in v1.** Queue reads are `ORDER BY priority_time, booked_at` with `SELECT ... FOR UPDATE` row-locking on the session for mutations.
- Panel **polls** `GET /queue` every 4s + optimistic UI. No Realtime/websockets in v1.
- WhatsApp Cloud API for all patient interaction. **Buttons/lists first**; LLM parses free text only.
- Panel auth: clinic `slug` + 6-digit PIN → JWT. (Phone OTP is v1.1.)

## The three queue rules (LAW — never violate)

1. **Sort by `priority_time`, not booking order.**
   ```
   floor          = max(now, session.start_at)
   priority_time  = floor                         # "come now / next available"
   priority_time  = max(requested_time, floor)    # a specific requested time
   ```
   Two separate jobs in that one `max`. `now` blocks claiming a past time to leapfrog people already waiting. **`session.start_at` blocks booking into a session that has not opened — or has already ended.** Omitting the session floor is what once booked a patient into a dead session; it is part of the rule, not a patch on top of it. Tie-break: `booked_at` (FIFO). Cancel = row leaves the ordering; everyone behind shifts up.

   When the clamp moves a patient's requested time by more than the notice threshold, the flow tells them so in one plain sentence (`adjust_reason`). Applying it silently is what makes someone who asked for 11:30 and got 5:00 PM believe the system is broken.

2. **ETA = forward walk from the doctor's live clock.**
   ```
   clock = max(now, session.doctor_free_at)      # doctor_free_at set on every NEXT
   for e in active entries ordered by (priority_time, booked_at):
       e.eta = max(clock, e.priority_time)        # never before the target time
       clock = e.eta + session.avg_consult
   ```
   Delays, cancels, walk-ins, emergency inserts are all just re-walks. Notify a patient only when their ETA moves > 10 min.

3. **Present beats absent — checked only at call time.** NEXT serves the **first ARRIVED entry in priority order**. An absent entry is passed over instantly (status → SKIPPED with grace); the doctor never waits. **Skip guard:** only skip when an ARRIVED replacement exists; if nobody has arrived, hold instead of skipping.

## Token lifecycle & timers

`BOOKED → ARRIVED → CALLED → IN_CONSULT → DONE`; side exits `CANCELLED`, `SKIPPED` (grace), `EXPIRED`.

- `token_number`: sequential per session, assigned at booking, **never changes** (it is the patient's identity at the desk). Position and ETA are dynamic and communicated separately.
- Two times per token: `turn_time` (= eta) and `report_time = eta − clamp(2 × avg_consult, 10 min, 30 min)`.
- Three distinct clocks — never merge them:
  | Event | Timer | Value |
  |---|---|---|
  | Passed over when absent | instant | 0 — evaluated at NEXT, no timer runs |
  | Grace after skip | short | `G = max(10 min, 2 × avg_consult)`; arrive within G ⇒ served at the very next NEXT (head of line); one extension max |
  | Hard expiry | session end | any BOOKED/SKIPPED still absent ⇒ EXPIRED, `strikes += 1`, rebook nudge |
- On every DONE: `doctor_free_at = now`, and the rolling average learns from the consult — **but only if the duration is sane**:
  ```
  if 30s <= actual <= 2700s:   avg_consult_s = round(0.7 × avg + 0.3 × actual)
  else:                        avg_consult_s unchanged  (log consult_out_of_range)
  ```
  The bounds are part of the rule. A forgotten NEXT tap once produced a 26-hour "consult" that permanently poisoned the average and corrupted every ETA after it. Below 30s is a mis-tap, not a consult; above 45 min assume the doctor forgot to tap. The patient is still marked DONE and still counted in `consults_done` — only the average update is skipped.

## Gap pull-forward (doctor never idles)

After any cancel/expiry, if `doctor_free_at + 10 min < next.priority_time`, in this order:
1. Auto-pull the earliest **ARRIVED** patient regardless of their target time (they only benefit). **Not subject to the horizon below** — someone already in the waiting room can only gain from being called sooner.
2. Else offer the slot to the next 2–3 remote patients in queue order — first YES sets their `priority_time = now`; offer expires in `gap_offer_expiry_min` (default 5); max one offer per patient per session.
3. Else a walk-in (`priority_time = now`) naturally fills the hole.
4. Else it is a genuine break. Do nothing.

**Two guards on the remote offer (step 2). Both are part of the rule.**

- **Pull-forward horizon.** Never offer a remote patient a slot more than `gap_pull_forward_max_min` (default 30) before their own time. Measured against **`priority_time`, not `eta`** — the requested time is what the patient planned their day around; the eta is a system artifact that drifts as the queue moves.
- **The doctor must actually be working**: at least one completed consult, or someone currently in consult. Session-start-to-first-booking is never a gap.

Why: an evening session opened 17:00, two patients booked ~19:00, the first cancelled at 17:30, and the second was offered **17:30** — 90 minutes before the time they chose. `17:30` was simply `now`. That hole was not created by the cancellation; it was the empty stretch before anyone had booked, and the cancel merely triggered re-evaluation of it. The rule exists for a doctor finishing early *between patients*, which is not a problem a patient can solve by leaving home earlier.

**`gap_offers: false` disables step 2 only.** The auto-pull in step 1 keeps running: the setting is about unsolicited patient messaging, and pulling forward someone already in the waiting room sends no message at all. Coupling them would let a messaging preference silently degrade queue throughput, with nothing on screen connecting cause to effect.

## Anti-abuse (v1)

One **ACTIVE** token per `(clinic, wa_number)` across today's sessions. Up to 3 named family profiles per number (they share the same one-active cap). Strikes are **counted** on expiry but **not enforced** in v1. No payments anywhere.

## Policy defaults (per-clinic overrides live in `clinics.settings` jsonb)

grace `max(10m, 2×avg)` · gap threshold 10 min · `gap_offer_expiry_min` 5 · `gap_pull_forward_max_min` 30 · `gap_offers` true · ETA-ping threshold 10 min · booking window 2 days · stop issuing tokens 30 min before close or at cap · family profiles ≤ 3 · default `avg_consult_s` seed 420.

Engine-visible policy is read through `repo.get_gap_policy(clinic_id)` into a `GapPolicy` — never from config inside `app/engine/`, so purity holds and every value is injectable in tests.

## Data model (summary — full DDL in supabase/migrations/)

| Table | Purpose / key columns |
|---|---|
| `clinics` | slug, pin_hash, language (hi/en), wa_phone_number_id, settings jsonb |
| `timetable` | weekly template: weekday, name, start/end, token_cap |
| `sessions` | one queue per (clinic, date, name); status, doctor_free_at, avg_consult_s, token_cap |
| `patients` | (clinic_id, wa_number, profile_name) unique; strikes |
| `queue_entries` | token_number, **priority_time**, status, eta, report_time, arrived_at, grace_until, source; unique (session_id, token_number); index (session_id, priority_time, booked_at) |
| `events` | append-only audit log of every state change — analytics + ETA learning depend on it |
| `wa_messages` | in/out log; inbound dedupe by `wamid` |
| `conversations` | per (wa_number, clinic_id) flow state + context jsonb |

Entry status enum: `booked|arrived|called|in_consult|done|skipped|expired|cancelled`. Session status: `scheduled|open|paused|closed|cancelled`. All timestamps `timestamptz` UTC; display in `Asia/Kolkata`.

### `timetable` vs `sessions` — two layers, not one

This trips people up, so it is written down explicitly.

- **`timetable` is a weekly template.** One row per (clinic, weekday, name): "Mon morning 09:00–13:00, cap 40". It holds no dates and no queue.
- **`sessions` are dated instances stamped from that template.** The `stamp_daily` job (00:05 IST) materializes sessions for **today + 2 days**, `insert ... on conflict (clinic_id, date, name) do nothing`.
- **Stamping is create-only.** The `do nothing` is the whole point: a session that already exists is never rewritten, so a live queue cannot be mutated out from under the receptionist by a background job.

The consequence that surprises people: **editing the timetable does not change an already-stamped session.** Change Monday's hours in Settings and today's — and the next two days' — sessions keep the hours they were stamped with. The edit takes effect from the first day not yet stamped. That is intended, not a bug: sessions carry live queue state, and retroactively moving `start_at` would move every `priority_time` floor (queue rule 1) under patients who are already booked. To change today, edit the session, not the template.

## WhatsApp layer

- All sends go through **one** `send()` gateway (`wa/sender.py`) that logs to `wa_messages` and handles retries. Nothing sends directly.
- **24-hour window:** free-form messages only within 24h of the patient's last inbound; otherwise use an approved template. `is_window_open()` decides; callers pass a free-form preference + template fallback.
- **Template registry (`wa/templates.py`)** — the only place patient-facing strings live, each in `hi` + `en`, UTILITY category: `booking_confirmed`, `pre_arrival`, `three_away`, `you_are_next`, `skipped_grace`, `eta_shift`, `delay_broadcast`, `closed_broadcast`, `gap_offer`, `expired_rebook`, `doctor_digest`.
- **Button/list ID conventions:** `sess:<session_id>` · `time:asap` · `profile:self` / `profile:<name>` · `arrived:<entry_id>` · `cancel:<entry_id>` · `gapyes:<entry_id>` · `rebook:tomorrow`.
- **NotificationIntent:** the engine returns notifications as *data* (`type`, `entry_id`, params). `wa/notify.py` (dispatcher) is the ONLY bridge from engine to WhatsApp.
- First-ever contact appends the consent line; `STOP` triggers the DPDP delete flow (cancel active tokens, delete patient rows, confirm).

## Conversation flow

State machine in `convo/flow.py` keyed on `conversations`: `idle → choosing_session → choosing_time → choosing_profile → (booked)`, plus `confirm_cancel`. Button replies drive transitions directly. Keywords bypass everything: `status` / "kitna time" ⇒ live position+ETA; `cancel`; `STOP`. Overflow (cap/end-of-session) ⇒ offer alternative sessions as a list. Booking beyond capacity is never silently accepted.

## LLM boundaries (hard rules)

- The LLM **never mutates state and never generates medical content.** It maps free text → `{intent, session_pref, time_pref, profile_name, confidence}` (strict JSON schema, temperature 0). Intents: `book|cancel|status|arrived|reschedule|greeting|medical_question|other`.
- Must handle Hinglish + Devanagari ("kal subah 10 baje", "शाम को आऊँगा").
- `confidence < 0.7` ⇒ re-ask with buttons. Never guess.
- `medical_question` ⇒ fixed safe template ("please discuss with the doctor at your visit"). Parse errors ⇒ `other`.
- Provider-agnostic via `LLM_PROVIDER` (`gemini-flash` | `claude-haiku`).

## Panel principles

Audience: a 45-year-old receptionist on a cheap Android, one thumb, interrupted constantly. One screen does 90% of the job. Touch targets ≥ 56px; NEXT is a fixed-bottom 72px full-width button. Every mutating action shows a **5s UNDO** snackbar (backend `POST /undo` replays the inverse of the last action). Hindi-first labels, English fallback. Walk-in add = 2 taps. Calm clinical look: soft near-white background, one deep teal primary, amber/green/gray status chips, Noto Sans (Devanagari). Poll every 4s, optimistic updates, subtle sound on new booking/arrival. Installable PWA; offline = cached read-only queue + "reconnecting" bar.

**Panel copy lives only in `panel/lib/i18n.ts`**, every entry carrying both `hi` and `en` — the same rule as `wa/templates.py`, extended to staff-facing strings. No user-visible string is hardcoded in a component. Locale is explicit: it defaults to `clinic.language`, a manual override in the `⋯` menu persists to `localStorage` and wins, and `<html lang>` tracks it. **Browser auto-translate is disabled** (`translate="no"`, `class="notranslate"`, `<meta name="google" content="notranslate">`) because machine translation rewrote state labels into imperatives next to destructive controls. Layout is verified at **360px width in both locales** — English strings run wider than Devanagari, so anything sized to fit Hindi must be re-checked in English.

**Error messages are classified by HTTP status, never by a catch-all `catch`.** A credentials error ("wrong code or PIN") may be shown **only on a 401**. A 4xx/5xx is a server error and shows its status; a `fetch` rejection (network, DNS, CORS) is "cannot reach server". These are different facts and the person reading the screen cannot tell them apart unless the code does. The panel also never renders the API's own bilingual `message` prose — it maps the machine-readable `reason` to its own dictionary key so the screen stays in one language.

**No relative countdown on a session that is not today.** ETAs and grace timers show absolute clock times on a future-dated session; a 10-hour countdown beside a 9:00 am target reads as a bug.

**Controls do not appear and disappear with the data.** The आज/कल day tabs render unconditionally — zero bookings and no-session-that-day each get their own empty state rather than a vanished control.

## Conventions & testing

- Python 3.11, full type hints, pydantic v2, black + ruff, raw SQL via asyncpg (no ORM).
- **Engine purity:** `app/engine/` imports nothing from `wa/`, `convo/`, `llm`, or web modules. Enforce with a test.
- Every state change writes an `events` row. No exceptions — analytics and the doctor digest are built on it.
- **Every function that touches time takes an injected `now: datetime`.** Tests use a FakeClock. No network in tests (mock Graph API with respx); LLM mocked.
- Notification sends are idempotent (per-entry `notified_*_at` columns). A crashed job must never double-send.
- Mutations row-lock the session; token_number assignment is race-safe.
- Migrations are additive; ask before any schema change.
- TS strict mode in panel; no `any`.

## Env vars

`DATABASE_URL, SUPABASE_URL, SUPABASE_SERVICE_KEY, WA_TOKEN, WA_PHONE_NUMBER_ID, WA_VERIFY_TOKEN, WA_APP_SECRET, LLM_PROVIDER, LLM_API_KEY, JWT_SECRET, PANEL_ORIGINS, ENV`

`PANEL_ORIGINS` is the CORS allow-list for the panel, and it has two sharp edges:

- **It is a JSON array, not a comma-separated string.** It is typed `list[str]`, so pydantic-settings json-decodes it; `PANEL_ORIGINS=https://a,https://b` raises `SettingsError` at import time and the app never starts.
  ```
  PANEL_ORIGINS=["https://app.clinicq.kpriyam.me","http://localhost:3000"]
  ```
- **A missing origin fails in the browser, before the request is sent.** There is no server log, no status code, nothing — which reads as "the PIN stopped working" unless the panel classifies its errors (see Panel principles). After moving the panel to a new domain, verify with a preflight rather than assuming: `curl -i -X OPTIONS <api>/panel/login -H 'Origin: <panel origin>' -H 'Access-Control-Request-Method: POST'`.

## v1 scope guard — do NOT build (even if it seems helpful)

Billing · pharmacy/inventory · prescriptions or any EMR/medical data storage · payments/token fees · strikes *enforcement* · multi-doctor UI (schema stays ready) · voice calls / missed-call telephony · Redis · Realtime/websockets · native apps · TV waiting-room view · analytics dashboard pages. These live in the v1.1+ backlog; add only when explicitly asked.

## Working agreements for every session

1. Run the relevant tests before claiming a task done; **`make test` green (146 passed, 0 skipped) before commit.** Bare `pytest` is a false green — see Commands.
2. If a requested change would violate the three queue rules, the LLM boundaries, or the scope guard — say so and propose the compliant alternative instead of silently complying.
3. Prefer small, reviewable commits per phase (P0–P7 in the build plan).
4. Patient-facing copy: never hardcode strings outside `wa/templates.py`; always add both `hi` and `en`.
5. When uncertain about product behavior, the answer is in this file or `docs/clinicq_build_plan.md` §3–5 — check before asking.
