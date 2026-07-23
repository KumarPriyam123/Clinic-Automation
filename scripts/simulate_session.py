"""Session simulator — demo + QA tool.

Runs a fake clinic session with N scripted patients on the in-memory backend,
driving the real engine + scheduler jobs with a compressed FakeClock (default
60:1). Prints every WhatsApp send it would make (dry-run), or sends for real to
a test number.

    python scripts/simulate_session.py --dry-run          # default, prints sends
    python scripts/simulate_session.py --patients 8
    python scripts/simulate_session.py --real +91XXXXXXXXXX   # live test number

Nothing here is imported by the app; it's a standalone driver.
"""

from __future__ import annotations

import argparse
import asyncio
import pathlib
import sys
import time as _time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "backend"))

from app import engine  # noqa: E402
from app.engine.state import Patient, SessionState  # noqa: E402
from app.jobs.pings import ping_scan  # noqa: E402
from app.jobs.store import ClinicRow, MemJobs  # noqa: E402
from app.jobs.sweep import sweep_tick  # noqa: E402
from app.models import SessionStatus, Source  # noqa: E402
from app.wa.notify import NotificationDispatcher, fmt_time  # noqa: E402
from app.wa.sender import Sender  # noqa: E402
from app.wa.store import InMemoryWaStore  # noqa: E402


class PrintSender(Sender):
    """Dry-run gateway: prints the message instead of calling the Graph API."""

    def __init__(self, clock):
        super().__init__(InMemoryWaStore(), token="x", phone_number_id="0")
        self._clock = clock

    async def send(
        self,
        now,
        wa,
        *,
        template_name,
        ctx,
        lang="hi",
        clinic_id=None,
        force_template=False,
    ):
        eta = ctx.get("eta", "")
        extra = f" eta={eta}" if eta else ""
        print(f"  [{fmt_time(self._clock[0])}] -> {wa}  {template_name}{extra}")
        return {}


def _clock_now(clock):
    return clock[0]


async def simulate(n_patients: int, real_to: str | None, speed: float) -> None:
    backend = MemJobs()
    clock = [datetime(2026, 7, 6, 9, 0, tzinfo=UTC)]  # mutable sim clock (IST 14:30)

    if real_to:
        sender = Sender(InMemoryWaStore())  # uses env WA creds
    else:
        sender = PrintSender(clock)
    disp = NotificationDispatcher(sender, backend.resolver())

    clinic = ClinicRow(uuid4(), "hi", "Demo Clinic", "Dr. Demo", real_to or "+9199999")
    backend.add_clinic(clinic)
    session = SessionState(
        id=uuid4(),
        clinic_id=clinic.id,
        date=clock[0].date(),
        name="morning",
        start_at=clock[0],
        end_at=clock[0] + timedelta(hours=3),
        token_cap=40,
        status=SessionStatus.open,
        doctor_free_at=clock[0],
        avg_consult_s=600,
    )
    backend.repo.add_session(session)

    # book N patients: alternate asap / future targets
    entry_ids: list = []
    for i in range(n_patients):
        wa = real_to if real_to else f"+9110000{i:05d}"
        p = Patient(id=uuid4(), clinic_id=clinic.id, wa_number=wa, profile_name=f"p{i}")
        backend.repo.add_patient(p)
        req = clock[0] + timedelta(minutes=20 * i) if i % 2 else None
        res = await backend.engine_call(
            lambda r, pid=p.id, req=req: engine.book(
                r,
                clock[0],
                clinic_id=clinic.id,
                session_id=session.id,
                patient_id=pid,
                requested_time=req,
                source=Source.whatsapp,
            )
        )
        entry_ids.append(res.entry.id)
        print(f"[{fmt_time(clock[0])}] booked token {res.entry.token_number} ({wa})")

    async def act(factory):
        res = await backend.engine_call(factory)
        await disp.dispatch(_clock_now(clock), res)

    # scripted actions keyed by simulated minute-offset
    script = {
        2: ("arrive", 0),
        5: ("next", None),
        8: ("delay", 30),
        12: ("arrive", 1),
        15: ("next", None),
        20: ("cancel", 2),
    }

    print("\n--- session running (compressed) ---")
    for minute in range(0, 190):
        clock[0] = clock[0] + timedelta(minutes=1)
        now = clock[0]
        if minute in script:
            kind, arg = script[minute]
            if kind == "arrive" and arg < len(entry_ids):
                await act(
                    lambda r, eid=entry_ids[arg]: engine.mark_arrived(r, now, eid)
                )
                print(f"[{fmt_time(now)}] patient arrived")
            elif kind == "next":
                await act(lambda r: engine.next_patient(r, now, session.id))
                print(f"[{fmt_time(now)}] doctor pressed NEXT")
            elif kind == "delay":
                await act(lambda r: engine.delay_session(r, now, session.id, arg))
                print(f"[{fmt_time(now)}] doctor delayed {arg}m")
            elif kind == "cancel" and arg < len(entry_ids):
                await act(lambda r, eid=entry_ids[arg]: engine.cancel(r, now, eid))
                print(f"[{fmt_time(now)}] patient cancelled")
        await ping_scan(backend, disp, now)
        await sweep_tick(backend, disp, now)
        if speed:
            _time.sleep(speed)

    print("--- done ---")


async def pg_drive(n_patients: int, speed: float) -> None:
    """QA mode: drive real bookings/arrivals into today's OPEN demo session in
    Postgres, spaced in wall-clock time, so the running panel shows them land
    live (4s poll + chime + badge). No WhatsApp sends. Pairs with `make qa-seed`.

        DATABASE_URL=... python scripts/simulate_session.py --pg --patients 4 --speed 5
    """
    import os

    from app import db  # noqa: PLC0415
    from app.engine.pg_repo import PgRepo  # noqa: PLC0415
    from app.models import Source  # noqa: PLC0415

    dsn = os.getenv("DATABASE_URL", "postgresql://localhost:5432/clinicq")
    await db.init_pool(dsn)
    pool = db.get_pool()

    async with pool.acquire() as con:
        clinic_id = await con.fetchval("select id from clinics where slug = 'demo'")
        sid = await con.fetchval(
            "select id from sessions where clinic_id = $1 "
            "and date = (now() at time zone 'Asia/Kolkata')::date and status = 'open' "
            "order by start_at limit 1",
            clinic_id,
        )
    if sid is None:
        print(
            "No OPEN demo session today. Run `make qa-seed` (or start one in the panel) first."
        )
        await db.close_pool()
        return

    delay = speed or 5.0
    print(
        f"Driving into session {sid} — watch the panel. ({delay:.0f}s between events)"
    )
    for i in range(n_patients):
        now = datetime.now(UTC)
        async with pool.acquire() as con:
            pid = await con.fetchval(
                "insert into patients (clinic_id, wa_number, display_name) values ($1, $2, $3) "
                "returning id",
                clinic_id,
                f"+9197{uuid4().int % 100000000:08d}",
                f"Sim {i + 1}",
            )
        async with pool.acquire() as con, con.transaction():
            res = await engine.book(
                PgRepo(con),
                now,
                clinic_id=clinic_id,
                session_id=sid,
                patient_id=pid,
                requested_time=None,
                source=Source.whatsapp,
            )
        print(
            f"  booked token {res.entry.token_number} (Sim {i + 1}) — panel should chime"
        )
        _time.sleep(delay)
        if i % 2 == 1:  # arrive every other one
            async with pool.acquire() as con, con.transaction():
                await engine.mark_arrived(PgRepo(con), datetime.now(UTC), res.entry.id)
            print(f"  Sim {i + 1} arrived — chip flips green")
            _time.sleep(delay)
    print("--- done. NEXT/undo from the panel to finish the walkthrough. ---")
    await db.close_pool()


def main() -> None:
    ap = argparse.ArgumentParser(description="ClinicQ session simulator")
    ap.add_argument("--dry-run", action="store_true", help="print sends (default)")
    ap.add_argument("--real", metavar="+91…", help="send for real to this test number")
    ap.add_argument(
        "--pg", action="store_true", help="drive real bookings into the DB (QA panel)"
    )
    ap.add_argument("--patients", type=int, default=5)
    ap.add_argument(
        "--speed", type=float, default=0.0, help="seconds of real sleep per sim-minute"
    )
    args = ap.parse_args()
    if args.pg:
        asyncio.run(pg_drive(args.patients, args.speed))
    else:
        asyncio.run(simulate(args.patients, args.real, args.speed))


if __name__ == "__main__":
    main()
