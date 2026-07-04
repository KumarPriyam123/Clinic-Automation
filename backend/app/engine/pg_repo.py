"""Production Repo backed by asyncpg. This is the only place the engine's
row-locking becomes a real ``SELECT ... FOR UPDATE``.

Construct with an asyncpg connection already inside a transaction; the lock is
held until that transaction commits/rolls back:

    async with pool.acquire() as con:
        async with con.transaction():
            repo = PgRepo(con)
            await engine.next_patient(repo, now, session_id)

Not exercised by the FakeClock unit tests (they use MemRepo); covered by
integration tests that provide DATABASE_URL_TEST.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

import asyncpg

from app.engine.results import SessionRef
from app.engine.state import RELEASED_STATUSES, Entry, Patient, SessionState
from app.models import SessionStatus, Source, Status

_ACTIVE_SQL = "('booked','arrived','called','in_consult','skipped')"
_RELEASED = tuple(s.value for s in RELEASED_STATUSES)


def _entry(row: asyncpg.Record) -> Entry:
    return Entry(
        id=row["id"],
        session_id=row["session_id"],
        clinic_id=row["clinic_id"],
        patient_id=row["patient_id"],
        token_number=row["token_number"],
        priority_time=row["priority_time"],
        booked_at=row["booked_at"],
        status=Status(row["status"]),
        source=Source(row["source"]),
        eta=row["eta"],
        report_time=row["report_time"],
        arrived_at=row["arrived_at"],
        called_at=row["called_at"],
        consult_start=row["consult_start"],
        done_at=row["done_at"],
        grace_until=row["grace_until"],
        skip_count=row["skip_count"],
        gap_offered_at=row["gap_offered_at"],
        next_up=row["next_up"],
        last_notified_eta=row["last_notified_eta"],
    )


def _session(row: asyncpg.Record) -> SessionState:
    return SessionState(
        id=row["id"],
        clinic_id=row["clinic_id"],
        date=row["date"],
        name=row["name"],
        start_at=row["start_at"],
        end_at=row["end_at"],
        token_cap=row["token_cap"],
        status=SessionStatus(row["status"]),
        doctor_free_at=row["doctor_free_at"],
        avg_consult_s=row["avg_consult_s"],
        consults_done=row["consults_done"],
    )


class PgRepo:
    def __init__(self, con: asyncpg.Connection) -> None:
        self._con = con

    async def lock_session(self, session_id: UUID) -> SessionState:
        row = await self._con.fetchrow(
            "select * from sessions where id = $1 for update", session_id
        )
        return _session(row)

    async def get_session(self, session_id: UUID) -> SessionState:
        return _session(
            await self._con.fetchrow("select * from sessions where id = $1", session_id)
        )

    async def list_entries(self, session_id: UUID) -> list[Entry]:
        rows = await self._con.fetch(
            "select * from queue_entries where session_id = $1 order by priority_time, booked_at",
            session_id,
        )
        return [_entry(r) for r in rows]

    async def get_entry(self, entry_id: UUID) -> Entry:
        return _entry(
            await self._con.fetchrow("select * from queue_entries where id = $1", entry_id)
        )

    async def get_patient(self, patient_id: UUID) -> Patient:
        r = await self._con.fetchrow("select * from patients where id = $1", patient_id)
        return Patient(
            id=r["id"],
            clinic_id=r["clinic_id"],
            wa_number=r["wa_number"],
            profile_name=r["profile_name"],
            strikes=r["strikes"],
        )

    async def add_strike(self, patient_id: UUID) -> None:
        await self._con.execute(
            "update patients set strikes = strikes + 1 where id = $1", patient_id
        )

    async def next_token_number(self, session_id: UUID) -> int:
        n = await self._con.fetchval(
            "select coalesce(max(token_number), 0) + 1 from queue_entries where session_id = $1",
            session_id,
        )
        return int(n)

    async def has_active_token(self, clinic_id: UUID, wa_number: str) -> bool:
        return bool(
            await self._con.fetchval(
                f"""
                select exists (
                  select 1
                  from queue_entries q
                  join patients p on p.id = q.patient_id
                  where q.clinic_id = $1 and p.wa_number = $2
                    and q.status in {_ACTIVE_SQL}
                )
                """,
                clinic_id,
                wa_number,
            )
        )

    async def insert_entry(self, e: Entry) -> None:
        await self._con.execute(
            """
            insert into queue_entries
              (id, session_id, clinic_id, patient_id, token_number, priority_time,
               booked_at, status, source, eta, report_time, arrived_at, called_at,
               consult_start, done_at, grace_until, skip_count, gap_offered_at,
               next_up, last_notified_eta)
            values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20)
            """,
            e.id,
            e.session_id,
            e.clinic_id,
            e.patient_id,
            e.token_number,
            e.priority_time,
            e.booked_at,
            e.status.value,
            e.source.value,
            e.eta,
            e.report_time,
            e.arrived_at,
            e.called_at,
            e.consult_start,
            e.done_at,
            e.grace_until,
            e.skip_count,
            e.gap_offered_at,
            e.next_up,
            e.last_notified_eta,
        )

    async def save_entry(self, e: Entry) -> None:
        await self._con.execute(
            """
            update queue_entries set
              priority_time=$2, status=$3, source=$4, eta=$5, report_time=$6, arrived_at=$7,
              called_at=$8, consult_start=$9, done_at=$10, grace_until=$11, skip_count=$12,
              gap_offered_at=$13, next_up=$14, last_notified_eta=$15
            where id=$1
            """,
            e.id,
            e.priority_time,
            e.status.value,
            e.source.value,
            e.eta,
            e.report_time,
            e.arrived_at,
            e.called_at,
            e.consult_start,
            e.done_at,
            e.grace_until,
            e.skip_count,
            e.gap_offered_at,
            e.next_up,
            e.last_notified_eta,
        )

    async def save_session(self, s: SessionState) -> None:
        await self._con.execute(
            """
            update sessions set
              status=$2, doctor_free_at=$3, avg_consult_s=$4, consults_done=$5
            where id=$1
            """,
            s.id,
            s.status.value,
            s.doctor_free_at,
            s.avg_consult_s,
            s.consults_done,
        )

    async def add_event(
        self,
        clinic_id: UUID,
        session_id: UUID | None,
        entry_id: UUID | None,
        type: str,
        payload: dict | None = None,
    ) -> None:
        await self._con.execute(
            """
            insert into events (clinic_id, session_id, entry_id, type, payload)
            values ($1, $2, $3, $4, $5)
            """,
            clinic_id,
            session_id,
            entry_id,
            type,
            payload or {},
        )

    async def future_sessions_with_space(
        self, clinic_id: UUID, after: datetime
    ) -> list[SessionRef]:
        rows = await self._con.fetch(
            """
            select s.id, s.name, s.date, s.token_cap,
                   coalesce(count(q.*) filter (where q.status <> all($3::text[])), 0) as issued
            from sessions s
            left join queue_entries q on q.session_id = s.id
            where s.clinic_id = $1
              and s.status in ('scheduled','open')
              and s.end_at > $2
            group by s.id
            having s.token_cap - coalesce(
                     count(q.*) filter (where q.status <> all($3::text[])), 0) > 0
            order by s.date
            """,
            clinic_id,
            after,
            list(_RELEASED),
        )
        return [
            SessionRef(
                session_id=r["id"],
                name=r["name"],
                date=r["date"],
                free=r["token_cap"] - r["issued"],
            )
            for r in rows
        ]

    async def open_sessions(self) -> list[SessionState]:
        rows = await self._con.fetch("select * from sessions where status = 'open' for update")
        return [_session(r) for r in rows]
