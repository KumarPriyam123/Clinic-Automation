"""Undo correctness — the snapshot/before-image restore (DSN-gated).

Proves the panel's generic undo against the case most likely to break it: the
compound NEXT, which in one transition finishes an in-consult patient (DONE +
avg_consult_s learning + doctor_free_at + consults_done), SKIPS an absent front
patient (grace_until, skip_count), and serves the arrived one. Undo must revert
EVERY mutated row to its exact prior state — if the snapshot missed a single
column, the byte-identical assertion fails.

Everything runs through the real route path (POST /next, POST /undo with a real
JWT) so it exercises panel._read_snapshot / _restore exactly as production does.
The WhatsApp dispatcher is stubbed (no Graph API).
"""

from __future__ import annotations

import asyncio
import pathlib
import time as _time
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from app import db
from app.api import panel
from app.main import create_app
from tests.pg_util import DSN, fresh_pool

pytestmark = pytest.mark.skipif(not DSN, reason="DATABASE_URL_TEST not set")

_SEED = pathlib.Path(__file__).resolve().parents[2] / "supabase" / "seed.sql"


class _NullDispatcher:
    async def dispatch(self, now, result, *, allow_eta_shift: bool = False) -> None:
        return None


async def _prepare():
    pool = await fresh_pool()
    async with pool.acquire() as con:
        await con.execute(_SEED.read_text(encoding="utf-8"))
    db._pool = pool
    panel._dispatcher = _NullDispatcher()
    return pool


def _client():
    return AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://t")


async def _login(c) -> dict:
    r = await c.post("/panel/login", json={"slug": "demo", "pin": "123456"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


async def _clinic_id(pool):
    async with pool.acquire() as con:
        return await con.fetchval("select id from clinics where slug = 'demo'")


async def _open_session(pool, cid) -> str:
    now = datetime.now(UTC)
    async with pool.acquire() as con:
        return await con.fetchval(
            "insert into sessions (clinic_id, date, name, start_at, end_at, token_cap, status, "
            "doctor_free_at, avg_consult_s, consults_done) "
            "values ($1, (now() at time zone 'Asia/Kolkata')::date, 'morning', $2, $3, 40, "
            "'open', $4, 500, 1) returning id",
            cid,
            now - timedelta(minutes=5),
            now + timedelta(hours=6),
            now,
        )


async def _read_entries(pool, sid) -> list[dict]:
    """All entry rows for a session, ordered, minus the trigger-managed updated_at."""
    async with pool.acquire() as con:
        rows = await con.fetch(
            "select * from queue_entries where session_id = $1 order by token_number", sid
        )
    out = []
    for r in rows:
        d = dict(r)
        d.pop("updated_at", None)
        out.append(d)
    return out


async def _read_session(pool, sid) -> dict:
    async with pool.acquire() as con:
        r = await con.fetchrow("select * from sessions where id = $1", sid)
    d = dict(r)
    d.pop("updated_at", None)
    return d


# --------------------------------------------------------------------------- #
# the hard case: undo a compound NEXT
# --------------------------------------------------------------------------- #
def test_undo_compound_next_is_byte_identical():
    async def scenario():
        pool = await _prepare()
        try:
            cid = await _clinic_id(pool)
            sid = await _open_session(pool, cid)
            now = datetime.now(UTC)
            booked_at = now - timedelta(minutes=30)

            # 4 patients + entries: current in_consult, absent front, arrived, behind
            async with pool.acquire() as con:
                pids = []
                for i in range(4):
                    pids.append(
                        await con.fetchval(
                            "insert into patients (clinic_id, wa_number, display_name) "
                            "values ($1, $2, $3) returning id",
                            cid,
                            f"+9199000{i:05d}",
                            f"P{i}",
                        )
                    )

                async def add(tok, pid, prio, st, **cols):
                    keys = [
                        "session_id",
                        "clinic_id",
                        "patient_id",
                        "token_number",
                        "priority_time",
                        "booked_at",
                        "status",
                    ]
                    vals = [sid, cid, pid, tok, prio, booked_at, st]
                    for k, v in cols.items():
                        keys.append(k)
                        vals.append(v)
                    ph = ", ".join(f"${i + 1}" for i in range(len(vals)))
                    await con.execute(
                        f"insert into queue_entries ({', '.join(keys)}) values ({ph})", *vals
                    )

                await add(
                    1,
                    pids[0],
                    now - timedelta(minutes=20),
                    "in_consult",
                    consult_start=now - timedelta(minutes=8),
                    called_at=now - timedelta(minutes=8),
                )
                await add(2, pids[1], now, "booked")  # absent front → will be SKIPPED
                await add(
                    3,
                    pids[2],
                    now + timedelta(minutes=5),
                    "arrived",
                    arrived_at=now - timedelta(minutes=1),
                )  # will be SERVED
                await add(4, pids[3], now + timedelta(minutes=10), "booked")  # behind, untouched

            pre_entries = await _read_entries(pool, sid)
            pre_session = await _read_session(pool, sid)

            async with _client() as c:
                h = await _login(c)
                r = await c.post("/panel/next", json={"session_id": str(sid)}, headers=h)
                assert r.status_code == 200, r.text
                # sanity: the compound transition really happened
                mid = {e["token_number"]: e for e in await _read_entries(pool, sid)}
                assert mid[1]["status"] == "done"
                assert mid[2]["status"] == "skipped" and mid[2]["grace_until"] is not None
                assert mid[3]["status"] == "in_consult"
                mid_session = await _read_session(pool, sid)
                assert mid_session["consults_done"] == 2
                assert mid_session["avg_consult_s"] != pre_session["avg_consult_s"]

                u = await c.post("/panel/undo", headers=h)
                assert u.status_code == 200, u.text

            post_entries = await _read_entries(pool, sid)
            post_session = await _read_session(pool, sid)
            return pre_entries, post_entries, pre_session, post_session
        finally:
            panel._dispatcher = None
            db._pool = None
            await pool.close()

    pre_e, post_e, pre_s, post_s = asyncio.run(scenario())
    assert post_e == pre_e, "an entry column was not restored by undo"
    assert post_s == pre_s, "a session column was not restored by undo"


# --------------------------------------------------------------------------- #
# walk-in undo: a row created after the snapshot is deleted on restore
# --------------------------------------------------------------------------- #
def test_undo_walkin_deletes_created_row():
    async def scenario():
        pool = await _prepare()
        try:
            cid = await _clinic_id(pool)
            sid = await _open_session(pool, cid)
            async with _client() as c:
                h = await _login(c)
                s = await c.post(f"/panel/walkin?session_id={sid}", json={"name": "आशा"}, headers=h)
                assert s.status_code == 200, s.text
                after_add = await _count(pool, sid)
                u = await c.post("/panel/undo", headers=h)
                assert u.status_code == 200, u.text
                after_undo = await _count(pool, sid)
            return after_add, after_undo
        finally:
            panel._dispatcher = None
            db._pool = None
            await pool.close()

    after_add, after_undo = asyncio.run(scenario())
    assert after_add == 1
    assert after_undo == 0  # the created walk-in row was removed


# --------------------------------------------------------------------------- #
# cancel undo: a status flip is restored
# --------------------------------------------------------------------------- #
def test_undo_cancel_restores_status():
    async def scenario():
        pool = await _prepare()
        try:
            cid = await _clinic_id(pool)
            sid = await _open_session(pool, cid)
            async with _client() as c:
                h = await _login(c)
                s = (
                    await c.post(
                        f"/panel/walkin?session_id={sid}", json={"name": "Ravi"}, headers=h
                    )
                ).json()
                eid = s["entries"][0]["entry_id"]
                await c.post(f"/panel/entries/{eid}/cancel", headers=h)
                cancelled = await _status(pool, eid)
                await c.post("/panel/undo", headers=h)
                restored = await _status(pool, eid)
            return cancelled, restored
        finally:
            panel._dispatcher = None
            db._pool = None
            await pool.close()

    cancelled, restored = asyncio.run(scenario())
    assert cancelled == "cancelled"
    assert restored == "booked"


# --------------------------------------------------------------------------- #
# TTL + second-undo are no-ops
# --------------------------------------------------------------------------- #
def test_undo_after_ttl_is_noop():
    async def scenario():
        pool = await _prepare()
        try:
            cid = await _clinic_id(pool)
            sid = await _open_session(pool, cid)
            async with _client() as c:
                h = await _login(c)
                await c.post(f"/panel/walkin?session_id={sid}", json={"name": "Late"}, headers=h)
                # force the stored action past the 5s window
                panel._last_action[cid].at = _time.monotonic() - panel.UNDO_WINDOW_S - 1
                u = await c.post("/panel/undo", headers=h)
                count = await _count(pool, sid)
            return u.status_code, count
        finally:
            panel._dispatcher = None
            db._pool = None
            await pool.close()

    code, count = asyncio.run(scenario())
    assert code == 409  # expired → rejected
    assert count == 1  # nothing restored/deleted


def test_second_undo_within_ttl_is_noop():
    async def scenario():
        pool = await _prepare()
        try:
            cid = await _clinic_id(pool)
            sid = await _open_session(pool, cid)
            async with _client() as c:
                h = await _login(c)
                await c.post(f"/panel/walkin?session_id={sid}", json={"name": "Once"}, headers=h)
                first = await c.post("/panel/undo", headers=h)
                second = await c.post("/panel/undo", headers=h)
            return first.status_code, second.status_code
        finally:
            panel._dispatcher = None
            db._pool = None
            await pool.close()

    first, second = asyncio.run(scenario())
    assert first == 200
    assert second == 409  # action already consumed → no double-undo


async def _count(pool, sid) -> int:
    async with pool.acquire() as con:
        return await con.fetchval("select count(*) from queue_entries where session_id = $1", sid)


async def _status(pool, eid) -> str:
    async with pool.acquire() as con:
        return await con.fetchval("select status from queue_entries where id = $1", eid)
