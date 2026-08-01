"""Engine exceptions — raised for genuinely invalid callers, not for the
expected 'session full' path (that returns an OverflowSuggestion instead)."""

from __future__ import annotations


class EngineError(Exception):
    """Base for all engine errors."""


class DuplicateActiveToken(EngineError):
    """A (clinic, wa_number) already holds an ACTIVE token today."""


class GraceExpired(EngineError):
    """arrived_during_grace called after grace_until has passed."""


class InvalidTransition(EngineError):
    """The entry/session is not in a state that allows this transition."""


class SessionEnded(InvalidTransition):
    """The session's end_at has already passed, so it cannot be made live.

    Distinct from InvalidTransition because it has a distinct cause and a
    distinct answer for the receptionist: the 60s sweep auto-closes any session
    past its end_at, so accepting the transition would only have it silently
    reverted a minute later. Rejecting it up front makes the reason visible.
    """
