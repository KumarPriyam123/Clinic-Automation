"""Route-level smoke over the real app (DSN-gated).

Drives every mutating panel route once with a real JWT against a freshly
migrated + seeded schema, via httpx's in-process ASGI transport (no network, no
lifespan/scheduler). Each queue response is parsed back through the
``QueueSnapshot`` contract model (``extra='forbid'``) — a true validation of the
wire shape, not just a status check. Also pins the 401 paths.

The WhatsApp dispatcher is stubbed so no route makes a Graph API call.
"""

from __future__ import annotations

import asyncio
import pathlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app import db
from app.api import panel
from app.api.schemas import QueueSnapshot
from app.main import create_app
from tests.pg_util import DSN, fresh_pool

pytestmark = pytest.mark.skipif(not DSN, reason="DATABASE_URL_TEST not set")

_SEED = pathlib.Path(__file__).resolve().parents[2] / "supabase" / "seed.sql"


class _NullDispatcher:
    async def dispatch(self, now, result, *, allow_eta_shift: bool = False) -> None:
        return None


async def _prepare_pool():
    pool = await fresh_pool()
    async with pool.acquire() as con:
        await con.execute(_SEED.read_text(encoding="utf-8"))
    db._pool = pool
    panel._dispatcher = _NullDispatcher()  # never touch the Graph API in tests
    return pool


async def _make_today_session(pool) -> None:
    """Insert a scheduled session for the demo clinic dated today (IST)."""
    now = datetime.now(UTC)
    async with pool.acquire() as con:
        cid = await con.fetchval("select id from clinics where slug = 'demo'")
        await con.execute(
            "insert into sessions (clinic_id, date, name, start_at, end_at, token_cap, status) "
            "values ($1, (now() at time zone 'Asia/Kolkata')::date, 'morning', $2, $3, 40, "
            "'scheduled')",
            cid,
            now - timedelta(minutes=5),
            now + timedelta(hours=6),
        )


def _check(resp) -> QueueSnapshot:
    assert resp.status_code == 200, f"{resp.request.url} -> {resp.status_code}: {resp.text}"
    return QueueSnapshot.model_validate(resp.json())


def test_every_mutating_route_smoke():
    async def scenario():
        pool = await _prepare_pool()
        try:
            await _make_today_session(pool)
            transport = ASGITransport(app=create_app())
            async with AsyncClient(transport=transport, base_url="http://t") as c:
                # --- auth ---
                bad = await c.post("/panel/login", json={"slug": "demo", "pin": "000000"})
                assert bad.status_code == 401
                no_tok = await c.post("/panel/next", json={"session_id": str(uuid4())})
                assert no_tok.status_code == 401

                login = await c.post("/panel/login", json={"slug": "demo", "pin": "123456"})
                assert login.status_code == 200, login.text
                token = login.json()["token"]
                h = {"Authorization": f"Bearer {token}"}

                # --- reads ---
                today = _check(await c.get("/panel/session/today", headers=h))
                assert today.session is not None
                sid = today.session.id

                _check(await c.get(f"/panel/queue?session_id={sid}", headers=h))

                # --- session lifecycle: open it ---
                _check(await c.post("/panel/session/start", json={"session_id": sid}, headers=h))

                # --- book 2 entries via walk-in ---
                s = _check(
                    await c.post(f"/panel/walkin?session_id={sid}", json={"name": "आशा"}, headers=h)
                )
                s = _check(
                    await c.post(
                        f"/panel/walkin?session_id={sid}",
                        json={"name": "Ravi", "phone": "+919000000001"},
                        headers=h,
                    )
                )
                assert len(s.entries) == 2
                e1, e2 = s.entries[0].entry_id, s.entries[1].entry_id

                # --- per-entry + serving ---
                _check(await c.post(f"/panel/entries/{e1}/arrived", headers=h))
                served = _check(await c.post("/panel/next", json={"session_id": sid}, headers=h))
                assert served.now_serving is not None

                _check(await c.post(f"/panel/entries/{e2}/call-now", headers=h))
                _check(
                    await c.post(
                        f"/panel/session/delay?session_id={sid}", json={"minutes": 15}, headers=h
                    )
                )
                _check(await c.post("/panel/session/pause", json={"session_id": sid}, headers=h))
                _check(await c.post("/panel/session/resume", json={"session_id": sid}, headers=h))
                _check(
                    await c.post(
                        f"/panel/emergency?session_id={sid}", json={"name": "Emergency"}, headers=h
                    )
                )
                _check(await c.post(f"/panel/entries/{e2}/cancel", headers=h))
                _check(await c.post("/panel/undo", headers=h))

                # --- settings (separate contract: clinic + timetable) ---
                st = await c.put("/panel/settings", json={"name": "Demo Clinic 2"}, headers=h)
                assert st.status_code == 200
                assert "clinic" in st.json() and "timetable" in st.json()
                assert st.json()["clinic"]["name"] == "Demo Clinic 2"

                # --- close / cancel today ---
                _check(await c.post("/panel/session/close", json={"session_id": sid}, headers=h))
                _check(
                    await c.post("/panel/session/cancel-today", json={"session_id": sid}, headers=h)
                )
        finally:
            panel._dispatcher = None
            db._pool = None
            await pool.close()

    asyncio.run(scenario())
