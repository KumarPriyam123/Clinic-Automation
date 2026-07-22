"""Shared helpers for the Postgres integration gate (Part 0).

Gated behind DATABASE_URL_TEST — the test modules skip cleanly when unset.
Each caller resets the schema (drop + re-apply migrations) so there is no
cross-test state leakage, and uses the same jsonb codec as app.db so PgRepo's
dict payloads round-trip.
"""

from __future__ import annotations

import os
import pathlib

import asyncpg

from app import db

DSN = os.getenv("DATABASE_URL_TEST")

_MIGRATIONS = sorted(
    (pathlib.Path(__file__).resolve().parents[2] / "supabase" / "migrations").glob("*.sql")
)


async def fresh_pool() -> asyncpg.Pool:
    """A pool on a freshly-migrated schema (drops public first)."""
    pool = await asyncpg.create_pool(DSN, init=db._init_connection, min_size=1, max_size=10)
    async with pool.acquire() as con:
        await con.execute("drop schema public cascade; create schema public;")
        for m in _MIGRATIONS:
            await con.execute(m.read_text(encoding="utf-8"))
    return pool
