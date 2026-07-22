"""Part 0 gate — PgRepo parity with MemRepo + real SELECT…FOR UPDATE locking.

Runs the P2 engine scenarios (t1, t7, t8, t11) through the REAL PgRepo against
DATABASE_URL_TEST and asserts identical outcomes to the MemRepo versions, then
proves the row-lock seam with two concurrent next_patient calls.

Skips cleanly when DATABASE_URL_TEST is unset. Each test owns a fresh schema.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app import engine
from app.engine.pg_repo import PgRepo
from app.engine.state import Entry
from app.models import Source, Status
from tests.pg_util import DSN, fresh_pool

pytestmark = pytest.mark.skipif(not DSN, reason="DATABASE_URL_TEST not set")


def dt(h: int, m: int = 0, s: int = 0) -> datetime:
    return datetime(2026, 7, 5, h, m, s, tzinfo=UTC)


async def _seed(pool, *, now, avg=600, cap=40, n=3, doctor_free_at=None, end=None):
    async with pool.acquire() as con:
        cid = await con.fetchval(
            "insert into clinics (slug, pin_hash, name, doctor_name) "
            "values ($1, 'h', 'C', 'Dr') returning id",
            f"c{uuid4().hex[:8]}",
        )
        sid = await con.fetchval(
            "insert into sessions (clinic_id, date, name, start_at, end_at, token_cap, "
            "status, doctor_free_at, avg_consult_s) "
            "values ($1, $2, 'morning', $3, $4, $5, 'open', $6, $7) returning id",
            cid,
            now.date(),
            now,
            end or now + timedelta(hours=6),
            cap,
            doctor_free_at or now,
            avg,
        )
        pids = []
        for i in range(n):
            pid = await con.fetchval(
                "insert into patients (clinic_id, wa_number) values ($1, $2) returning id",
                cid,
                f"+9190000{i:05d}",
            )
            pids.append(pid)
    return cid, sid, pids


async def _call(pool, factory):
    """One engine call in its own transaction (lock held until commit)."""
    async with pool.acquire() as con, con.transaction():
        return await factory(PgRepo(con))


async def _read(pool, sid) -> list[Entry]:
    async with pool.acquire() as con:
        return await PgRepo(con).list_entries(sid)


def _book(pool, cid, sid, pid, now, req=None, source=Source.whatsapp):
    return _call(
        pool,
        lambda r: engine.book(
            r,
            now,
            clinic_id=cid,
            session_id=sid,
            patient_id=pid,
            requested_time=req,
            source=source,
        ),
    )


# --------------------------------------------------------------------------- #
def test_t1_priority_order_via_pg():
    async def scenario():
        pool = await fresh_pool()
        try:
            cid, sid, ps = await _seed(pool, now=dt(9))
            await _book(pool, cid, sid, ps[0], dt(9), req=dt(12))
            await _book(pool, cid, sid, ps[1], dt(9), req=dt(11))
            await _book(pool, cid, sid, ps[2], dt(9), req=dt(10))
            entries = sorted(await _read(pool, sid), key=Entry.order_key)
            return [e.priority_time for e in entries]
        finally:
            await pool.close()

    assert asyncio.run(scenario()) == [dt(10), dt(11), dt(12)]


def test_t7_present_beats_absent_via_pg():
    async def scenario():
        pool = await fresh_pool()
        try:
            cid, sid, ps = await _seed(pool, now=dt(10))
            a = (await _book(pool, cid, sid, ps[0], dt(10), req=dt(10))).entry
            b = (await _book(pool, cid, sid, ps[1], dt(10), req=dt(10, 5))).entry
            await _call(pool, lambda r: engine.mark_arrived(r, dt(10), b.id))
            await _call(pool, lambda r: engine.next_patient(r, dt(10), sid))
            entries = {e.id: e for e in await _read(pool, sid)}
            return entries[a.id].status, entries[b.id].status, entries[a.id].grace_until
        finally:
            await pool.close()

    a_status, b_status, grace = asyncio.run(scenario())
    assert a_status == Status.skipped and grace is not None
    assert b_status == Status.in_consult


def test_t8_grace_reinsert_served_first_via_pg():
    async def scenario():
        pool = await fresh_pool()
        try:
            cid, sid, ps = await _seed(pool, now=dt(10))
            a = (await _book(pool, cid, sid, ps[0], dt(10), req=dt(10))).entry
            b = (await _book(pool, cid, sid, ps[1], dt(10), req=dt(10, 5))).entry
            await _call(pool, lambda r: engine.mark_arrived(r, dt(10), b.id))
            await _call(pool, lambda r: engine.next_patient(r, dt(10), sid))
            await _call(pool, lambda r: engine.arrived_during_grace(r, dt(10, 5), a.id))
            await _call(pool, lambda r: engine.next_patient(r, dt(10, 10), sid))
            entries = {e.id: e for e in await _read(pool, sid)}
            return entries[a.id].status, entries[b.id].status
        finally:
            await pool.close()

    a_status, b_status = asyncio.run(scenario())
    assert b_status == Status.done
    assert a_status == Status.in_consult


def test_t11_gap_autopull_arrived_via_pg():
    async def scenario():
        pool = await fresh_pool()
        try:
            cid, sid, ps = await _seed(pool, now=dt(10), doctor_free_at=dt(10))
            x = (await _book(pool, cid, sid, ps[0], dt(10), req=dt(10))).entry
            y = (await _book(pool, cid, sid, ps[1], dt(10), req=dt(11))).entry
            await _call(pool, lambda r: engine.mark_arrived(r, dt(10), y.id))
            await _call(pool, lambda r: engine.cancel(r, dt(10), x.id))
            entries = {e.id: e for e in await _read(pool, sid)}
            return entries[y.id].priority_time
        finally:
            await pool.close()

    assert asyncio.run(scenario()) == dt(10)


def test_concurrent_next_patient_serves_exactly_one():
    """Two next_patient calls on separate connections must not both serve the
    same ARRIVED entry — PgRepo.lock_session (SELECT…FOR UPDATE) serializes them."""

    async def scenario():
        pool = await fresh_pool()
        try:
            cid, sid, ps = await _seed(pool, now=dt(10), n=1)
            p = (await _book(pool, cid, sid, ps[0], dt(10))).entry
            await _call(pool, lambda r: engine.mark_arrived(r, dt(10), p.id))

            async def one_next():
                async with pool.acquire() as con, con.transaction():
                    return await engine.next_patient(PgRepo(con), dt(10, 1), sid)

            r1, r2 = await asyncio.gather(one_next(), one_next())
            entries = await _read(pool, sid)
            served = [r for r in (r1, r2) if r.entry is not None]
            async with pool.acquire() as con:
                called = await con.fetchval(
                    "select count(*) from events where type = 'called' and entry_id = $1", p.id
                )
            return served, entries, called, p.id
        finally:
            await pool.close()

    served, entries, called, pid = asyncio.run(scenario())
    assert len(served) == 1  # exactly one call served a patient
    assert served[0].entry.id == pid  # ...and it served the ARRIVED patient
    assert called == 1  # served exactly once — the FOR UPDATE lock held (no double serve)
    pf = [e for e in entries if e.id == pid]
    assert len(pf) == 1 and pf[0].status in (Status.in_consult, Status.done)
