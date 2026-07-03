"""Pydantic v2 models mirroring the DB tables (build doc §4) + status enums.

These are plain row DTOs — no ORM. `db.py` maps asyncpg records onto them.
All datetimes are UTC (timestamptz in DB).
"""

from __future__ import annotations

import datetime as dt
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #
class Status(str, Enum):
    """queue_entries.status — the token lifecycle + side exits."""

    booked = "booked"
    arrived = "arrived"
    called = "called"
    in_consult = "in_consult"
    done = "done"
    skipped = "skipped"
    expired = "expired"
    cancelled = "cancelled"


class SessionStatus(str, Enum):
    """sessions.status."""

    scheduled = "scheduled"
    open = "open"
    paused = "paused"
    closed = "closed"
    cancelled = "cancelled"


class Source(str, Enum):
    """queue_entries.source — how the token entered the queue."""

    whatsapp = "whatsapp"
    walkin = "walkin"
    panel = "panel"


class Direction(str, Enum):
    """wa_messages.direction."""

    inbound = "in"
    outbound = "out"


class ConversationState(str, Enum):
    """conversations.state — multi-turn booking flow."""

    idle = "idle"
    choosing_session = "choosing_session"
    choosing_time = "choosing_time"
    choosing_profile = "choosing_profile"
    confirm_cancel = "confirm_cancel"


# --------------------------------------------------------------------------- #
# Row models
# --------------------------------------------------------------------------- #
class Clinic(BaseModel):
    id: UUID
    slug: str
    pin_hash: str
    name: str
    doctor_name: str
    specialty: str | None = None
    address: str | None = None
    fee_inr: int | None = None
    wa_phone_number_id: str | None = None
    wa_display_number: str | None = None
    language: str = "hi"
    timezone: str = "Asia/Kolkata"
    settings: dict = Field(default_factory=dict)
    created_at: dt.datetime | None = None


class Timetable(BaseModel):
    id: UUID
    clinic_id: UUID
    weekday: int  # 0=Mon … 6=Sun
    name: str
    start_time: dt.time
    end_time: dt.time
    token_cap: int = 40


class Session(BaseModel):
    id: UUID
    clinic_id: UUID
    date: dt.date
    name: str
    start_at: dt.datetime
    end_at: dt.datetime
    token_cap: int
    status: SessionStatus = SessionStatus.scheduled
    doctor_free_at: dt.datetime | None = None
    avg_consult_s: int = 420
    consults_done: int = 0
    updated_at: dt.datetime | None = None


class Patient(BaseModel):
    id: UUID
    clinic_id: UUID
    wa_number: str
    profile_name: str = "self"
    display_name: str | None = None
    strikes: int = 0
    blocked_until: dt.datetime | None = None
    created_at: dt.datetime | None = None


class QueueEntry(BaseModel):
    id: UUID
    session_id: UUID
    clinic_id: UUID
    patient_id: UUID
    token_number: int
    priority_time: dt.datetime
    booked_at: dt.datetime
    status: Status = Status.booked
    source: Source = Source.whatsapp
    eta: dt.datetime | None = None
    report_time: dt.datetime | None = None
    arrived_at: dt.datetime | None = None
    called_at: dt.datetime | None = None
    consult_start: dt.datetime | None = None
    done_at: dt.datetime | None = None
    grace_until: dt.datetime | None = None
    skip_count: int = 0
    gap_offered_at: dt.datetime | None = None
    updated_at: dt.datetime | None = None


class Event(BaseModel):
    id: int
    clinic_id: UUID
    session_id: UUID | None = None
    entry_id: UUID | None = None
    type: str
    payload: dict = Field(default_factory=dict)
    created_at: dt.datetime | None = None


class WaMessage(BaseModel):
    id: int
    clinic_id: UUID | None = None
    wa_number: str
    direction: Direction
    wamid: str | None = None
    kind: str | None = None
    payload: dict | None = None
    created_at: dt.datetime | None = None


class Conversation(BaseModel):
    wa_number: str
    clinic_id: UUID
    state: ConversationState = ConversationState.idle
    context: dict = Field(default_factory=dict)
    updated_at: dt.datetime | None = None
