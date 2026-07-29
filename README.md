# ClinicQ

WhatsApp-based virtual token queue for single-doctor Indian clinics. Patients book / track / check-in on WhatsApp; the clinic runs the queue from a mobile-first web panel. Multi-tenant by `clinic_id` from day one.

See `CLAUDE.md` for the project constitution (architecture, queue rules, conventions) — it is the source of truth.

## Repo layout

```
Clinic Appointment/
  CLAUDE.md              # project constitution — read first
  clinicq_build_plan.md  # phased build plan
  backend/               # FastAPI, Python 3.11 (webhook + panel API + queue engine + jobs)
    app/main.py          # app factory, GET /healthz
    app/config.py        # pydantic-settings
    tests/
  panel/                 # Next.js 14 app router, TS strict, Tailwind
  supabase/migrations/   # DDL (source of truth for schema) — empty for now
  docs/
```

## Backend

Python 3.11. From `backend/`:

```powershell
python -m venv .venv
.venv\Scripts\activate           # macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

Health check: `http://127.0.0.1:8000/healthz` → `{"ok": true}`

Tests (no network, fake clock):

```powershell
pytest
```

Lint / format:

```powershell
ruff check . ; black .
```

Copy `backend/.env.example` → `backend/.env` and fill values before wiring WhatsApp / DB.

## Panel

Next.js 14, TypeScript strict, Tailwind. From `panel/`:

```powershell
npm install
npm run dev
```

Opens `http://localhost:3000` → renders **ClinicQ panel**.

## Deploy & pilot

Deploy-ready: backend (Docker + Cloudflare Tunnel), panel (Vercel), Postgres (Supabase).

- `docs/DEPLOY.md` — full runbook (Meta/WhatsApp, Supabase, droplet, ENV matrix, smoke checklist).
- `docs/ONBOARDING.md` — 60-minute clinic setup.
- `docs/PILOT_METRICS.md` — the case-study SQL.
- Migrations without the Supabase CLI: `python scripts/migrate.py [--seed]`.
- Create a clinic: `python scripts/create_clinic.py --slug ... --pin ...`.
- QR poster: `python scripts/qr_poster.py --number ... --clinic ...` (needs `pip install ".[pilot]"`).

**Scheduler single-instance:** APScheduler runs in-process — keep `uvicorn --workers 1`
and `RUN_SCHEDULER=true` in exactly one process, or every job double-fires
(duplicate patient sends). See DEPLOY.md.
