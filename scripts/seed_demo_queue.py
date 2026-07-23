"""QA seed — a realistic live queue for the panel in one command.

Assumes migrations + demo clinic already applied (``supabase db reset`` runs
supabase/seed.sql). This script then, against ``DATABASE_URL``:
  * ensures today's 'morning' session exists and is OPEN (doctor_free_at = now),
  * clears any prior entries on it,
  * books ~5 patients at varied target times through the REAL engine (so
    token_number / priority_time / eta are all correct), and
  * marks two of them ARRIVED.

Result: open the panel and it lands on a realistic board — someone servable,
absent front tokens, future targets — with zero manual setup. `simulate_session
--pg` drives more bookings/arrivals into THIS SAME session so you watch it move.

    make qa-seed        # supabase db reset + this script
    python scripts/seed_demo_queue.py
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import sys
from datetime import UTC, datetime, timedelta
from uuid import uuid4

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "backend"))

from app import db, engine  # noqa: E402
from app.engine.pg_repo import PgRepo  # noqa: E402
from app.models import Source  # noqa: E402

# (name, requested-time offset minutes or None=ASAP, arrive?)
PLAN = [
    ("Asha Devi", None, True),  # arrived, servable now
    ("Ramesh Kumar", 0, False),  # absent front token
    ("Priya Sharma", 5, True),  # arrived, slightly later target
    ("Sanjay Gupta", 20, False),  # future target, not here yet
    ("Meena Kumari", 40, False),  # later still
]


async def _ensure_open_session(con, clinic_id) -> str:
    now = datetime.now(UTC)
    sid = await con.fetchval(
        """
        insert into sessions (clinic_id, date, name, start_at, end_at, token_cap, status,
                              doctor_free_at, avg_consult_s)
        values ($1, (now() at time zone 'Asia/Kolkata')::date, 'morning', $2, $3, 40, 'open',
                $4, 420)
        on conflict (clinic_id, date, name)
          do update set status = 'open', doctor_free_at = $4
        returning id
        """,
        clinic_id,
        now - timedelta(minutes=10),
        now + timedelta(hours=6),
        now,
    )
    return sid


async def main() -> None:
    dsn = os.getenv("DATABASE_URL", "postgresql://localhost:5432/clinicq")
    await db.init_pool(dsn)
    pool = db.get_pool()
    now = datetime.now(UTC)

    async with pool.acquire() as con:
        clinic_id = await con.fetchval("select id from clinics where slug = 'demo'")
        if clinic_id is None:
            print(
                "No 'demo' clinic — run `supabase db reset` (applies seed.sql) first."
            )
            return
        sid = await _ensure_open_session(con, clinic_id)
        # fresh board
        await con.execute("delete from queue_entries where session_id = $1", sid)

        patient_ids = []
        for name, _off, _arr in PLAN:
            pid = await con.fetchval(
                """
                insert into patients (clinic_id, wa_number, display_name)
                values ($1, $2, $3)
                on conflict (clinic_id, wa_number, profile_name)
                  do update set display_name = excluded.display_name
                returning id
                """,
                clinic_id,
                f"+9198{uuid4().int % 100000000:08d}",
                name,
            )
            patient_ids.append(pid)

    # book + arrive through the real engine (correct tokens / etas)
    booked = []
    for (name, off, arrive), pid in zip(PLAN, patient_ids, strict=True):
        req = None if off is None else now + timedelta(minutes=off)
        async with pool.acquire() as con, con.transaction():
            res = await engine.book(
                PgRepo(con),
                now,
                clinic_id=clinic_id,
                session_id=sid,
                patient_id=pid,
                requested_time=req,
                source=Source.whatsapp,
            )
        entry = res.entry
        booked.append((entry.id, entry.token_number, name))
        if arrive:
            async with pool.acquire() as con, con.transaction():
                await engine.mark_arrived(PgRepo(con), now, entry.id)

    print(f"Session {sid} OPEN with {len(booked)} patients:")
    for _eid, tok, name in booked:
        print(f"  token {tok:>2}  {name}")
    print("\nOpen the panel (slug demo / PIN 123456) — it should land on this queue.")
    await db.close_pool()


if __name__ == "__main__":
    asyncio.run(main())
