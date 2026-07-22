"""wa_messages access — inbound dedupe (by wamid), outbound log, and the last
inbound timestamp that drives the 24-hour window.

A protocol so the sender/webhook can be tested without a DB (InMemoryWaStore);
PgWaStore is the asyncpg-backed production impl.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

import asyncpg


class WaStore(Protocol):
    async def record_inbound(
        self,
        *,
        clinic_id: UUID | None,
        wa_number: str,
        wamid: str | None,
        kind: str | None,
        payload: dict | None,
        at: datetime,
    ) -> bool:
        """Insert-or-skip by wamid. Returns True if newly stored, False if dup."""
        ...

    async def record_outbound(
        self,
        *,
        clinic_id: UUID | None,
        wa_number: str,
        kind: str | None,
        payload: dict | None,
    ) -> None: ...

    async def last_inbound_at(self, wa_number: str) -> datetime | None: ...


class InMemoryWaStore:
    """Test double. Dedupes on wamid; tracks last inbound time per number."""

    def __init__(self) -> None:
        self.inbound: list[dict] = []
        self.outbound: list[dict] = []
        self._wamids: set[str] = set()

    async def record_inbound(self, *, clinic_id, wa_number, wamid, kind, payload, at) -> bool:
        if wamid is not None:
            if wamid in self._wamids:
                return False
            self._wamids.add(wamid)
        self.inbound.append(
            {
                "clinic_id": clinic_id,
                "wa_number": wa_number,
                "wamid": wamid,
                "kind": kind,
                "payload": payload,
                "at": at,
            }
        )
        return True

    async def record_outbound(self, *, clinic_id, wa_number, kind, payload) -> None:
        self.outbound.append(
            {"clinic_id": clinic_id, "wa_number": wa_number, "kind": kind, "payload": payload}
        )

    async def last_inbound_at(self, wa_number: str) -> datetime | None:
        times = [m["at"] for m in self.inbound if m["wa_number"] == wa_number]
        return max(times) if times else None


class PoolWaStore:
    """WaStore that acquires a connection from the shared db pool per call.
    Used by the webhook router, which has no ambient transaction."""

    async def record_inbound(self, **kw) -> bool:
        from app import db

        async with db.get_pool().acquire() as con:
            return await PgWaStore(con).record_inbound(**kw)

    async def record_outbound(self, **kw) -> None:
        from app import db

        async with db.get_pool().acquire() as con:
            await PgWaStore(con).record_outbound(**kw)

    async def last_inbound_at(self, wa_number: str) -> datetime | None:
        from app import db

        async with db.get_pool().acquire() as con:
            return await PgWaStore(con).last_inbound_at(wa_number)


class PgWaStore:
    """asyncpg-backed WaStore (production)."""

    def __init__(self, con: asyncpg.Connection) -> None:
        self._con = con

    async def record_inbound(self, *, clinic_id, wa_number, wamid, kind, payload, at) -> bool:
        row = await self._con.fetchrow(
            """
            insert into wa_messages (clinic_id, wa_number, direction, wamid, kind, payload)
            values ($1, $2, 'in', $3, $4, $5)
            on conflict (wamid) do nothing
            returning id
            """,
            clinic_id,
            wa_number,
            wamid,
            kind,
            payload or {},
        )
        return row is not None

    async def record_outbound(self, *, clinic_id, wa_number, kind, payload) -> None:
        await self._con.execute(
            """
            insert into wa_messages (clinic_id, wa_number, direction, kind, payload)
            values ($1, $2, 'out', $3, $4)
            """,
            clinic_id,
            wa_number,
            kind,
            payload or {},
        )

    async def last_inbound_at(self, wa_number: str) -> datetime | None:
        return await self._con.fetchval(
            "select max(created_at) from wa_messages where wa_number = $1 and direction = 'in'",
            wa_number,
        )
