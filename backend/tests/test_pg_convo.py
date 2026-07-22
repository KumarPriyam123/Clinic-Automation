"""Part 1 DoD, DB-backed: drive the flow through PgConvo against real PG and
prove the booking + arrived transitions land in queue_entries.

Skips when DATABASE_URL_TEST is unset. LLM + Graph API are mocked; only the
Postgres conversation/engine path is exercised for real.
"""

from __future__ import annotations

import asyncio
import pathlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app import db
from app.convo.flow import Flow
from app.convo.llm import Intent
from app.convo.store import PgConvo
from app.wa.sender import Sender
from app.wa.store import InMemoryWaStore
from app.wa.webhook import InboundMessage
from tests.pg_util import DSN

pytestmark = pytest.mark.skipif(not DSN, reason="DATABASE_URL_TEST not set")

_MIGRATIONS = sorted(
    (pathlib.Path(__file__).resolve().parents[2] / "supabase" / "migrations").glob("*.sql")
)
WA = "+919000000042"
PHONE = "123"


def now0():
    return datetime(2026, 7, 5, 9, 0, tzinfo=UTC)


class Parse:
    def __init__(self):
        self.q = []

    def push(self, **kw):
        self.q.append(Intent(**kw))

    async def __call__(self, text, ctx):
        return self.q.pop(0) if self.q else Intent(intent="other", confidence=0.0)


class FakeSender(Sender):
    async def _post(self, payload):
        return {"messaging_product": "whatsapp", "messages": [{"id": "wamid.OUT"}]}


async def _seed_and_pool():
    await db.init_pool(DSN)
    pool = db.get_pool()
    async with pool.acquire() as con:
        await con.execute("drop schema public cascade; create schema public;")
        for m in _MIGRATIONS:
            await con.execute(m.read_text(encoding="utf-8"))
        cid = await con.fetchval(
            "insert into clinics (slug, pin_hash, name, doctor_name, language, "
            "wa_phone_number_id) values ($1,'h','C','Dr','hi',$2) returning id",
            f"c{uuid4().hex[:8]}",
            PHONE,
        )
        now = now0()
        sid = await con.fetchval(
            "insert into sessions (clinic_id, date, name, start_at, end_at, token_cap, "
            "status, doctor_free_at, avg_consult_s) "
            "values ($1,$2,'morning',$3,$4,40,'open',$5,600) returning id",
            cid,
            now.date(),
            now,
            now + timedelta(hours=6),
            now,
        )
    return sid


def test_book_then_arrived_hits_db():
    async def scenario():
        sid = await _seed_and_pool()
        store = InMemoryWaStore()
        sender = FakeSender(store, token="t", phone_number_id=PHONE, backoff_base=0)
        parse = Parse()
        flow = Flow(PgConvo(), sender, parse)
        now = now0()

        async def inbound(text=None, button_id=None):
            kind = "button_reply" if button_id else "text"
            await store.record_inbound(
                clinic_id=None, wa_number=WA, wamid=uuid4().hex, kind=kind, payload={}, at=now
            )
            await flow.handle(
                now,
                InboundMessage(
                    wa_number=WA,
                    kind=kind,
                    text=text,
                    button_id=button_id,
                    timestamp=now,
                    wamid="x",
                    phone_number_id=PHONE,
                ),
            )

        parse.push(intent="greeting", confidence=0.95)
        await inbound(text="namaste")
        await inbound(button_id=f"sess:{sid}")
        await inbound(button_id="time:asap")
        await inbound(button_id="profile:self")

        pool = db.get_pool()
        async with pool.acquire() as con:
            booked = await con.fetchrow(
                "select q.id, q.status, q.token_number from queue_entries q "
                "join patients p on p.id = q.patient_id where p.wa_number = $1",
                WA,
            )
            entry_id, status_after_book = booked["id"], booked["status"]

            # tap the Arrived button
            await store.record_inbound(
                clinic_id=None,
                wa_number=WA,
                wamid=uuid4().hex,
                kind="button_reply",
                payload={},
                at=now,
            )
            await flow.handle(
                now,
                InboundMessage(
                    wa_number=WA,
                    kind="button_reply",
                    text=None,
                    button_id=f"arrived:{entry_id}",
                    timestamp=now,
                    wamid="x",
                    phone_number_id=PHONE,
                ),
            )
            status_after_arrived = await con.fetchval(
                "select status from queue_entries where id = $1", entry_id
            )
        await db.close_pool()
        return status_after_book, status_after_arrived

    booked, arrived = asyncio.run(scenario())
    assert booked == "booked"
    assert arrived == "arrived"
