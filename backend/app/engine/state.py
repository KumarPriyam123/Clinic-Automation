"""Engine domain objects (mutable dataclasses) + policy constants.

Deliberately separate from the DB pydantic models in app.models: the engine
needs in-place mutation and two runtime-only fields (`next_up`,
`last_notified_eta`) that repos map to/from their storage. Status/SessionStatus/
Source enums are reused from app.models so DB and engine never drift.
"""

from __future__ import annotations

import dataclasses as dc
from datetime import date as _date
from datetime import datetime, timedelta
from uuid import UUID

from app.models import SessionStatus, Source, Status

# --- policy (CLAUDE.md §3 defaults) -------------------------------------- #
GAP_THRESHOLD = timedelta(minutes=10)
GAP_OFFER_TTL = timedelta(minutes=5)
ETA_PING_THRESHOLD_S = 600  # notify only when ETA moves > 10 min

#: entries still "in play" for the one-active-token rule and the queue
ACTIVE_STATUSES = frozenset(
    {Status.booked, Status.arrived, Status.called, Status.in_consult, Status.skipped}
)
#: entries that occupy an ordering slot in the ETA walk / NEXT selection
WAITING_STATUSES = frozenset({Status.booked, Status.arrived})
#: statuses that consumed a token but freed it again (don't count vs cap)
RELEASED_STATUSES = frozenset({Status.cancelled, Status.expired})


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(v, hi))


def buffer_seconds(avg_consult_s: int) -> int:
    """report_time buffer = clamp(2 × avg, 10 min, 30 min)."""
    return int(clamp(2 * avg_consult_s, 600, 1800))


def grace_seconds(avg_consult_s: int) -> int:
    """Grace after a skip = max(10 min, 2 × avg)."""
    return int(max(600, 2 * avg_consult_s))


@dc.dataclass(slots=True)
class Patient:
    id: UUID
    clinic_id: UUID
    wa_number: str
    profile_name: str = "self"
    strikes: int = 0


@dc.dataclass(slots=True)
class SessionState:
    id: UUID
    clinic_id: UUID
    date: _date
    name: str
    start_at: datetime
    end_at: datetime
    token_cap: int
    status: SessionStatus = SessionStatus.scheduled
    doctor_free_at: datetime | None = None
    avg_consult_s: int = 420
    consults_done: int = 0


@dc.dataclass(slots=True)
class Entry:
    id: UUID
    session_id: UUID
    clinic_id: UUID
    patient_id: UUID
    token_number: int
    priority_time: datetime
    booked_at: datetime
    status: Status = Status.booked
    source: Source = Source.whatsapp
    eta: datetime | None = None
    report_time: datetime | None = None
    arrived_at: datetime | None = None
    called_at: datetime | None = None
    consult_start: datetime | None = None
    done_at: datetime | None = None
    grace_until: datetime | None = None
    skip_count: int = 0
    gap_offered_at: datetime | None = None
    next_up: bool = False
    last_notified_eta: datetime | None = None

    def order_key(self) -> tuple[int, datetime, datetime]:
        """Sort key for the queue: next_up first, then priority_time, then FIFO."""
        return (0 if self.next_up else 1, self.priority_time, self.booked_at)
