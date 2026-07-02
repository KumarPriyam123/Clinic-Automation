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

## Status

P0 scaffold only: `/healthz` + placeholder panel. Queue engine, WhatsApp layer, LLM parser, and migrations land in later phases (see `clinicq_build_plan.md`).
