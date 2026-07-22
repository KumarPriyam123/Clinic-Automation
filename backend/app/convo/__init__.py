"""Conversation layer: LLM intent parser + buttons-first state machine.

The webhook hands an InboundMessage to Flow.handle, which drives the booking
state machine, calls the pure engine through the backend seam, and replies via
the WhatsApp sender. The LLM only classifies free text — it never mutates state
or generates medical content.
"""

from app.convo.flow import Flow
from app.convo.llm import Intent, parse
from app.convo.store import (
    ClinicInfo,
    ConvoBackend,
    ConvState,
    EntryInfo,
    MemConvo,
    PgConvo,
    SessionInfo,
)

__all__ = [
    "Flow",
    "Intent",
    "parse",
    "ClinicInfo",
    "ConvoBackend",
    "ConvState",
    "EntryInfo",
    "MemConvo",
    "PgConvo",
    "SessionInfo",
]
