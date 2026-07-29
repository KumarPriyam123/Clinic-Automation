# ClinicQ — Deploy runbook

Production topology: **backend** on an Ubuntu 24 DigitalOcean droplet (behind a
Cloudflare Tunnel), **panel** on Vercel, **Postgres** on Supabase. One backend
process = webhook receiver + panel API + queue engine + APScheduler jobs.

> The dev box has **no Supabase CLI and no `make`** — use `scripts/migrate.py`
> and plain `docker compose` everywhere below.

---

## ⚠️ Scheduler single-instance hazard (read first)

APScheduler runs **in-process**. If the backend ever runs with **`uvicorn --workers >1`**
or is scaled to more than one replica, **every job double-fires** — duplicate
sweeps, pings, and **duplicate WhatsApp messages to real patients**.

Guards in place:
- `Dockerfile` CMD pins `--workers 1`; `docker-compose.yml` runs a single replica.
- `RUN_SCHEDULER` (env, default `true`) must be `true` in **exactly one** process.
  Any extra web process must set `RUN_SCHEDULER=false`.
- On startup the process logs one line: `scheduler ACTIVE ...` or
  `scheduler DISABLED ...`. Confirm you see exactly one `ACTIVE`.

Never remove these guards.

---

## Part A — Supabase (Postgres)

1. Create a Supabase project. Note two DSNs from **Project settings → Database**:
   - **Direct** (`db.<ref>.supabase.co:5432`) — for migrations.
   - **Pooler / transaction mode** (`...pooler.supabase.com:6543`) — for the app.
2. Connection specifics (already handled in `app/db.py`, do not hardcode):
   - App uses the **pooler** DSN for the long-lived asyncpg pool.
   - pgBouncer transaction mode has **no prepared statements** ⇒ asyncpg pool is
     opened with `statement_cache_size=0` (auto when the DSN is a pooler; force
     with `DB_STATEMENT_CACHE_SIZE=0`).
   - **SSL required** for Supabase ⇒ `ssl='require'` (auto for `*.supabase.co`;
     force with `DB_SSL=true`).
3. Apply schema + create the clinic (run from the **direct** DSN):
   ```bash
   DATABASE_URL="postgresql://postgres:<pw>@db.<ref>.supabase.co:5432/postgres" \
     python scripts/migrate.py            # applies migrations idempotently
   # real clinic (not the demo seed):
   DATABASE_URL="...:5432/postgres" python scripts/create_clinic.py \
     --slug <slug> --name "<Clinic>" --doctor "Dr. <X>" --pin <6 digits> \
     --language hi --fee <inr>
   ```
   `migrate.py` tracks applied files in `schema_migrations`; re-runs are no-ops.

---

## Part B — Meta / WhatsApp Cloud API

Do this once; the **live round-trip smoke** at the end is the real test.

1. **Business verification** on Meta Business Manager (can take a day — start early).
2. Create a **Meta app** → add the **WhatsApp** product.
3. **Register the production number.** It must **not** be a number currently
   active on the consumer WhatsApp app — deregister it there first, or use a fresh number.
4. **Permanent token:** create a **System User** (Business settings → Users →
   System users) with the WhatsApp permissions and generate a **permanent token**.
   Do **not** ship the 24-hour temporary token. Put it in `WA_TOKEN`.
5. **Webhook:** set callback URL `https://<subdomain>/webhook` and the verify
   token = your `WA_VERIFY_TOKEN`. Meta calls `GET /webhook` to verify.
6. **Subscribe** the app to the **`messages`** field.
7. **Templates:** submit all **11** in **hi + en**, category **UTILITY**:
   `booking_confirmed, pre_arrival, three_away, you_are_next, skipped_grace,
   eta_shift, delay_broadcast, closed_broadcast, gap_offer, expired_rebook,
   doctor_digest`. These are transactional — keep copy factual; marketing-sounding
   wording gets rejected. Param counts must match `app/wa/templates.py`.

---

## Part C — Droplet (backend + tunnel)

1. Ubuntu 24, install Docker + compose plugin. Clone the repo; `cd backend`.
2. `cp .env.example .env` and fill it (see ENV MATRIX below). `DATABASE_URL` =
   the **pooler** DSN. `.env` is gitignored — never commit it.
3. **Cloudflare Tunnel:** in the Cloudflare dashboard (Zero Trust → Networks →
   Tunnels) create a **named tunnel**, add a public hostname
   `https://<subdomain>.<domain>` → service `http://backend:8000`. Copy the
   tunnel **token** into `.env` as `TUNNEL_TOKEN`.
4. Bring it up:
   ```bash
   docker compose up -d --build
   docker compose logs -f backend    # expect exactly one "scheduler ACTIVE"
   ```
5. Verify:
   ```bash
   curl -fsS https://<subdomain>/healthz     # {"ok":true}
   curl -fsS https://<subdomain>/metrics     # bookings/sends/tick/pool
   ```
   Point an **uptime monitor at `/healthz`**. Watch `/metrics.scheduler_last_tick`
   advance every ~60s (proof the scheduler is alive).

**Timezone:** container runs `TZ=UTC`. The scheduler uses explicit IST trigger
objects, so `stamp_sessions` fires **00:05 IST** and `doctor_digest` **21:45 IST**
regardless of host TZ (pinned by `tests/test_scheduler_triggers.py`). The startup
log prints the next fire times in IST — eyeball them once.

**Logs:** JSON-file driver with rotation (10MB × 5). Request logging never emits
full phone numbers (masked to last 4) or the WA token (redaction filter in `app/obs.py`).

---

## Part D — Panel (Vercel)

1. Import the repo in Vercel; set **Root Directory = `panel`** (framework
   auto-detects Next.js; `vercel.json` is present).
2. Env var: `NEXT_PUBLIC_API_URL = https://<subdomain>` (the tunnel URL, no
   trailing slash).
3. Add the Vercel domain to the backend **`PANEL_ORIGINS`** (CORS) in `.env`, e.g.
   `PANEL_ORIGINS=["https://clinicq-panel.vercel.app"]`, and `docker compose up -d`.
4. PWA: Vercel serves over HTTPS (required for service workers). `sw.js` is at the
   origin root so its scope is `/`; `vercel.json` sets `Service-Worker-Allowed: /`
   and the manifest content-type. Confirm "Install app" appears and the installed
   PWA opens standalone.

---

## ENV MATRIX (dev vs prod)

| Var | dev | prod |
|---|---|---|
| `DATABASE_URL` | local Postgres (`:5432/clinicq`) | **pooler** DSN (`...pooler.supabase.com:6543`) |
| `DB_STATEMENT_CACHE_SIZE` | unset | unset (auto 0 on pooler) or `0` |
| `DB_SSL` | unset (false) | unset (auto true) or `true` |
| `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` | blank | from project settings |
| `WA_TOKEN` | blank / sandbox | **permanent** system-user token |
| `WA_PHONE_NUMBER_ID` | test number id | production number id |
| `WA_VERIFY_TOKEN` | any | strong random; matches Meta |
| `WA_APP_SECRET` | blank (dev bypass) | Meta app secret (enables signature check) |
| `LLM_PROVIDER` / `LLM_API_KEY` | gemini-flash / dev key | chosen provider / prod key |
| `JWT_SECRET` | `dev-secret-change-me` | long random string |
| `ENV` | `dev` | `prod` |
| `RUN_SCHEDULER` | `true` | `true` (exactly one process) |
| `PANEL_ORIGINS` | localhost:3000 | Vercel domain(s) |
| `TUNNEL_TOKEN` | — | Cloudflare named-tunnel token |

**Secret hygiene:** `.env` and tunnel credentials are gitignored (`.gitignore`
covers `.env` and `.env*.local`). Rotate `WA_TOKEN` by generating a new
system-user token in Meta, updating `.env`, and `docker compose up -d` (no code
change). Do the same for `JWT_SECRET` if leaked (invalidates panel sessions).

---

## SMOKE CHECKLIST (run in this exact order)

**1. LIVE WHATSAPP ROUND-TRIP — the last unproven seam.** From a real phone,
message the production number.
- `docker compose logs -f backend` shows `POST /webhook 200`.
- `normalize_inbound` parses Meta's **actual** payload (a `text` message, then an
  `interactive.button_reply` when the patient taps a button).
- The booking flow completes; `booking_confirmed` arrives with a **tappable** button.
- Tapping **"आ गए / arrived"** flips the entry to `arrived` in the DB
  (`select status from queue_entries order by booked_at desc limit 1`).
- **Expect 1–2 wire-format mismatches here** (button-reply nesting, template
  param counts) — they surface nowhere earlier. Fix in `app/wa/webhook.py`
  (parsing) or `app/wa/templates.py` (params) and record what you hit in a note.

**2. Panel login** on the Vercel domain (slug + PIN) → the live queue shows the
booking from step 1.

**3. NEXT + undo** against prod: press NEXT (serves/holds correctly), then the 5s
UNDO restores the prior state.

**4. A scheduled ping fires:** watch `/metrics.scheduler_last_tick` advance, or a
`pre_arrival`/`three_away` send in the logs at the right time.

**5. No duplicate sends:** confirm each notification appears **once** in
`wa_messages` (single-instance guard working). If you see doubles, you have >1
process with `RUN_SCHEDULER=true` — fix immediately.

---

## Rollback / pause mid-session

- **Pause the queue** (no data loss): panel → session controls → Pause. Bookings
  still arrive; NEXT is held.
- **Stop the clinic entirely today:** panel → **Close today** (patients seen are
  recorded; waiting patients get the rebook message). Mis-tap? **Reopen** (same
  day) — note it does **not** re-summon already-notified patients.
- **Backend rollback:** `docker compose down` then redeploy the previous image
  tag; the DB is the source of truth and is untouched by a redeploy.
