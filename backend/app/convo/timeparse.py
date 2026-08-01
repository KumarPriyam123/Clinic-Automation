"""Ambiguous wall-clock resolution — pure, deterministic, no LLM, no network.

The LLM returns a 24-hour ``HH:MM``, but it cannot reliably know whether a bare
"11:30" means 11:30 AM or 11:30 PM: that answer lives in the *session the
patient already picked*, not in the sentence.  Production proved this — a bare
"11:30" typed into a 17:00–23:30 evening session was read as 11:30 AM, then
silently clamped to the session start.

So the LLM's hour is treated as a 12-hour hint and both readings are evaluated
here against the chosen session's ``[start_at, end_at]`` window:

  * patient stated an explicit AM/PM marker  -> that reading only
  * exactly one reading inside the window    -> use it
  * both inside                              -> the one nearest the live clock
    (or the session start, when the session has not begun yet)
  * neither inside                           -> ``out_of_window``; the flow
    re-asks.  We never silently move a patient to a time they did not choose.

Window bounds are inclusive: a session running 17:00–23:30 can legitimately be
asked for 23:30.  Whether that late a target still fits behind the queue is the
engine's ``past_end`` overflow check, not this module's business.

Every function takes an injected ``now`` — no wall-clock reads.
"""

from __future__ import annotations

import dataclasses as dc
import re
from datetime import date as _date
from datetime import datetime
from enum import Enum
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

#: Words that pin a bare hour to one half of the day.  Latin (Hinglish) and
#: Devanagari both, because patients type either.  ``\b`` is Unicode-aware in
#: Python's ``re``, so Devanagari words are bounded correctly.
_MERIDIEM = re.compile(
    r"\b("
    r"a\.?m\.?|p\.?m\.?"
    r"|morning|afternoon|evening|night|noon|midnight"
    r"|subah|sub[ha]|savere|sawere|dopahar|dupahar"
    r"|shaam|sham|shyam|raat|raatri|rat"
    r"|सुबह|सवेरे|तड़के|दोपहर|शाम|संध्या|रात|रात्रि|दुपहर"
    r")\b",
    re.IGNORECASE | re.UNICODE,
)


def has_meridiem(text: str | None) -> bool:
    """True when the patient's own words pin the time to AM or PM.

    Deterministic and LLM-independent on purpose: this decides whether we are
    allowed to reinterpret the hour, so it must keep working when the LLM is
    degraded or mocked.
    """
    return bool(text) and _MERIDIEM.search(text or "") is not None


class Outcome(str, Enum):
    ok = "ok"
    out_of_window = "out_of_window"
    invalid = "invalid"  # unparseable HH:MM — caller re-asks with buttons


@dc.dataclass(frozen=True, slots=True)
class Window:
    """The chosen session's booking window (UTC instants + its IST date)."""

    date: _date
    start_at: datetime
    end_at: datetime

    def contains(self, at: datetime) -> bool:
        return self.start_at <= at <= self.end_at


@dc.dataclass(frozen=True, slots=True)
class Resolution:
    outcome: Outcome
    at: datetime | None = None
    #: True when both AM and PM readings were considered (no explicit marker).
    ambiguous: bool = False

    @property
    def ok(self) -> bool:
        return self.outcome is Outcome.ok


def parse_hhmm(hhmm: str | None) -> tuple[int, int] | None:
    """'HH:MM' -> (h, m), or None when it is not a valid 24h time."""
    try:
        h_s, m_s = (hhmm or "").split(":")
        h, m = int(h_s), int(m_s)
    except (ValueError, AttributeError):
        return None
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return None
    return h, m


def _on(day: _date, h: int, m: int) -> datetime:
    """A wall-clock IST time on `day`, as a UTC instant."""
    return datetime(day.year, day.month, day.day, h, m, tzinfo=IST).astimezone(ZoneInfo("UTC"))


def resolve(
    now: datetime,
    hhmm: str | None,
    *,
    explicit: bool,
    window: Window | None,
) -> Resolution:
    """Resolve a parsed ``HH:MM`` against the chosen session's window.

    ``explicit`` — the patient said AM/PM (or सुबह/शाम/…), so the stated
    reading is the only one considered.

    With no ``window`` (a stale conversation whose session metadata predates
    this feature) we fall back to the literal reading on today's IST date,
    which is exactly the old behaviour — degraded, never crashing.
    """
    parsed = parse_hhmm(hhmm)
    if parsed is None:
        return Resolution(Outcome.invalid)
    h, m = parsed

    if window is None:
        return Resolution(Outcome.ok, _on(now.astimezone(IST).date(), h, m))

    primary = _on(window.date, h, m)
    if explicit:
        if window.contains(primary):
            return Resolution(Outcome.ok, primary)
        return Resolution(Outcome.out_of_window)

    # No marker: the hour is a 12-hour hint, so both halves of the day are live
    # candidates regardless of which one the LLM happened to emit.
    alt = _on(window.date, (h + 12) % 24, m)
    inside = [c for c in (primary, alt) if window.contains(c)]
    if not inside:
        return Resolution(Outcome.out_of_window, ambiguous=True)
    if len(inside) == 1:
        return Resolution(Outcome.ok, inside[0], ambiguous=True)

    # Both readings are servable — take the one nearest the doctor's live
    # clock (session start when the session has not begun).
    ref = max(now, window.start_at)
    nearest = min(inside, key=lambda c: abs((c - ref).total_seconds()))
    return Resolution(Outcome.ok, nearest, ambiguous=True)


def window_from(meta: dict | None) -> Window | None:
    """Rebuild a Window from the ISO strings stashed in conversation context.

    Returns None for missing/garbled context so an in-flight conversation from
    before this feature shipped degrades instead of raising.
    """
    if not meta:
        return None
    try:
        return Window(
            date=_date.fromisoformat(meta["date"]),
            start_at=datetime.fromisoformat(meta["start_at"]),
            end_at=datetime.fromisoformat(meta["end_at"]),
        )
    except (KeyError, TypeError, ValueError):
        return None
