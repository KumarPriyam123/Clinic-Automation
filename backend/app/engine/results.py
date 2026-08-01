"""Engine outputs — pure data. Notifications are DATA, never sent from here.

A later phase (wa/notify.py dispatcher) turns NotificationIntent into WhatsApp
sends. The engine only decides *what* should be communicated, as records.
"""

from __future__ import annotations

import dataclasses as dc
from datetime import date as _date
from datetime import datetime
from enum import Enum
from uuid import UUID


class NotificationType(str, Enum):
    """Mirrors the wa/templates registry names (added in a later phase)."""

    booking_confirmed = "booking_confirmed"
    pre_arrival = "pre_arrival"
    three_away = "three_away"
    you_are_next = "you_are_next"
    skipped_grace = "skipped_grace"
    eta_shift = "eta_shift"
    delay_broadcast = "delay_broadcast"
    closed_broadcast = "closed_broadcast"
    gap_offer = "gap_offer"
    expired_rebook = "expired_rebook"
    doctor_digest = "doctor_digest"


@dc.dataclass(slots=True)
class NotificationIntent:
    type: NotificationType
    entry_id: UUID | None
    params: dict = dc.field(default_factory=dict)


@dc.dataclass(slots=True)
class SessionRef:
    """A session offered as an alternative when a booking overflows."""

    session_id: UUID
    name: str
    date: _date
    free: int
    #: Carried so the conversation can resolve a typed time against the
    #: alternative the patient picks, exactly as for a first-choice session.
    start_at: datetime | None = None
    end_at: datetime | None = None


@dc.dataclass(slots=True)
class OverflowSuggestion:
    """Returned by book() when the target session cannot take the token."""

    reason: str  # 'cap' | 'closed' | 'past_end'
    alternatives: list[SessionRef] = dc.field(default_factory=list)


#: A booking whose granted time differs from the requested one by more than
#: this is materially different and MUST be explained to the patient.
BOOKING_NOTICE_THRESHOLD_S = 600


@dc.dataclass(slots=True)
class BookingInfo:
    """What book() actually granted, versus what the patient asked for.

    Pure data. The engine states the facts (which day, which time, why it
    moved); ``convo/flow.py`` turns them into the patient's sentence. Without
    this the patient sees only a token and an ETA, and a clamped or next-day
    booking looks like the system is broken — the worst trust failure in the
    booking flow.
    """

    session_date: _date
    session_name: str
    session_start: datetime
    session_end: datetime
    granted: datetime
    requested: datetime | None = None
    #: 'session_start' | 'now' | None — set only when the move exceeds
    #: BOOKING_NOTICE_THRESHOLD_S, i.e. only when it is worth telling them.
    adjust_reason: str | None = None


@dc.dataclass(slots=True)
class EngineResult:
    """The single return type of every public engine transition."""

    changed_entries: list = dc.field(default_factory=list)
    notifications: list[NotificationIntent] = dc.field(default_factory=list)
    entry: object | None = None  # the created/served entry, when relevant
    overflow: OverflowSuggestion | None = None
    booking: BookingInfo | None = None  # set by book() on success

    def notify(self, type_: NotificationType, entry_id: UUID | None, **params: object) -> None:
        self.notifications.append(NotificationIntent(type_, entry_id, dict(params)))

    def touched(self, *entries: object) -> None:
        for e in entries:
            if e not in self.changed_entries:
                self.changed_entries.append(e)


def eta_moved_over(old: datetime | None, new: datetime, threshold_s: int = 600) -> bool:
    """True when an ETA changed by more than `threshold_s` (default 10 min)."""
    if old is None:
        return False
    return abs((new - old).total_seconds()) > threshold_s
