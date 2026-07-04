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
