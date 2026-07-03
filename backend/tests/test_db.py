"""DB round-trip test: apply migration, insert a clinic, read it back typed.

Skipped unless DATABASE_URL_TEST points at a disposable Postgres (the test
wipes the `public` schema). Run against a local Supabase or a throwaway PG:

    DATABASE_URL_TEST=postgresql://postgres:postgres@localhost:54322/postgres pytest
"""

from __future__ import annotations

import asyncio
import os
import pathlib

import pytest

from app import db
from app.models import Clinic

DSN = os.getenv("DATABASE_URL_TEST")

pytestmark = pytest.mark.skipif(
    not DSN, reason="DATABASE_URL_TEST not set (needs a disposable Postgres)"
)

_MIGRATION = (
    pathlib.Path(__file__).resolve().parents[2]
    / "supabase"
    / "migrations"
    / "20260703000001_init.sql"
)


async def _roundtrip() -> Clinic | None:
    await db.init_pool(DSN)
    try:
        pool = db.get_pool()
        async with pool.acquire() as con:
            # Fresh schema, then apply the real migration file verbatim.
            await con.execute("drop schema public cascade; create schema public;")
            await con.execute(_MIGRATION.read_text(encoding="utf-8"))

        await db.insert_clinic(
            slug="test",
            pin_hash="$2b$12$notarealhashjustfortests000000000000000000000000000",
            name="Test Clinic",
            doctor_name="Dr. Test",
            specialty="GP",
            fee_inr=300,
            language="hi",
        )
        return await db.get_clinic_by_slug("test")
    finally:
        await db.close_pool()


def test_insert_and_read_clinic_typed() -> None:
    clinic = asyncio.run(_roundtrip())
    assert isinstance(clinic, Clinic)
    assert clinic.slug == "test"
    assert clinic.doctor_name == "Dr. Test"
    assert clinic.fee_inr == 300
    assert clinic.language == "hi"
    # jsonb decoded to dict, not str
    assert clinic.settings == {}
