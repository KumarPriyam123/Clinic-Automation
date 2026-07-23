"""Panel response contract — Pydantic models mirroring the queue snapshot the
routes emit. These are the single source of truth for the panel<->backend wire
shape:

  * route tests parse responses back through :class:`QueueSnapshot` (a real
    validation, ``extra="forbid"`` so any stray/renamed field fails),
  * ``panel/contract/queue-snapshot.schema.json`` is generated from
    ``QueueSnapshot.model_json_schema()`` and pinned by ``test_contract.py`` so
    any future change to the response shape breaks a test and prompts updating
    ``panel/app/lib/types.ts``.

The routes still build plain dicts (behaviour unchanged); these models describe
that same shape field-for-field. All timestamps are ISO-8601 strings (the routes
serialise via ``.isoformat()``); ``date`` is an ISO date string.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

_forbid = ConfigDict(extra="forbid")


class SessionMetaOut(BaseModel):
    model_config = _forbid
    id: str
    name: str
    status: str
    date: str
    start_at: str | None
    end_at: str | None
    token_cap: int
    avg_consult_s: int
    doctor_free_at: str | None
    served: int
    waiting: int


class NowServingOut(BaseModel):
    model_config = _forbid
    entry_id: str
    token_number: int
    name: str
    consult_start: str | None


class QueueEntryOut(BaseModel):
    model_config = _forbid
    entry_id: str
    token_number: int
    name: str
    status: str
    source: str
    priority_time: str | None
    eta: str | None
    report_time: str | None
    arrived_at: str | None
    grace_until: str | None
    next_up: bool


class SessionListItemOut(BaseModel):
    model_config = _forbid
    id: str
    name: str
    status: str
    start_at: str | None
    end_at: str | None


class QueueSnapshot(BaseModel):
    model_config = _forbid
    session: SessionMetaOut | None
    now_serving: NowServingOut | None
    entries: list[QueueEntryOut]
    sessions: list[SessionListItemOut] | None = None
    can_undo: bool | None = None
