"""Pure, deterministic queue engine (CLAUDE.md §3 is law).

Imports nothing from wa/, convo/, llm, or web — enforced by
tests/test_engine_purity.py. Every public transition takes an injected `now`
and returns an EngineResult (changed entries + notification *data*).
"""

from app.engine.api import (
    accept_gap_offer,
    arrived_during_grace,
    book,
    call_now,
    cancel,
    cancel_session_today,
    close_session,
    delay_session,
    emergency_insert,
    gap_check,
    mark_arrived,
    next_patient,
    open_session,
    pause_session,
    recompute_etas_public,
    reopen_session,
    resume_session,
    sweep,
)
from app.engine.errors import (
    DuplicateActiveToken,
    EngineError,
    GraceExpired,
    InvalidTransition,
    SessionEnded,
)
from app.engine.results import (
    BookingInfo,
    EngineResult,
    NotificationIntent,
    NotificationType,
    OverflowSuggestion,
    SessionRef,
)
from app.engine.state import Entry, Patient, SessionState

__all__ = [
    "accept_gap_offer",
    "arrived_during_grace",
    "book",
    "call_now",
    "cancel",
    "cancel_session_today",
    "close_session",
    "delay_session",
    "emergency_insert",
    "gap_check",
    "mark_arrived",
    "next_patient",
    "open_session",
    "pause_session",
    "recompute_etas_public",
    "reopen_session",
    "resume_session",
    "sweep",
    "DuplicateActiveToken",
    "EngineError",
    "GraceExpired",
    "InvalidTransition",
    "SessionEnded",
    "BookingInfo",
    "EngineResult",
    "NotificationIntent",
    "NotificationType",
    "OverflowSuggestion",
    "SessionRef",
    "Entry",
    "Patient",
    "SessionState",
]
