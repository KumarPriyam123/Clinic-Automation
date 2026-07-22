"""WhatsApp Cloud API layer: webhook, send() gateway, template registry,
notification dispatcher. All patient-facing strings live in templates.py; all
sends go through Sender; the engine reaches WhatsApp only via
NotificationDispatcher.
"""

from app.wa.notify import NotificationDispatcher, Recipient, RecipientResolver
from app.wa.sender import Sender
from app.wa.store import InMemoryWaStore, PgWaStore, WaStore
from app.wa.templates import REGISTRY, Button, Template
from app.wa.webhook import (
    InboundMessage,
    build_router,
    normalize_inbound,
    set_message_handler,
    verify_signature,
)

__all__ = [
    "NotificationDispatcher",
    "Recipient",
    "RecipientResolver",
    "Sender",
    "WaStore",
    "InMemoryWaStore",
    "PgWaStore",
    "REGISTRY",
    "Button",
    "Template",
    "InboundMessage",
    "build_router",
    "normalize_inbound",
    "set_message_handler",
    "verify_signature",
]
