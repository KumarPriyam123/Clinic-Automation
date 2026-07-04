"""Repository seam between the pure engine and storage.

The engine calls `repo.lock_session(...)` to obtain the session under a write
lock, then loads/mutates entries through the repo. The production PgRepo
(app.engine.pg_repo) implements lock_session with `SELECT ... FOR UPDATE`;
tests use the in-memory MemRepo below (no DB, fully deterministic).
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID, uuid4

from app.engine.results import SessionRef
from app.engine.state import ACTIVE_STATUSES, RELEASED_STATUSES, Entry, Patient, SessionState
from app.models import SessionStatus


class Repo(Protocol):
    async def lock_session(self, session_id: UUID) -> SessionState: ...
    async def get_session(self, session_id: UUID) -> SessionState: ...
    async def list_entries(self, session_id: UUID) -> list[Entry]: ...
    async def get_entry(self, entry_id: UUID) -> Entry: ...
    async def get_patient(self, patient_id: UUID) -> Patient: ...
    async def add_strike(self, patient_id: UUID) -> None: ...
    async def next_token_number(self, session_id: UUID) -> int: ...
    async def has_active_token(self, clinic_id: UUID, wa_number: str) -> bool: ...
    async def insert_entry(self, entry: Entry) -> None: ...
    async def save_entry(self, entry: Entry) -> None: ...
    async def save_session(self, session: SessionState) -> None: ...
    async def add_event(
        self,
        clinic_id: UUID,
        session_id: UUID | None,
        entry_id: UUID | None,
        type: str,
        payload: dict | None = None,
    ) -> None: ...
    async def future_sessions_with_space(
        self, clinic_id: UUID, after: datetime
    ) -> list[SessionRef]: ...
    async def open_sessions(self) -> list[SessionState]: ...


class MemRepo:
    """In-memory Repo for tests. Objects are shared by reference, so `save_*`
    is a no-op that still records the call for parity with PgRepo."""

    def __init__(self) -> None:
        self.sessions: dict[UUID, SessionState] = {}
        self.entries: dict[UUID, Entry] = {}
        self.patients: dict[UUID, Patient] = {}
        self.events: list[dict] = []

    # --- seed helpers (test-only convenience) ---------------------------- #
    def add_session(self, session: SessionState) -> SessionState:
        self.sessions[session.id] = session
        return session

    def add_patient(self, patient: Patient) -> Patient:
        self.patients[patient.id] = patient
        return patient

    # --- Repo protocol --------------------------------------------------- #
    async def lock_session(self, session_id: UUID) -> SessionState:
        return self.sessions[session_id]

    async def get_session(self, session_id: UUID) -> SessionState:
        return self.sessions[session_id]

    async def list_entries(self, session_id: UUID) -> list[Entry]:
        return [e for e in self.entries.values() if e.session_id == session_id]

    async def get_entry(self, entry_id: UUID) -> Entry:
        return self.entries[entry_id]

    async def get_patient(self, patient_id: UUID) -> Patient:
        return self.patients[patient_id]

    async def add_strike(self, patient_id: UUID) -> None:
        self.patients[patient_id].strikes += 1

    async def next_token_number(self, session_id: UUID) -> int:
        used = [e.token_number for e in self.entries.values() if e.session_id == session_id]
        return (max(used) + 1) if used else 1

    async def has_active_token(self, clinic_id: UUID, wa_number: str) -> bool:
        for e in self.entries.values():
            if e.status not in ACTIVE_STATUSES:
                continue
            p = self.patients.get(e.patient_id)
            if p and p.clinic_id == clinic_id and p.wa_number == wa_number:
                return True
        return False

    async def insert_entry(self, entry: Entry) -> None:
        self.entries[entry.id] = entry

    async def save_entry(self, entry: Entry) -> None:  # no-op: shared reference
        self.entries[entry.id] = entry

    async def save_session(self, session: SessionState) -> None:  # no-op
        self.sessions[session.id] = session

    async def add_event(
        self,
        clinic_id: UUID,
        session_id: UUID | None,
        entry_id: UUID | None,
        type: str,
        payload: dict | None = None,
    ) -> None:
        self.events.append(
            {
                "id": uuid4(),
                "clinic_id": clinic_id,
                "session_id": session_id,
                "entry_id": entry_id,
                "type": type,
                "payload": payload or {},
            }
        )

    async def future_sessions_with_space(
        self, clinic_id: UUID, after: datetime
    ) -> list[SessionRef]:
        out: list[SessionRef] = []
        for s in self.sessions.values():
            if s.clinic_id != clinic_id:
                continue
            if s.status not in (SessionStatus.scheduled, SessionStatus.open):
                continue
            if s.end_at <= after:
                continue
            issued = sum(
                1
                for e in self.entries.values()
                if e.session_id == s.id and e.status not in RELEASED_STATUSES
            )
            free = s.token_cap - issued
            if free > 0:
                out.append(SessionRef(session_id=s.id, name=s.name, date=s.date, free=free))
        return sorted(out, key=lambda r: r.date)

    async def open_sessions(self) -> list[SessionState]:
        return [s for s in self.sessions.values() if s.status == SessionStatus.open]
