"""Create (or update) a clinic + its weekly timetable — onboarding, not raw SQL.

Hashes the PIN with bcrypt, inserts the clinic, and stamps a default Mon–Sat
morning+evening timetable (override with flags). Idempotent on slug: re-running
updates name/doctor/PIN and replaces the timetable.

    DATABASE_URL=postgresql://... python scripts/create_clinic.py \
        --slug sharma --name "Sharma Clinic" --doctor "Dr. Sharma" \
        --pin 481902 --language hi --fee 300 \
        --morning 09:00-13:00 --evening 17:00-21:00 --cap 40

Print the panel login at the end. Never echoes the PIN back into logs.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import time

import asyncpg
import bcrypt


def _parse_window(spec: str) -> tuple[time, time]:
    a, b = spec.split("-")
    return _hhmm(a), _hhmm(b)


def _hhmm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


async def run(args) -> int:
    pin = args.pin.strip()
    if not (pin.isdigit() and len(pin) == 6):
        print("PIN must be exactly 6 digits.", file=sys.stderr)
        return 2
    pin_hash = bcrypt.hashpw(pin.encode(), bcrypt.gensalt()).decode()

    con = await asyncpg.connect(args.dsn)
    try:
        async with con.transaction():
            clinic_id = await con.fetchval(
                """
                insert into clinics (slug, pin_hash, name, doctor_name, specialty, fee_inr,
                                     language)
                values ($1, $2, $3, $4, $5, $6, $7)
                on conflict (slug) do update set
                    pin_hash = excluded.pin_hash, name = excluded.name,
                    doctor_name = excluded.doctor_name, specialty = excluded.specialty,
                    fee_inr = excluded.fee_inr, language = excluded.language
                returning id
                """,
                args.slug,
                pin_hash,
                args.name,
                args.doctor,
                args.specialty,
                args.fee,
                args.language,
            )

            windows = []
            if args.morning:
                windows.append(("morning", *_parse_window(args.morning)))
            if args.evening:
                windows.append(("evening", *_parse_window(args.evening)))

            await con.execute("delete from timetable where clinic_id = $1", clinic_id)
            for weekday in range(0, 6):  # Mon..Sat
                for name, start, end in windows:
                    await con.execute(
                        "insert into timetable (clinic_id, weekday, name, start_time, end_time, "
                        "token_cap) values ($1, $2, $3, $4, $5, $6)",
                        clinic_id,
                        weekday,
                        name,
                        start,
                        end,
                        args.cap,
                    )
    finally:
        await con.close()

    print(f"Clinic '{args.name}' ready (id={clinic_id}).")
    print(f"Panel login:  slug = {args.slug}   PIN = <the 6 digits you set>")
    print(
        f"Timetable: Mon–Sat  {args.morning or '—'} / {args.evening or '—'}  cap {args.cap}"
    )
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Create/update a ClinicQ clinic")
    ap.add_argument(
        "--slug", required=True, help="panel login code (lowercase, no spaces)"
    )
    ap.add_argument("--name", required=True)
    ap.add_argument("--doctor", required=True)
    ap.add_argument("--pin", required=True, help="6-digit receptionist PIN")
    ap.add_argument("--language", default="hi", choices=["hi", "en"])
    ap.add_argument("--specialty", default=None)
    ap.add_argument("--fee", type=int, default=None)
    ap.add_argument(
        "--morning", default="09:00-13:00", help="HH:MM-HH:MM or empty to skip"
    )
    ap.add_argument(
        "--evening", default="17:00-21:00", help="HH:MM-HH:MM or empty to skip"
    )
    ap.add_argument("--cap", type=int, default=40, help="token cap per session")
    ap.add_argument("--dsn", default=os.getenv("DATABASE_URL"))
    args = ap.parse_args()
    if not args.dsn:
        print("No DATABASE_URL set and no --dsn given.", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
