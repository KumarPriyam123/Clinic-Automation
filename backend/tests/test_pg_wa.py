"""Part 0 gate — Pg WA store: wamid dedupe under concurrency + real-row window.

Skips when DATABASE_URL_TEST is unset. Each test owns a fresh schema.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.wa.sender import Sender
from app.wa.store import PgWaStore
from tests.pg_util import DSN, fresh_pool

pytestmark = pytest.mark.skipif(not DSN, reason="DATABASE_URL_TEST not set")

T0 = datetime(2026, 7, 5, 9, 0, tzinfo=UTC)


async def _clinic(pool):
    async with pool.acquire() as con:
        return await con.fetchval(
            "insert into clinics (slug, pin_hash, name, doctor_name) "
            "values ($1, 'h', 'C', 'Dr') returning id",
            f"c{uuid4().hex[:8]}",
        )


def test_wamid_dedupe_under_concurrency():
    """Two concurrent inserts of the SAME wamid (Meta retry storm) -> exactly
    one row persists, no exception surfaces (UNIQUE(wamid) + ON CONFLICT)."""

    async def scenario():
        pool = await fresh_pool()
        try:
            cid = await _clinic(pool)

            async def ins():
                async with pool.acquire() as con:
                    return await PgWaStore(con).record_inbound(
                        clinic_id=cid,
                        wa_number="+91x",
                        wamid="wamid.DUP",
                        kind="text",
                        payload={"t": "hi"},
                        at=T0,
                    )

            results = await asyncio.gather(ins(), ins())
            async with pool.acquire() as con:
                count = await con.fetchval(
                    "select count(*) from wa_messages where wamid = 'wamid.DUP'"
                )
            return results, count
        finally:
            await pool.close()

    results, count = asyncio.run(scenario())
    assert count == 1  # exactly one row
    assert sorted(results) == [False, True]  # one stored, one skipped, no error


def test_is_window_open_against_real_rows():
    async def scenario():
        pool = await fresh_pool()
        try:
            cid = await _clinic(pool)
            # last inbound at exactly T0 (explicit created_at -> real timestamptz)
            async with pool.acquire() as con:
                await con.execute(
                    "insert into wa_messages (clinic_id, wa_number, direction, wamid, created_at) "
                    "values ($1, '+91y', 'in', 'wamid.W', $2)",
                    cid,
                    T0,
                )
                s = Sender(PgWaStore(con), token="t", phone_number_id="1")
                within = await s.is_window_open(T0 + timedelta(hours=23, minutes=59), "+91y")
                beyond = await s.is_window_open(T0 + timedelta(hours=24, minutes=1), "+91y")
            return within, beyond
        finally:
            await pool.close()

    within, beyond = asyncio.run(scenario())
    assert within is True
    assert beyond is False
