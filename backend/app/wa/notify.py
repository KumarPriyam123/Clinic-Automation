"""NotificationDispatcher — the ONLY bridge from engine to WhatsApp.

Consumes EngineResult.notifications (pure NotificationIntent data), resolves
each entry's recipient, builds the template ctx, and sends via the gateway.
The engine never imports this; this imports the engine's result types only.
"""

from __future__ import annotations

import dataclasses as dc
from datetime import datetime
from typing import Protocol
from uuid import UUID
from zoneinfo import ZoneInfo

from app.engine.results import EngineResult, NotificationIntent, NotificationType
from app.wa.sender import Sender

IST = ZoneInfo("Asia/Kolkata")


def fmt_time(dt: datetime | None) -> str:
    if dt is None:
        return ""
    return dt.astimezone(IST).strftime("%I:%M %p").lstrip("0")


@dc.dataclass(slots=True)
class Recipient:
    wa_number: str
    name: str
    lang: str
    token_number: int
    clinic_id: UUID | None = None
    eta: datetime | None = None
    report: datetime | None = None


class RecipientResolver(Protocol):
    async def for_entry(self, entry_id: UUID) -> Recipient | None: ...


class NotificationDispatcher:
    def __init__(self, sender: Sender, resolver: RecipientResolver) -> None:
        self._sender = sender
        self._resolver = resolver

    async def dispatch(
        self, now: datetime, result: EngineResult, *, allow_eta_shift: bool = False
    ) -> None:
        # eta_shift is owned by the ping_scan job (idempotent via last_notified_eta);
        # every other dispatch path skips it so a patient never gets it twice.
        for intent in result.notifications:
            if intent.type == NotificationType.eta_shift and not allow_eta_shift:
                continue
            await self._dispatch_one(now, intent)

    async def _dispatch_one(self, now: datetime, intent: NotificationIntent) -> None:
        if intent.entry_id is None:
            return
        rec = await self._resolver.for_entry(intent.entry_id)
        if rec is None:
            return
        ctx = self._ctx(now, intent, rec)
        await self._sender.send(
            now,
            rec.wa_number,
            template_name=intent.type.value,
            ctx=ctx,
            lang=rec.lang,
            clinic_id=rec.clinic_id,
        )

    def _ctx(self, now: datetime, intent: NotificationIntent, rec: Recipient) -> dict:
        p = intent.params
        ctx: dict = {
            "entry_id": intent.entry_id,
            "name": rec.name,
            "token": rec.token_number,
        }
        if intent.type == NotificationType.eta_shift:
            ctx["eta"] = fmt_time(p.get("eta") or rec.eta)
        elif intent.type == NotificationType.pre_arrival:
            ctx["eta"] = fmt_time(p.get("eta") or rec.eta)
            ctx["report"] = fmt_time(p.get("report") or rec.report)
        elif intent.type == NotificationType.three_away:
            ctx["eta"] = fmt_time(p.get("eta") or rec.eta)
        elif intent.type == NotificationType.skipped_grace:
            grace_until = p.get("grace_until")
            ctx["minutes"] = (
                max(0, round((grace_until - now).total_seconds() / 60)) if grace_until else ""
            )
        elif intent.type == NotificationType.you_are_next:
            ctx["token"] = p.get("token_number", rec.token_number)
        elif intent.type == NotificationType.gap_offer:
            ctx["new"] = fmt_time(p.get("new") or now)
            ctx["old"] = fmt_time(p.get("old") or rec.eta)
        # expired_rebook / closed_broadcast need no extra params
        return ctx
