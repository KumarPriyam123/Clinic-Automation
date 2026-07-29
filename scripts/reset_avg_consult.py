"""reset_avg_consult.py — repair a poisoned avg_consult_s value.

A single forgotten NEXT tap can leave a patient in_consult overnight; when
that consult is finally finalized the rolling average absorbs hours of garbage
and permanently corrupts ETA for the clinic.  This script resets the value
back to the 420-second seed (or a supplied value) so the next real consult
starts learning cleanly.

Usage (run from the backend/ directory):

    # reset the OPEN session for clinic 'demo' to 420s default
    .venv/Scripts/python.exe ../scripts/reset_avg_consult.py --slug demo

    # reset a specific session by id
    .venv/Scripts/python.exe ../scripts/reset_avg_consult.py --slug demo \\
        --session-id <uuid>

    # reset to a custom value (e.g. from historical data)
    .venv/Scripts/python.exe ../scripts/reset_avg_consult.py --slug demo \\
        --avg 600
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from uuid import UUID


async def run(args) -> int:
    try:
        import asyncpg
    except ImportError:
        print("asyncpg not installed — run from inside the backend venv", file=sys.stderr)
        return 2

    dsn = args.dsn or os.getenv("DATABASE_URL")
    if not dsn:
        print("No DATABASE_URL set and no --dsn given.", file=sys.stderr)
        return 2

    con = await asyncpg.connect(dsn)
    try:
        # Resolve clinic id
        clinic_id = await con.fetchval("SELECT id FROM clinics WHERE slug = $1", args.slug)
        if clinic_id is None:
            print(f"Clinic '{args.slug}' not found.", file=sys.stderr)
            return 1

        if args.session_id:
            sid = UUID(args.session_id)
            rows = await con.fetch(
                "SELECT id, status, avg_consult_s, date FROM sessions "
                "WHERE id = $1 AND clinic_id = $2",
                sid,
                clinic_id,
            )
        else:
            rows = await con.fetch(
                "SELECT id, status, avg_consult_s, date FROM sessions "
                "WHERE clinic_id = $1 ORDER BY date DESC, start_at DESC LIMIT 5",
                clinic_id,
            )

        if not rows:
            print("No matching sessions found.")
            return 1

        print(f"\nSessions for clinic '{args.slug}':")
        for r in rows:
            print(f"  {r['id']}  date={r['date']}  status={r['status']}  "
                  f"avg_consult_s={r['avg_consult_s']}")

        target = args.avg
        print(f"\nWill reset avg_consult_s → {target}s for the above session(s).")

        if not args.yes:
            ans = input("Proceed? [y/N] ").strip().lower()
            if ans != "y":
                print("Aborted.")
                return 0

        for r in rows:
            await con.execute(
                "UPDATE sessions SET avg_consult_s = $1 WHERE id = $2",
                target,
                r["id"],
            )
            print(f"  ✓  {r['id']}  {r['avg_consult_s']}s → {target}s")

        return 0
    finally:
        await con.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="Reset avg_consult_s for a clinic's sessions")
    ap.add_argument("--slug", required=True, help="clinic slug (panel login)")
    ap.add_argument("--session-id", default=None, help="specific session UUID (default: recent 5)")
    ap.add_argument("--avg", type=int, default=420, help="target avg_consult_s in seconds (default 420)")
    ap.add_argument("--dsn", default=None, help="DATABASE_URL override")
    ap.add_argument("-y", "--yes", action="store_true", help="skip confirmation prompt")
    args = ap.parse_args()
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
