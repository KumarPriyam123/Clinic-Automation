"""JobBackend — storage + engine access the scheduler jobs need, behind one
seam so every job is FakeClock-testable without a DB (MemJobs). PgJobs is the
asyncpg production impl.
"""

from __future__ import annotations

import dataclasses as dc
from collections.abc import Awaitable, Callable
from datetime import date as _date
from datetime import datetime, time, timedelta
from typing import Protocol
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from app.engine.results import EngineResult
from app.engine.state import Entry, SessionState
from app.models import SessionStatus, Source, Status
from app.wa.notify import Recipient, RecipientResolver

IST = ZoneInfo("Asia/Kolkata")
DEFAULT_AVG_S = 420


@dc.dataclass(slots=True)
class ClinicRow:
    id: UUID
    language: str
    name: str
    doctor_name: str
    wa_number: str | None


@dc.dataclass(slots=True)
class TimetableRow:
    clinic_id: UUID
    weekday: int  # 0=Mon
    name: str
    start_time: time
    end_time: time
    token_cap: int


@dc.dataclass(slots=True)
class DigestStats:
    seen: int
    no_shows: int
    avg_min: int
    wa_bookings: int
    tomorrow_morning: int


def _at(day: _date, t: time) -> datetime:
    """A wall-clock IST time on `day`, as a UTC instant."""
    return datetime.combine(day, t, tzinfo=IST).astimezone(ZoneInfo("UTC"))


class JobBackend(Protocol):
    async def engine_call(
        self, factory: Callable[[object], Awaitable[EngineResult]]
    ) -> EngineResult: ...
    async def open_sessions(self) -> list[SessionState]: ...
    async def sessions_to_open(self, now: datetime) -> list[UUID]: ...
    async def sessions_to_close(self, now: datetime) -> list[UUID]: ...
    async def list_entries(self, session_id: UUID) -> list[Entry]: ...
    async def save_entry(self, entry: Entry) -> None: ...
    async def stamp_sessions(self, now: datetime) -> list[UUID]: ...
    async def clinics(self) -> list[ClinicRow]: ...
    async def digest_stats(self, clinic_id: UUID, now: datetime) -> DigestStats: ...
    def resolver(self) -> RecipientResolver: ...


# --------------------------------------------------------------------------- #
# In-memory backend (tests) — over an engine MemRepo
# --------------------------------------------------------------------------- #
class _MemJobResolver:
    def __init__(self, mem: MemJobs) -> None:
        self._mem = mem

    async def for_entry(self, entry_id: UUID) -> Recipient | None:
        e = self._mem.repo.entries.get(entry_id)
        if e is None:
            return None
        p = self._mem.repo.patients.get(e.patient_id)
        clinic = self._mem.clinics_by_id.get(e.clinic_id)
        return Recipient(
            wa_number=p.wa_number if p else "",
            name="" if not p or p.profile_name == "self" else p.profile_name,
            lang=clinic.language if clinic else "hi",
            token_number=e.token_number,
            clinic_id=e.clinic_id,
            eta=e.eta,
            report=e.report_time,
        )


class MemJobs:
    def __init__(self) -> None:
        from app.engine.repo import MemRepo

        self.repo = MemRepo()
        self.clinics_by_id: dict[UUID, ClinicRow] = {}
        self.timetable: list[TimetableRow] = []

    def add_clinic(self, c: ClinicRow) -> ClinicRow:
        self.clinics_by_id[c.id] = c
        return c

    async def engine_call(self, factory) -> EngineResult:
        return await factory(self.repo)

    async def open_sessions(self) -> list[SessionState]:
        return [s for s in self.repo.sessions.values() if s.status == SessionStatus.open]

    async def sessions_to_open(self, now: datetime) -> list[UUID]:
        return [
            s.id
            for s in self.repo.sessions.values()
            if s.status == SessionStatus.scheduled and s.start_at <= now < s.end_at
        ]

    async def sessions_to_close(self, now: datetime) -> list[UUID]:
        return [
            s.id
            for s in self.repo.sessions.values()
            if s.status in (SessionStatus.open, SessionStatus.paused) and s.end_at <= now
        ]

    async def list_entries(self, session_id: UUID) -> list[Entry]:
        return [e for e in self.repo.entries.values() if e.session_id == session_id]

    async def save_entry(self, entry: Entry) -> None:
        self.repo.entries[entry.id] = entry

    async def stamp_sessions(self, now: datetime) -> list[UUID]:
        created: list[UUID] = []
        today = now.astimezone(IST).date()
        for offset in range(3):  # today + 2
            day = today + timedelta(days=offset)
            for tt in self.timetable:
                if tt.weekday != day.weekday():
                    continue
                exists = any(
                    s.clinic_id == tt.clinic_id and s.date == day and s.name == tt.name
                    for s in self.repo.sessions.values()
                )
                if exists:
                    continue
                s = SessionState(
                    id=uuid4(),
                    clinic_id=tt.clinic_id,
                    date=day,
                    name=tt.name,
                    start_at=_at(day, tt.start_time),
                    end_at=_at(day, tt.end_time),
                    token_cap=tt.token_cap,
                    status=SessionStatus.scheduled,
                    avg_consult_s=DEFAULT_AVG_S,
                )
                self.repo.add_session(s)
                created.append(s.id)
        return created

    async def clinics(self) -> list[ClinicRow]:
        return list(self.clinics_by_id.values())

    async def digest_stats(self, clinic_id: UUID, now: datetime) -> DigestStats:
        today = now.astimezone(IST).date()
        tomorrow = today + timedelta(days=1)
        today_sessions = {
            s.id: s
            for s in self.repo.sessions.values()
            if s.clinic_id == clinic_id and s.date == today
        }
        seen = no_shows = wa_bookings = 0
        for e in self.repo.entries.values():
            if e.session_id not in today_sessions:
                continue
            if e.status == Status.done:
                seen += 1
            elif e.status == Status.expired:
                no_shows += 1
            if e.source == Source.whatsapp:
                wa_bookings += 1
        avg_s = next((s.avg_consult_s for s in today_sessions.values()), DEFAULT_AVG_S)
        tomorrow_morning = sum(
            1
            for e in self.repo.entries.values()
            for s in self.repo.sessions.values()
            if s.id == e.session_id
            and s.clinic_id == clinic_id
            and s.date == tomorrow
            and s.name == "morning"
            and e.status not in (Status.cancelled, Status.expired)
        )
        return DigestStats(seen, no_shows, round(avg_s / 60), wa_bookings, tomorrow_morning)

    def resolver(self) -> RecipientResolver:
        return _MemJobResolver(self)


# --------------------------------------------------------------------------- #
# Production backend (asyncpg)
# --------------------------------------------------------------------------- #
class PgJobs:
    async def engine_call(self, factory) -> EngineResult:
        from app import db
        from app.engine.pg_repo import PgRepo

        async with db.get_pool().acquire() as con, con.transaction():
            return await factory(PgRepo(con))

    async def _pool(self):
        from app import db

        return db.get_pool()

    async def open_sessions(self) -> list[SessionState]:
        from app.engine.pg_repo import _session

        pool = await self._pool()
        async with pool.acquire() as con:
            rows = await con.fetch("select * from sessions where status = 'open'")
        return [_session(r) for r in rows]

    async def sessions_to_open(self, now: datetime) -> list[UUID]:
        pool = await self._pool()
        async with pool.acquire() as con:
            rows = await con.fetch(
                "select id from sessions where status = 'scheduled' "
                "and start_at <= $1 and end_at > $1",
                now,
            )
        return [r["id"] for r in rows]

    async def sessions_to_close(self, now: datetime) -> list[UUID]:
        pool = await self._pool()
        async with pool.acquire() as con:
            rows = await con.fetch(
                "select id from sessions where status in ('open','paused') and end_at <= $1",
                now,
            )
        return [r["id"] for r in rows]

    async def list_entries(self, session_id: UUID) -> list[Entry]:
        from app.engine.pg_repo import _entry

        pool = await self._pool()
        async with pool.acquire() as con:
            rows = await con.fetch("select * from queue_entries where session_id = $1", session_id)
        return [_entry(r) for r in rows]

    async def save_entry(self, entry: Entry) -> None:
        from app.engine.pg_repo import PgRepo

        pool = await self._pool()
        async with pool.acquire() as con:
            await PgRepo(con).save_entry(entry)

    async def stamp_sessions(self, now: datetime) -> list[UUID]:
        pool = await self._pool()
        today = now.astimezone(IST).date()
        created: list[UUID] = []
        async with pool.acquire() as con:
            for offset in range(3):
                day = today + timedelta(days=offset)
                rows = await con.fetch(
                    "select clinic_id, name, start_time, end_time, token_cap "
                    "from timetable where weekday = $1",
                    day.weekday(),
                )
                for tt in rows:
                    sid = await con.fetchval(
                        """
                        insert into sessions
                          (clinic_id, date, name, start_at, end_at, token_cap, status)
                        values ($1, $2, $3, $4, $5, $6, 'scheduled')
                        on conflict (clinic_id, date, name) do nothing
                        returning id
                        """,
                        tt["clinic_id"],
                        day,
                        tt["name"],
                        _at(day, tt["start_time"]),
                        _at(day, tt["end_time"]),
                        tt["token_cap"],
                    )
                    if sid:
                        created.append(sid)
        return created

    async def clinics(self) -> list[ClinicRow]:
        pool = await self._pool()
        async with pool.acquire() as con:
            rows = await con.fetch(
                "select id, language, name, doctor_name, wa_display_number from clinics"
            )
        return [
            ClinicRow(r["id"], r["language"], r["name"], r["doctor_name"], r["wa_display_number"])
            for r in rows
        ]

    async def digest_stats(self, clinic_id: UUID, now: datetime) -> DigestStats:
        pool = await self._pool()
        today = now.astimezone(IST).date()
        tomorrow = today + timedelta(days=1)
        async with pool.acquire() as con:
            row = await con.fetchrow(
                """
                select
                  count(*) filter (where q.status = 'done') as seen,
                  count(*) filter (where q.status = 'expired') as no_shows,
                  count(*) filter (where q.source = 'whatsapp') as wa_bookings,
                  coalesce(round(avg(s.avg_consult_s) / 60.0), 7) as avg_min
                from sessions s
                left join queue_entries q on q.session_id = s.id
                where s.clinic_id = $1 and s.date = $2
                """,
                clinic_id,
                today,
            )
            tomorrow_morning = await con.fetchval(
                """
                select count(*) from queue_entries q
                join sessions s on s.id = q.session_id
                where s.clinic_id = $1 and s.date = $2 and s.name = 'morning'
                  and q.status not in ('cancelled','expired')
                """,
                clinic_id,
                tomorrow,
            )
        return DigestStats(
            seen=row["seen"] or 0,
            no_shows=row["no_shows"] or 0,
            avg_min=int(row["avg_min"] or 7),
            wa_bookings=row["wa_bookings"] or 0,
            tomorrow_morning=tomorrow_morning or 0,
        )

    def resolver(self) -> RecipientResolver:
        from app.wa.resolver import PgRecipientResolver

        return PgRecipientResolver()
