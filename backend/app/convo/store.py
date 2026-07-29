"""ConvoBackend — everything the flow needs from storage + the engine, behind
one seam so the flow is testable without a DB.

MemConvo wraps an engine MemRepo (tests). PgConvo runs against asyncpg
(production). The flow never touches a repo directly: engine mutations go
through ``engine_call`` so the production path gets a real transaction/lock.
"""

from __future__ import annotations

import dataclasses as dc
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

from app.engine.results import EngineResult
from app.engine.state import (
    ACTIVE_STATUSES,
    RELEASED_STATUSES,
    STOP_ISSUING_BUFFER,
    WAITING_STATUSES,
    Entry,
    Patient,
)
from app.models import SessionStatus, Status
from app.wa.notify import Recipient, RecipientResolver

BOOKING_WINDOW_DAYS = 2


@dc.dataclass(slots=True)
class ClinicInfo:
    id: UUID
    language: str
    name: str
    doctor_name: str


@dc.dataclass(slots=True)
class SessionInfo:
    id: UUID
    name: str
    free: int


@dc.dataclass(slots=True)
class EntryInfo:
    entry_id: UUID
    session_id: UUID
    token_number: int
    ahead: int
    eta: datetime | None


@dc.dataclass(slots=True)
class ConvState:
    state: str = "idle"
    context: dict = dc.field(default_factory=dict)


class ConvoBackend(Protocol):
    async def clinic_for_phone(self, phone_number_id: str | None) -> ClinicInfo | None: ...
    async def get_conversation(self, wa_number: str, clinic_id: UUID) -> ConvState | None: ...
    async def save_conversation(self, wa_number: str, clinic_id: UUID, st: ConvState) -> None: ...
    async def bookable_sessions(self, clinic_id: UUID, now: datetime) -> list[SessionInfo]: ...
    async def get_or_create_patient(
        self, clinic_id: UUID, wa_number: str, profile_name: str
    ) -> UUID: ...
    async def active_entry(self, clinic_id: UUID, wa_number: str) -> EntryInfo | None: ...
    async def stop_delete(self, clinic_id: UUID, wa_number: str) -> None: ...
    async def engine_call(
        self, factory: Callable[[object], Awaitable[EngineResult]]
    ) -> EngineResult: ...
    def resolver(self) -> RecipientResolver: ...


# --------------------------------------------------------------------------- #
# In-memory backend (tests) — backed by an engine MemRepo
# --------------------------------------------------------------------------- #
class _MemResolver:
    def __init__(self, mem: MemConvo) -> None:
        self._mem = mem

    async def for_entry(self, entry_id: UUID) -> Recipient | None:
        e = self._mem.repo.entries.get(entry_id)
        if e is None:
            return None
        p = self._mem.repo.patients.get(e.patient_id)
        clinic = self._mem.clinics_by_id.get(e.clinic_id)
        return Recipient(
            wa_number=p.wa_number if p else "",
            name=p.profile_name if p and p.profile_name != "self" else "",
            lang=clinic.language if clinic else "hi",
            token_number=e.token_number,
            clinic_id=e.clinic_id,
            eta=e.eta,
            report=e.report_time,
        )


class MemConvo:
    def __init__(self) -> None:
        from app.engine.repo import MemRepo

        self.repo = MemRepo()
        self.clinics_by_phone: dict[str, ClinicInfo] = {}
        self.clinics_by_id: dict[UUID, ClinicInfo] = {}
        self.conversations: dict[tuple[str, UUID], ConvState] = {}

    # --- seeding helpers (tests) ---------------------------------------- #
    def add_clinic(self, phone_number_id: str, info: ClinicInfo) -> ClinicInfo:
        self.clinics_by_phone[phone_number_id] = info
        self.clinics_by_id[info.id] = info
        return info

    # --- ConvoBackend --------------------------------------------------- #
    async def clinic_for_phone(self, phone_number_id: str | None) -> ClinicInfo | None:
        return self.clinics_by_phone.get(phone_number_id or "")

    async def get_conversation(self, wa_number: str, clinic_id: UUID) -> ConvState | None:
        return self.conversations.get((wa_number, clinic_id))

    async def save_conversation(self, wa_number: str, clinic_id: UUID, st: ConvState) -> None:
        self.conversations[(wa_number, clinic_id)] = st

    async def bookable_sessions(self, clinic_id: UUID, now: datetime) -> list[SessionInfo]:
        out: list[SessionInfo] = []
        horizon = (now + timedelta(days=BOOKING_WINDOW_DAYS)).date()
        for s in self.repo.sessions.values():
            if s.clinic_id != clinic_id or s.status not in (
                SessionStatus.scheduled,
                SessionStatus.open,
            ):
                continue
            if s.end_at <= now + STOP_ISSUING_BUFFER or s.date > horizon:
                continue
            issued = sum(
                1
                for e in self.repo.entries.values()
                if e.session_id == s.id and e.status not in RELEASED_STATUSES
            )
            free = s.token_cap - issued
            if free > 0:
                out.append(SessionInfo(id=s.id, name=s.name, free=free))
        return out

    async def get_or_create_patient(
        self, clinic_id: UUID, wa_number: str, profile_name: str
    ) -> UUID:
        for p in self.repo.patients.values():
            if (
                p.clinic_id == clinic_id
                and p.wa_number == wa_number
                and p.profile_name == profile_name
            ):
                return p.id
        p = Patient(id=uuid4(), clinic_id=clinic_id, wa_number=wa_number, profile_name=profile_name)
        self.repo.add_patient(p)
        return p.id

    async def active_entry(self, clinic_id: UUID, wa_number: str) -> EntryInfo | None:
        nums = {
            p.id
            for p in self.repo.patients.values()
            if p.clinic_id == clinic_id and p.wa_number == wa_number
        }
        for e in self.repo.entries.values():
            if e.patient_id in nums and e.status in ACTIVE_STATUSES:
                ahead = self._ahead(e)
                return EntryInfo(e.id, e.session_id, e.token_number, ahead, e.eta)
        return None

    def _ahead(self, entry: Entry) -> int:
        waiting = sorted(
            (
                e
                for e in self.repo.entries.values()
                if e.session_id == entry.session_id and e.status in WAITING_STATUSES
            ),
            key=Entry.order_key,
        )
        return next((i for i, e in enumerate(waiting) if e.id == entry.id), 0)

    async def stop_delete(self, clinic_id: UUID, wa_number: str) -> None:
        pids = {
            p.id
            for p in self.repo.patients.values()
            if p.clinic_id == clinic_id and p.wa_number == wa_number
        }
        for e in list(self.repo.entries.values()):
            if e.patient_id in pids and e.status in ACTIVE_STATUSES:
                e.status = Status.cancelled
        for pid in pids:
            self.repo.patients.pop(pid, None)

    async def engine_call(self, factory) -> EngineResult:
        return await factory(self.repo)

    def resolver(self) -> RecipientResolver:
        return _MemResolver(self)


# --------------------------------------------------------------------------- #
# Production backend — asyncpg + PgRepo (used by the live webhook handler)
# --------------------------------------------------------------------------- #
_ACTIVE = ("booked", "arrived", "called", "in_consult", "skipped")
_RELEASED_VALUES = [s.value for s in RELEASED_STATUSES]


class PgConvo:
    """ConvoBackend over the shared db pool. engine_call runs inside a
    transaction so PgRepo.lock_session takes a real row lock."""

    async def clinic_for_phone(self, phone_number_id: str | None) -> ClinicInfo | None:
        from app import db

        if not phone_number_id:
            return None
        async with db.get_pool().acquire() as con:
            r = await con.fetchrow(
                "select id, language, name, doctor_name from clinics "
                "where wa_phone_number_id = $1",
                phone_number_id,
            )
        return ClinicInfo(r["id"], r["language"], r["name"], r["doctor_name"]) if r else None

    async def get_conversation(self, wa_number: str, clinic_id: UUID) -> ConvState | None:
        from app import db

        async with db.get_pool().acquire() as con:
            r = await con.fetchrow(
                "select state, context from conversations where wa_number = $1 and clinic_id = $2",
                wa_number,
                clinic_id,
            )
        return ConvState(state=r["state"], context=dict(r["context"])) if r else None

    async def save_conversation(self, wa_number: str, clinic_id: UUID, st: ConvState) -> None:
        from app import db

        async with db.get_pool().acquire() as con:
            await con.execute(
                """
                insert into conversations (wa_number, clinic_id, state, context, updated_at)
                values ($1, $2, $3, $4, now())
                on conflict (wa_number, clinic_id)
                do update set state = excluded.state, context = excluded.context,
                              updated_at = now()
                """,
                wa_number,
                clinic_id,
                st.state,
                st.context,
            )

    async def bookable_sessions(self, clinic_id: UUID, now: datetime) -> list[SessionInfo]:
        from app import db

        horizon = (now + timedelta(days=BOOKING_WINDOW_DAYS)).date()
        cutoff = now + STOP_ISSUING_BUFFER  # stop issuing 30 min before close
        async with db.get_pool().acquire() as con:
            rows = await con.fetch(
                """
                select s.id, s.name,
                       s.token_cap - coalesce(
                         count(q.*) filter (where q.status <> all($4::text[])), 0) as free
                from sessions s
                left join queue_entries q on q.session_id = s.id
                where s.clinic_id = $1 and s.status in ('scheduled','open')
                  and s.end_at > $2 and s.date <= $3
                group by s.id
                having s.token_cap - coalesce(
                         count(q.*) filter (where q.status <> all($4::text[])), 0) > 0
                order by s.date, s.start_at
                """,
                clinic_id,
                cutoff,
                horizon,
                _RELEASED_VALUES,
            )
        return [SessionInfo(r["id"], r["name"], r["free"]) for r in rows]

    async def get_or_create_patient(
        self, clinic_id: UUID, wa_number: str, profile_name: str
    ) -> UUID:
        from app import db

        async with db.get_pool().acquire() as con:
            pid = await con.fetchval(
                """
                insert into patients (clinic_id, wa_number, profile_name)
                values ($1, $2, $3)
                on conflict (clinic_id, wa_number, profile_name) do nothing
                returning id
                """,
                clinic_id,
                wa_number,
                profile_name,
            )
            if pid is None:
                pid = await con.fetchval(
                    "select id from patients where clinic_id = $1 and wa_number = $2 "
                    "and profile_name = $3",
                    clinic_id,
                    wa_number,
                    profile_name,
                )
        return pid

    async def active_entry(self, clinic_id: UUID, wa_number: str) -> EntryInfo | None:
        from app import db

        async with db.get_pool().acquire() as con:
            r = await con.fetchrow(
                f"""
                select q.id, q.session_id, q.token_number, q.eta
                from queue_entries q
                join patients p on p.id = q.patient_id
                where q.clinic_id = $1 and p.wa_number = $2
                  and q.status in {_ACTIVE}
                order by q.priority_time, q.booked_at
                limit 1
                """,
                clinic_id,
                wa_number,
            )
            if r is None:
                return None
            ahead = await con.fetchval(
                """
                with ord as (
                  select id, row_number() over (
                    order by next_up desc, priority_time, booked_at) - 1 as pos
                  from queue_entries
                  where session_id = $1 and status in ('booked','arrived')
                )
                select pos from ord where id = $2
                """,
                r["session_id"],
                r["id"],
            )
        return EntryInfo(r["id"], r["session_id"], r["token_number"], ahead or 0, r["eta"])

    async def stop_delete(self, clinic_id: UUID, wa_number: str) -> None:
        from app import db

        async with db.get_pool().acquire() as con, con.transaction():
            await con.execute(
                "delete from queue_entries where clinic_id = $1 and patient_id in "
                "(select id from patients where clinic_id = $1 and wa_number = $2)",
                clinic_id,
                wa_number,
            )
            await con.execute(
                "delete from patients where clinic_id = $1 and wa_number = $2",
                clinic_id,
                wa_number,
            )

    async def engine_call(self, factory) -> EngineResult:
        from app import db
        from app.engine.pg_repo import PgRepo

        async with db.get_pool().acquire() as con, con.transaction():
            return await factory(PgRepo(con))

    def resolver(self) -> RecipientResolver:
        from app.wa.resolver import PgRecipientResolver

        return PgRecipientResolver()
