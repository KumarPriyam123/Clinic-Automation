"""Observability: structured logging (with PII/secret redaction) + in-process
counters the /metrics endpoint reads.

Rules (DEPLOY.md): never log a full patient phone number (mask to last 4) and
never log the WhatsApp token. ``configure_logging`` installs a redaction filter
that enforces the token rule globally; callers use ``mask_phone`` for numbers.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime

from app.config import settings

log = logging.getLogger("clinicq")

# --- redaction ---------------------------------------------------------------
_PHONE_RE = re.compile(r"(\+?\d[\d\-\s]{5,})(\d{4})")


def mask_phone(value: str | None) -> str:
    """'+919876543210' -> '+91••••3210'. Safe to log."""
    if not value:
        return "—"
    digits = re.sub(r"\D", "", value)
    if len(digits) < 4:
        return "••••"
    return f"••••{digits[-4:]}"


class _RedactFilter(logging.Filter):
    """Scrub the WA token and any phone-shaped run from formatted log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        if settings.WA_TOKEN and settings.WA_TOKEN in msg:
            msg = msg.replace(settings.WA_TOKEN, "***WA_TOKEN***")
        msg = _PHONE_RE.sub(lambda m: f"{m.group(1)[:3]}••••{m.group(2)}", msg)
        record.msg = msg
        record.args = ()
        return True


def configure_logging() -> None:
    """Idempotent root logging setup: single stream handler, redaction filter."""
    root = logging.getLogger()
    if getattr(root, "_clinicq_configured", False):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    handler.addFilter(_RedactFilter())
    root.handlers[:] = [handler]
    root.setLevel(logging.INFO)
    root._clinicq_configured = True  # type: ignore[attr-defined]


# --- metrics counters --------------------------------------------------------
_counters: dict[str, int] = {"wa_send_failures": 0}
_last_scheduler_tick: datetime | None = None


def record_send_failure() -> None:
    _counters["wa_send_failures"] += 1


def mark_scheduler_tick(now: datetime) -> None:
    global _last_scheduler_tick
    _last_scheduler_tick = now


def counters() -> dict[str, int]:
    return dict(_counters)


def last_scheduler_tick() -> datetime | None:
    return _last_scheduler_tick
