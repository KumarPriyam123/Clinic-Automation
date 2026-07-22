"""PgJobs smoke against real PG — stamp/open/close/digest SQL correctness.

Skips when DATABASE_URL_TEST is unset.
"""

from __future__ import annotations

import asyncio
import pathlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app import db
from app.jobs.store import PgJobs
from tests.pg_util import DSN

pytestmark = pytest.mark.skipif(not DSN, reason="DATABASE_URL_TEST not set")

_MIGRATIONS = sorted(
    (pathlib.Path(__file__).resolve().parents[2] / "supabase" / "migrations").glob("*.sql")
)
MONDAY = datetime(2026, 7, 6, 9, 0, tzinfo=UTC)  # 09:00 UTC = 14:30 IST, a Monday


async def _reset():
    await db.init_pool(DSN)
    async with db.get_pool().acquire() as con:
        await con.execute("drop schema public cascade; create schema public;")
        for m in _MIGRATIONS:
            await con.execute(m.read_text(encoding="utf-8"))
        cid = await con.fetchval(
            "insert into clinics (slug, pin_hash, name, doctor_name, language, "
            "wa_display_number) values ($1,'h','C','Dr','hi','+9199999') returning id",
            f"c{uuid4().hex[:8]}",
        )
        # Monday timetable: weekday 0
        await con.execute(
            "insert into timetable (clinic_id, weekday, name, start_time, end_time, token_cap) "
            "values ($1,0,'morning','09:00','13:00',40),($1,0,'evening','17:00','21:00',40)",
            cid,
        )
    return cid


def test_stamp_open_close_digest():
    async def scenario():
        cid = await _reset()
        jobs = PgJobs()

        created = await jobs.stamp_sessions(MONDAY)
        again = await jobs.stamp_sessions(MONDAY)  # idempotent (on conflict do nothing)

        # a stamped morning session starts 09:00 IST; at 10:00 IST it is open-able
        ist_10 = MONDAY.replace(hour=4, minute=30)  # 10:00 IST
        to_open = await jobs.sessions_to_open(ist_10)

        # open one, then it should be close-able after its end_at
        async with db.get_pool().acquire() as con:
            await con.execute("update sessions set status='open' where id = $1", to_open[0])
            pid = await con.fetchval(
                "insert into patients (clinic_id, wa_number) values ($1,'+91x') returning id", cid
            )
            await con.execute(
                "insert into queue_entries (session_id, clinic_id, patient_id, token_number, "
                "priority_time, status, source) values ($1,$2,$3,1,now(),'done','whatsapp')",
                to_open[0],
                cid,
                pid,
            )
            end_at = await con.fetchval("select end_at from sessions where id=$1", to_open[0])
        to_close = await jobs.sessions_to_close(end_at + timedelta(minutes=1))
        stats = await jobs.digest_stats(cid, ist_10)

        await db.close_pool()
        return len(created), again, len(to_open), to_open[0] in to_close, stats.seen

    n_created, again, n_open, closable, seen = asyncio.run(scenario())
    assert n_created >= 1 and again == []  # stamped once, idempotent
    assert n_open >= 1  # morning session open-able mid-window
    assert closable  # open session past end_at is close-able
    assert seen == 1  # digest counts the done entry
