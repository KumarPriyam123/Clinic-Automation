"""Conversation state machine: idle → choosing_session → choosing_time →
choosing_profile → (booked), plus confirm_cancel.

Buttons/lists drive transitions directly; free text goes through the LLM
(confidence < 0.7 ⇒ re-ask with buttons, never guess); keywords (status /
kitna time / cancel / STOP) bypass everything. The LLM never mutates state and
never produces medical text. All engine mutations go through
``backend.engine_call`` so production gets a real transaction + row lock.
"""

from __future__ import annotations

import dataclasses as dc
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from app import engine
from app.convo.llm import Intent
from app.convo.store import ConvoBackend, ConvState
from app.models import Source
from app.wa.notify import NotificationDispatcher, fmt_time
from app.wa.sender import Sender
from app.wa.templates import (
    BTN_ASAP,
    BTN_CANCEL_NO,
    BTN_CANCEL_YES,
    BTN_FAMILY,
    BTN_SELF,
    btn,
    prompt,
)
from app.wa.webhook import InboundMessage

IST = ZoneInfo("Asia/Kolkata")
ParseFn = Callable[[str, dict], Awaitable[Intent]]


def _is_status(low: str) -> bool:
    return low == "status" or "kitna time" in low or "kitni der" in low or "कितना" in low


def _is_cancel_kw(low: str) -> bool:
    return low.startswith("cancel") or "रद्द" in low


def _req_from(now: datetime, hhmm: str) -> datetime | None:
    try:
        h, m = (int(x) for x in hhmm.split(":"))
    except (ValueError, AttributeError):
        return None
    ist = now.astimezone(IST).replace(hour=h, minute=m, second=0, microsecond=0)
    return ist.astimezone(UTC)


@dc.dataclass(slots=True)
class Flow:
    backend: ConvoBackend
    sender: Sender
    parse: ParseFn

    # --- entrypoint ------------------------------------------------------ #
    async def handle(self, now: datetime, inbound: InboundMessage) -> None:
        clinic = await self.backend.clinic_for_phone(inbound.phone_number_id)
        if clinic is None:
            return
        wa = inbound.wa_number
        conv = await self.backend.get_conversation(wa, clinic.id)
        first = conv is None
        st = conv or ConvState()
        lang = clinic.language

        text = (inbound.text or "").strip()
        low = text.lower()

        # STOP — DPDP delete (highest priority keyword)
        if low == "stop":
            await self.backend.stop_delete(clinic.id, wa)
            await self._say(now, clinic.id, wa, prompt("stop_done", lang))
            await self.backend.save_conversation(wa, clinic.id, ConvState())
            return

        # buttons/lists drive transitions directly
        if inbound.button_id:
            return await self._button(now, clinic, wa, lang, st, inbound.button_id, first)

        # keyword bypass
        if _is_status(low):
            return await self._status(now, clinic, wa, lang)
        if _is_cancel_kw(low):
            return await self._ask_cancel(now, clinic, wa, lang, st)

        # awaiting a typed family-member name
        if st.state == "choosing_profile" and st.context.get("awaiting_name"):
            return await self._book(now, clinic, wa, lang, st, profile_name=text or "family")

        # free text -> LLM
        intent = await self.parse(text, {"state": st.state})
        if intent.confidence < 0.7:
            return await self._low_confidence(now, clinic, wa, lang, st)

        # in choosing_time, a typed specific time advances to profile
        if st.state == "choosing_time" and intent.time_pref:
            st.context["requested"] = intent.time_pref
            return await self._offer_profiles(now, clinic, wa, lang, st)

        return await self._route(now, clinic, wa, lang, st, intent, first)

    # --- intent routing -------------------------------------------------- #
    async def _route(self, now, clinic, wa, lang, st, intent: Intent, first: bool) -> None:
        i = intent.intent
        if i in ("book", "greeting", "reschedule"):
            if intent.time_pref:
                st.context["requested"] = intent.time_pref
            return await self._offer_sessions(now, clinic, wa, lang, st, first)
        if i == "status":
            return await self._status(now, clinic, wa, lang)
        if i == "cancel":
            return await self._ask_cancel(now, clinic, wa, lang, st)
        if i == "arrived":
            return await self._arrived_active(now, clinic, wa, lang)
        if i == "medical_question":
            return await self._say(now, clinic.id, wa, prompt("medical_safe", lang))
        return await self._low_confidence(now, clinic, wa, lang, st)

    # --- buttons --------------------------------------------------------- #
    async def _button(self, now, clinic, wa, lang, st, button_id: str, first: bool) -> None:
        prefix, _, arg = button_id.partition(":")
        if prefix == "sess":
            st.context["session_id"] = arg
            return await self._offer_time(now, clinic, wa, lang, st)
        if prefix == "time":  # time:asap
            st.context["requested"] = "asap"
            return await self._offer_profiles(now, clinic, wa, lang, st)
        if prefix == "profile":
            if arg == "family":
                st.state = "choosing_profile"
                st.context["awaiting_name"] = True
                await self.backend.save_conversation(wa, clinic.id, st)
                return await self._say(now, clinic.id, wa, prompt("ask_name", lang))
            return await self._book(now, clinic, wa, lang, st, profile_name="self")
        if prefix == "arrived":
            return await self._mark_arrived(now, clinic, wa, lang, UUID(arg))
        if prefix == "cancel":
            return await self._do_cancel(now, clinic, wa, lang, UUID(arg))
        if prefix == "gapyes":
            return await self._accept_gap(now, clinic, wa, lang, UUID(arg))
        if prefix == "rebook":  # rebook:tomorrow
            return await self._offer_sessions(now, clinic, wa, lang, st, first)
        if prefix == "confirmcancel":
            if arg == "yes":
                eid = st.context.get("cancel_entry")
                if eid:
                    return await self._do_cancel(now, clinic, wa, lang, UUID(eid))
            await self.backend.save_conversation(wa, clinic.id, ConvState())
            return

    # --- booking steps --------------------------------------------------- #
    async def _offer_sessions(self, now, clinic, wa, lang, st, first: bool) -> None:
        sessions = await self.backend.bookable_sessions(clinic.id, now)
        if not sessions:
            await self._say(now, clinic.id, wa, prompt("no_sessions", lang), first=first)
            return
        rows = [
            {"id": f"sess:{s.id}", "title": s.name, "description": f"{s.free} slots"}
            for s in sessions
        ]
        body = prompt("choose_session", lang)
        if first:
            body = prompt("consent", lang) + "\n\n" + body
        await self.sender.send_list(
            now,
            wa,
            body,
            [{"title": prompt("choose_session", lang), "rows": rows}],
            clinic_id=clinic.id,
        )
        st.state = "choosing_session"
        await self.backend.save_conversation(wa, clinic.id, st)

    async def _offer_time(self, now, clinic, wa, lang, st) -> None:
        await self.sender.send_buttons(
            now, wa, prompt("choose_time", lang), [btn(BTN_ASAP, lang)], clinic_id=clinic.id
        )
        st.state = "choosing_time"
        await self.backend.save_conversation(wa, clinic.id, st)

    async def _offer_profiles(self, now, clinic, wa, lang, st) -> None:
        await self.sender.send_buttons(
            now,
            wa,
            prompt("choose_profile", lang),
            [btn(BTN_SELF, lang), btn(BTN_FAMILY, lang)],
            clinic_id=clinic.id,
        )
        st.state = "choosing_profile"
        st.context.pop("awaiting_name", None)
        await self.backend.save_conversation(wa, clinic.id, st)

    async def _book(self, now, clinic, wa, lang, st, *, profile_name: str) -> None:
        session_id = UUID(st.context["session_id"])
        requested = st.context.get("requested")
        req_dt = None if requested in (None, "asap") else _req_from(now, requested)
        patient_id = await self.backend.get_or_create_patient(clinic.id, wa, profile_name)
        result = await self.backend.engine_call(
            lambda r: engine.book(
                r,
                now,
                clinic_id=clinic.id,
                session_id=session_id,
                patient_id=patient_id,
                requested_time=req_dt,
                source=Source.whatsapp,
            )
        )
        if result.overflow is not None:
            rows = [
                {"id": f"sess:{a.session_id}", "title": a.name, "description": f"{a.free} slots"}
                for a in result.overflow.alternatives
            ]
            await self.sender.send_list(
                now,
                wa,
                prompt("overflow", lang),
                [{"title": prompt("choose_session", lang), "rows": rows}] if rows else [],
                clinic_id=clinic.id,
            )
            st.state = "choosing_session"
            await self.backend.save_conversation(wa, clinic.id, st)
            return

        entry = result.entry
        await self.sender.send(
            now,
            wa,
            template_name="booking_confirmed",
            ctx={
                "name": profile_name if profile_name != "self" else "",
                "token": entry.token_number,
                "eta": fmt_time(entry.eta),
                "report": fmt_time(entry.report_time),
                "entry_id": entry.id,
            },
            lang=lang,
            clinic_id=clinic.id,
        )
        await self.backend.save_conversation(wa, clinic.id, ConvState())

    # --- status / arrived / cancel / gap -------------------------------- #
    async def _status(self, now, clinic, wa, lang) -> None:
        info = await self.backend.active_entry(clinic.id, wa)
        if info is None:
            return await self._say(now, clinic.id, wa, prompt("no_active", lang))
        await self._say(
            now,
            clinic.id,
            wa,
            prompt(
                "status_line",
                lang,
                token=info.token_number,
                ahead=info.ahead,
                eta=fmt_time(info.eta),
            ),
        )

    async def _arrived_active(self, now, clinic, wa, lang) -> None:
        info = await self.backend.active_entry(clinic.id, wa)
        if info is None:
            return await self._say(now, clinic.id, wa, prompt("no_active", lang))
        await self._mark_arrived(now, clinic, wa, lang, info.entry_id)

    async def _mark_arrived(self, now, clinic, wa, lang, entry_id: UUID) -> None:
        result = await self.backend.engine_call(lambda r: engine.mark_arrived(r, now, entry_id))
        await self._dispatch(now, result)
        await self._say(now, clinic.id, wa, prompt("arrived_ack", lang))

    async def _ask_cancel(self, now, clinic, wa, lang, st) -> None:
        info = await self.backend.active_entry(clinic.id, wa)
        if info is None:
            return await self._say(now, clinic.id, wa, prompt("no_active", lang))
        st.state = "confirm_cancel"
        st.context["cancel_entry"] = str(info.entry_id)
        await self.backend.save_conversation(wa, clinic.id, st)
        await self.sender.send_buttons(
            now,
            wa,
            prompt("cancel_confirm", lang),
            [btn(BTN_CANCEL_YES, lang), btn(BTN_CANCEL_NO, lang)],
            clinic_id=clinic.id,
        )

    async def _do_cancel(self, now, clinic, wa, lang, entry_id: UUID) -> None:
        result = await self.backend.engine_call(lambda r: engine.cancel(r, now, entry_id))
        await self._dispatch(now, result)
        await self._say(now, clinic.id, wa, prompt("cancelled", lang))
        await self.backend.save_conversation(wa, clinic.id, ConvState())

    async def _accept_gap(self, now, clinic, wa, lang, entry_id: UUID) -> None:
        result = await self.backend.engine_call(lambda r: engine.accept_gap_offer(r, now, entry_id))
        await self._dispatch(now, result)
        await self._say(now, clinic.id, wa, prompt("gap_accepted", lang))

    # --- helpers --------------------------------------------------------- #
    async def _low_confidence(self, now, clinic, wa, lang, st) -> None:
        await self._say(now, clinic.id, wa, prompt("low_confidence", lang))
        if st.state == "idle":
            await self._offer_sessions(now, clinic, wa, lang, st, first=False)

    async def _say(self, now, clinic_id, wa, text: str, *, first: bool = False) -> None:
        await self.sender.send_text(now, wa, text, clinic_id=clinic_id)

    async def _dispatch(self, now, result) -> None:
        if result.notifications:
            disp = NotificationDispatcher(self.sender, self.backend.resolver())
            await disp.dispatch(now, result)
