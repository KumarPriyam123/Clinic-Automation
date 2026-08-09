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
#: Never ask a remote patient to arrive more than this far before the time they
#: asked for. See GapPolicy.pull_forward_max.
GAP_PULL_FORWARD_MAX = timedelta(minutes=30)
ETA_PING_THRESHOLD_S = 600  # notify only when ETA moves > 10 min
STOP_ISSUING_BUFFER = timedelta(minutes=30)  # stop offering slots 30 min before close

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


@dc.dataclass(frozen=True, slots=True)
class GapPolicy:
    """Per-clinic gap-offer policy, from `clinics.settings` jsonb.

    Defaults match CLAUDE.md § policy defaults; a clinic may override any of
    them. Passed in rather than read from config so `app/engine/` stays pure
    and every value is injectable in tests.
    """

    #: `gap_offers` — master switch for the whole pull-forward feature.
    offers_enabled: bool = True
    #: `gap_pull_forward_max_min` — the horizon. Never offer a remote patient a
    #: slot more than this far before their own requested time.
    #:
    #: Measured against `priority_time`, NOT `eta`: the requested time is what
    #: the patient planned their day around, while the eta is a system artifact
    #: that drifts as the queue moves. Without this bound, a cancellation at
    #: 17:30 in a session that opened at 17:00 offered a 19:00 patient a 17:30
    #: slot — 90 minutes early.
    pull_forward_max: timedelta = GAP_PULL_FORWARD_MAX
    #: `gap_offer_expiry_min` — how long an unanswered offer stands.
    offer_ttl: timedelta = GAP_OFFER_TTL


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
    notified_pre_arrival_at: datetime | None = None
    notified_three_away_at: datetime | None = None

    def order_key(self) -> tuple[int, datetime, datetime]:
        """Sort key for the queue: next_up first, then priority_time, then FIFO."""
        return (0 if self.next_up else 1, self.priority_time, self.booked_at)
