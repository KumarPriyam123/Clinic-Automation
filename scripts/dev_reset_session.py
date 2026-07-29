"""dev_reset_session.py — DEV ONLY: open/reset today's session for a clinic.

Opens (or creates) today's first session for a clinic, resets avg_consult_s to
420s and consults_done to 0, finalizes any stuck in_consult entry, and leaves
the session in a clean open state ready for testing.

NEVER expose this in the panel. It bypasses the engine's rolling-average
learning and should only be run in local dev or before a QA session.

Usage (from the backend/ directory):

    .venv/Scripts/python.exe ../scripts/dev_reset_session.py --slug demo

    # custom window (default: 08:00-14:00 IST today)
    .venv/Scripts/python.exe ../scripts/dev_reset_session.py --slug demo \\
        --start 09:00 --end 13:00

    # reset without confirmation
    .venv/Scripts/python.exe ../scripts/dev_reset_session.py --slug demo -y
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
DEFAULT_AVG_S = 420


def _at_ist(day, hhmm: str) -> datetime:
    h, m = (int(x) for x in hhmm.split(":"))
    ist = datetime(day.year, day.month, day.day, h, m, tzinfo=IST)
    return ist.astimezone(ZoneInfo("UTC"))


async def run(args) -> int:
    try:
        import asyncpg
    except ImportError:
        print("asyncpg not installed — run from inside the backend venv.", file=sys.stderr)
        return 2

    dsn = args.dsn or os.getenv("DATABASE_URL")
    if not dsn:
        print("No DATABASE_URL set and no --dsn given.", file=sys.stderr)
        return 2

    now_utc = datetime.now(UTC)
    today_ist = now_utc.astimezone(IST).date()

    con = await asyncpg.connect(dsn)
    try:
        # Resolve clinic
        clinic = await con.fetchrow(
            "SELECT id, name FROM clinics WHERE slug = $1", args.slug
        )
        if clinic is None:
            print(f"Clinic '{args.slug}' not found.", file=sys.stderr)
            return 1

        clinic_id = clinic["id"]
        print(f"\nClinic: {clinic['name']} ({args.slug})")
        print(f"Today (IST): {today_ist}  —  now UTC: {now_utc.strftime('%H:%M:%S')}")

        # Find today's sessions
        rows = await con.fetch(
            "SELECT id, name, status, avg_consult_s, consults_done, start_at, end_at "
            "FROM sessions WHERE clinic_id = $1 AND date = $2 ORDER BY start_at",
            clinic_id,
            today_ist,
        )

        if rows:
            print(f"\nToday's sessions ({len(rows)}):")
            for r in rows:
                print(
                    f"  {r['id']}  {r['name']}  {r['status']}  "
                    f"avg={r['avg_consult_s']}s  done={r['consults_done']}"
                )
            session_id = rows[0]["id"]
            session_name = rows[0]["name"]
        else:
            # No sessions for today — create one from timetable or use defaults
            tt = await con.fetchrow(
                "SELECT name, start_time, end_time, token_cap FROM timetable "
                "WHERE clinic_id = $1 AND weekday = $2 ORDER BY start_time LIMIT 1",
                clinic_id,
                today_ist.weekday(),
            )
            if tt:
                start_str = tt["start_time"].strftime("%H:%M")
                end_str = tt["end_time"].strftime("%H:%M")
                session_name = tt["name"]
                token_cap = tt["token_cap"]
            else:
                start_str = args.start
                end_str = args.end
                session_name = "morning"
                token_cap = 40

            start_at = _at_ist(today_ist, start_str)
            end_at = _at_ist(today_ist, end_str)
            print(f"\nNo sessions for today. Will create: {session_name} {start_str}–{end_str}")

            if not args.yes:
                ans = input("Create and open? [y/N] ").strip().lower()
                if ans != "y":
                    print("Aborted.")
                    return 0

            session_id = await con.fetchval(
                """
                INSERT INTO sessions
                  (clinic_id, date, name, start_at, end_at, token_cap, status,
                   avg_consult_s, consults_done, doctor_free_at)
                VALUES ($1, $2, $3, $4, $5, $6, 'open', $7, 0, $8)
                ON CONFLICT (clinic_id, date, name)
                DO UPDATE SET status='open', avg_consult_s=$7, consults_done=0,
                              doctor_free_at=$8
                RETURNING id
                """,
                clinic_id,
                today_ist,
                session_name,
                start_at,
                end_at,
                token_cap,
                DEFAULT_AVG_S,
                now_utc,
            )
            print(f"  ✓  Created session {session_id}")
            return 0

        # Show existing stale state and ask before resetting
        stuck = await con.fetchval(
            "SELECT count(*) FROM queue_entries WHERE session_id = $1 AND status = 'in_consult'",
            session_id,
        )
        print(f"\nWill reset session '{session_name}' ({session_id}):")
        print(f"  avg_consult_s → {DEFAULT_AVG_S}s (was {rows[0]['avg_consult_s']}s)")
        print(f"  consults_done → 0 (was {rows[0]['consults_done']})")
        print(f"  status        → open")
        print(f"  doctor_free_at → now")
        if stuck:
            print(f"  stuck in_consult entries: {stuck}  →  will mark done")

        if not args.yes:
            ans = input("\nProceed? [y/N] ").strip().lower()
            if ans != "y":
                print("Aborted.")
                return 0

        async with con.transaction():
            # Finalize any stuck in_consult entries
            if stuck:
                await con.execute(
                    "UPDATE queue_entries SET status='done', done_at=$2 "
                    "WHERE session_id=$1 AND status='in_consult'",
                    session_id,
                    now_utc,
                )
                print(f"  ✓  Finalized {stuck} stuck in_consult entry(ies)")

            await con.execute(
                """
                UPDATE sessions SET
                  status        = 'open',
                  avg_consult_s = $2,
                  consults_done = 0,
                  doctor_free_at = $3
                WHERE id = $1
                """,
                session_id,
                DEFAULT_AVG_S,
                now_utc,
            )

        print(f"  ✓  Session reset and opened. Ready for testing.")
        return 0

    finally:
        await con.close()


def main() -> None:
    ap = argparse.ArgumentParser(
        description="DEV ONLY: open/reset today's session for testing"
    )
    ap.add_argument("--slug", required=True, help="clinic slug (panel login)")
    ap.add_argument("--start", default="08:00", help="session start HH:MM IST if creating")
    ap.add_argument("--end", default="14:00", help="session end HH:MM IST if creating")
    ap.add_argument("--dsn", default=None, help="DATABASE_URL override")
    ap.add_argument("-y", "--yes", action="store_true", help="skip confirmation")
    args = ap.parse_args()
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
