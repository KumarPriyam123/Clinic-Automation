"""Rule 2 — ETA as a forward walk from the doctor's live clock. Pure.

    clock = max(now, session.doctor_free_at)
    for e in active entries ordered by (next_up, priority_time, booked_at):
        e.eta = max(clock, e.priority_time)          # never before the target
        e.report_time = e.eta - buffer
        clock = e.eta + avg_consult

No DB, no I/O — operates on in-memory Entry/SessionState objects.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.engine.results import eta_moved_over
from app.engine.state import (
    ETA_PING_THRESHOLD_S,
    WAITING_STATUSES,
    Entry,
    SessionState,
    buffer_seconds,
)


def recompute_etas(session: SessionState, entries: list[Entry], now: datetime) -> list[Entry]:
    """Recompute eta + report_time for every waiting entry, in place.

    Returns the entries whose eta moved by more than the ping threshold
    (10 min) — callers turn those into eta_shift notifications.
    """
    waiting = sorted(
        (e for e in entries if e.status in WAITING_STATUSES),
        key=Entry.order_key,
    )
    clock = max(now, session.doctor_free_at) if session.doctor_free_at else now
    buf = timedelta(seconds=buffer_seconds(session.avg_consult_s))
    avg = timedelta(seconds=session.avg_consult_s)

    moved: list[Entry] = []
    for e in waiting:
        new_eta = max(clock, e.priority_time)
        if eta_moved_over(e.eta, new_eta, ETA_PING_THRESHOLD_S):
            moved.append(e)
        e.eta = new_eta
        e.report_time = new_eta - buf
        clock = new_eta + avg
    return moved
