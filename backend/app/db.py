"""Async Postgres access — asyncpg pool + small typed query helpers.

No ORM. Raw SQL; asyncpg records are mapped onto the pydantic models in
`app.models`. A module-level pool is created once (FastAPI lifespan / tests)
and shared. jsonb columns are decoded to dict via a per-connection codec so
they land straight in the models.
"""

from __future__ import annotations

import json
from typing import Any, TypeVar

import asyncpg
from pydantic import BaseModel

from app.config import settings
from app.models import Clinic

M = TypeVar("M", bound=BaseModel)

_pool: asyncpg.Pool | None = None


async def _init_connection(con: asyncpg.Connection) -> None:
    """Decode json/jsonb to python objects (dict/list) instead of str."""
    for typ in ("json", "jsonb"):
        await con.set_type_codec(
            typ,
            encoder=json.dumps,
            decoder=json.loads,
            schema="pg_catalog",
        )


async def init_pool(dsn: str | None = None, **kwargs: Any) -> asyncpg.Pool:
    """Create the shared pool (idempotent). Call once at startup / test setup."""
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            dsn or settings.DATABASE_URL,
            init=_init_connection,
            min_size=1,
            max_size=10,
            **kwargs,
        )
    return _pool


def get_pool() -> asyncpg.Pool:
    """Return the shared pool. Raises if `init_pool` was never called."""
    if _pool is None:
        raise RuntimeError("DB pool not initialized — call init_pool() first")
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


# --------------------------------------------------------------------------- #
# Generic helpers
# --------------------------------------------------------------------------- #
def _map(record: asyncpg.Record | None, model: type[M]) -> M | None:
    return model.model_validate(dict(record)) if record is not None else None


def _map_all(records: list[asyncpg.Record], model: type[M]) -> list[M]:
    return [model.model_validate(dict(r)) for r in records]


async def fetch_one(sql: str, *args: Any, model: type[M]) -> M | None:
    """Run a query returning at most one row, mapped to `model`."""
    row = await get_pool().fetchrow(sql, *args)
    return _map(row, model)


async def fetch_all(sql: str, *args: Any, model: type[M]) -> list[M]:
    """Run a query returning many rows, each mapped to `model`."""
    rows = await get_pool().fetch(sql, *args)
    return _map_all(rows, model)


async def execute(sql: str, *args: Any) -> str:
    """Run a statement, returning asyncpg's status string."""
    return await get_pool().execute(sql, *args)


# --------------------------------------------------------------------------- #
# Typed table helpers (extend per phase; kept small on purpose)
# --------------------------------------------------------------------------- #
async def insert_clinic(
    *,
    slug: str,
    pin_hash: str,
    name: str,
    doctor_name: str,
    specialty: str | None = None,
    fee_inr: int | None = None,
    language: str = "hi",
) -> Clinic:
    row = await get_pool().fetchrow(
        """
        insert into clinics (slug, pin_hash, name, doctor_name, specialty, fee_inr, language)
        values ($1, $2, $3, $4, $5, $6, $7)
        returning *
        """,
        slug,
        pin_hash,
        name,
        doctor_name,
        specialty,
        fee_inr,
        language,
    )
    return Clinic.model_validate(dict(row))


async def get_clinic_by_slug(slug: str) -> Clinic | None:
    return await fetch_one("select * from clinics where slug = $1", slug, model=Clinic)
