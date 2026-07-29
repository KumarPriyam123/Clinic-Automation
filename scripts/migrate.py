"""Migration runner — applies supabase/migrations/*.sql in filename order.

Replaces `supabase db reset` / `make db-reset` for environments without the
Supabase CLI (prod, Windows dev). Plain asyncpg, no new deps. Tracks applied
files in a `schema_migrations` table so re-runs are idempotent.

    # apply any pending migrations to $DATABASE_URL
    python scripts/migrate.py

    # ...and (re-)apply the demo seed too
    python scripts/migrate.py --seed

    # explicit target
    DATABASE_URL=postgresql://... python scripts/migrate.py --seed

Each *.sql file runs in one transaction; a failure rolls that file back and
stops (later files are not applied). Filenames are the migration identity, so
never rename an applied migration — add a new one.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import pathlib
import sys

import asyncpg

ROOT = pathlib.Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = ROOT / "supabase" / "migrations"
SEED_FILE = ROOT / "supabase" / "seed.sql"

_TRACK_TABLE = """
create table if not exists schema_migrations (
    filename   text primary key,
    applied_at timestamptz not null default now()
)
"""


async def _applied(con: asyncpg.Connection) -> set[str]:
    rows = await con.fetch("select filename from schema_migrations")
    return {r["filename"] for r in rows}


def _connect_kwargs(dsn: str) -> dict:
    kw: dict = {}
    if "pooler.supabase.com" in dsn or ":6543" in dsn:
        kw["statement_cache_size"] = 0  # pgBouncer txn mode: no prepared statements
    if "supabase.co" in dsn or "supabase.com" in dsn:
        kw["ssl"] = "require"
    return kw


async def run(dsn: str, *, seed: bool) -> int:
    con = await asyncpg.connect(dsn, **_connect_kwargs(dsn))
    try:
        await con.execute(_TRACK_TABLE)
        done = await _applied(con)
        pending = [
            p for p in sorted(MIGRATIONS_DIR.glob("*.sql")) if p.name not in done
        ]

        if not pending:
            print("Migrations up to date (nothing to apply).")
        for path in pending:
            sql = path.read_text(encoding="utf-8")
            async with con.transaction():
                await con.execute(sql)
                await con.execute(
                    "insert into schema_migrations (filename) values ($1)", path.name
                )
            print(f"applied  {path.name}")

        if seed:
            async with con.transaction():
                await con.execute(SEED_FILE.read_text(encoding="utf-8"))
            print(f"seeded   {SEED_FILE.name}")
    finally:
        await con.close()
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(
        description="ClinicQ migration runner (no Supabase CLI)"
    )
    ap.add_argument("--seed", action="store_true", help="also apply supabase/seed.sql")
    ap.add_argument(
        "--dsn",
        default=os.getenv("DATABASE_URL"),
        help="target DB (default: $DATABASE_URL)",
    )
    args = ap.parse_args()
    if not args.dsn:
        print("No DATABASE_URL set and no --dsn given.", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(asyncio.run(run(args.dsn, seed=args.seed)))


if __name__ == "__main__":
    main()
