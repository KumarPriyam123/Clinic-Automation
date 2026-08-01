"""Conversation state machine: idle → choosing_session → choosing_time →
choosing_profile → (booked), plus confirm_cancel.

Buttons/lists drive transitions directly; free text goes through the LLM
(confidence < 0.7 ⇒ re-ask with buttons, never guess); keywords (status /
kitna time / cancel / STOP / greeting) bypass everything. The LLM never
mutates state and never produces medical text. All engine mutations go through
``backend.engine_call`` so production gets a real transaction + row lock.
"""

from __future__ import annotations

import dataclasses as dc
import re
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from app import engine
from app.convo import timeparse
from app.convo.llm import Intent
from app.convo.store import ConvoBackend, ConvState
from app.models import Source
from app.wa.notify import NotificationDispatcher, fmt_date, fmt_time
from app.wa.sender import Sender
from app.wa.templates import (
    BTN_ASAP,
    BTN_CANCEL_NO,
    BTN_CANCEL_YES,
    BTN_FAMILY,
    BTN_SELF,
    btn,
    prompt,
    session_label,
)
from app.wa.webhook import InboundMessage

IST = ZoneInfo("Asia/Kolkata")
ParseFn = Callable[[str, dict], Awaitable[Intent]]

_GREETING_WORDS = frozenset(
    {
        "hi",
        "hii",
        "hiii",
        "hello",
        "helo",
        "hey",
        "namaste",
        "namaskar",
        "नमस्ते",
        "नमस्कार",
        "हाय",
        "हैलो",
        "salaam",
        "assalam",
        "start",
        "menu",
        "शुरू",
    }
)
_PUNCT_TAIL = re.compile(r"[!?,.।\s]+$")  # । = Devanagari danda


def _is_greeting(low: str) -> bool:
    return _PUNCT_TAIL.sub("", low).strip() in _GREETING_WORDS


def _is_status(low: str) -> bool:
    return low == "status" or "kitna time" in low or "kitni der" in low or "कितना" in low


def _is_cancel_kw(low: str) -> bool:
    return low.startswith("cancel") or "रद्द" in low


def _window(st: ConvState) -> timeparse.Window | None:
    """The chosen session's window, if the patient has picked one."""
    return timeparse.window_from(st.context.get("session_window"))


def _session_meta(s) -> dict:
    """JSON-safe {name, date, start_at, end_at} for conversation context.

    Works for both SessionInfo (first choice) and SessionRef (overflow
    alternative); either may lack the window on an older row, hence the guards.
    """
    meta: dict = {"name": s.name}
    if getattr(s, "date", None) is not None:
        meta["date"] = s.date.isoformat()
    if getattr(s, "start_at", None) is not None:
        meta["start_at"] = s.start_at.isoformat()
    if getattr(s, "end_at", None) is not None:
        meta["end_at"] = s.end_at.isoformat()
    return meta


def _booking_notice(now: datetime, lang: str, info) -> str | None:
    """Everything the patient did not ask for, stated plainly — or None.

    Two independent facts, either or both of which may apply:
      * the booking is not for today (a token issued at 11 PM for tomorrow
        evening otherwise looks like tonight),
      * the granted time had to move more than 10 min from the request.
    """
    if info is None:
        return None
    lines: list[str] = []
    today = now.astimezone(IST).date()
    if info.session_date != today:
        key = (
            "booking_day_tomorrow"
            if info.session_date == today + timedelta(days=1)
            else "booking_day_other"
        )
        lines.append(
            prompt(
                key,
                lang,
                date=fmt_date(info.session_date),
                session=session_label(info.session_name, lang),
            )
        )
    if info.adjust_reason == "session_start":
        lines.append(
            prompt(
                "adjusted_to_start",
                lang,
                requested=fmt_time(info.requested),
                start=fmt_time(info.session_start),
            )
        )
    elif info.adjust_reason == "now":
        lines.append(prompt("adjusted_to_now", lang, requested=fmt_time(info.requested)))
    return "\n".join(lines) if lines else None


def _slots_line(lang: str, free: int, day, today) -> str:
    """List-row description. Non-today sessions carry the date, so 'evening'
    tomorrow is never mistaken for 'evening' tonight."""
    if day is None or day == today:
        return prompt("slots_left", lang, free=free)
    return prompt("slots_left_on", lang, free=free, date=fmt_date(day))


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

        # keyword bypass — all checked BEFORE llm.parse() so they work when LLM is down
        if _is_status(low):
            return await self._status(now, clinic, wa, lang)
        if _is_cancel_kw(low):
            return await self._ask_cancel(now, clinic, wa, lang, st)
        if _is_greeting(low):
            return await self._greeting(now, clinic, wa, lang, st, first)

        # awaiting a typed family-member name
        if st.state == "choosing_profile" and st.context.get("awaiting_name"):
            return await self._book(now, clinic, wa, lang, st, profile_name=text or "family")

        # free text -> LLM
        intent = await self.parse(
            text,
            {
                "state": st.state,
                "session_name": st.context.get("session_name", ""),
                "session_window": st.context.get("session_window"),
            },
        )
        if intent.confidence < 0.7:
            return await self._low_confidence(now, clinic, wa, lang, st)

        # in choosing_time, a typed specific time advances to profile
        if st.state == "choosing_time" and intent.time_pref:
            return await self._accept_time(now, clinic, wa, lang, st, intent.time_pref, text)

        return await self._route(now, clinic, wa, lang, st, intent, first, text)

    # --- intent routing -------------------------------------------------- #
    async def _route(
        self, now, clinic, wa, lang, st, intent: Intent, first: bool, text: str
    ) -> None:
        i = intent.intent
        if i in ("book", "greeting", "reschedule"):
            if intent.time_pref:
                # Held raw: it can only be resolved once we know which session
                # (and therefore which day and window) the patient picks.
                st.context["requested"] = intent.time_pref
                st.context["requested_text"] = text
                st.context.pop("requested_at", None)
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
            # Recover the session's name AND window from the map saved by
            # _offer_sessions: the window is what makes a bare "11:30"
            # resolvable, and the day is what the confirmation must state.
            meta = (st.context.get("_sessions") or {}).get(arg)
            if meta:
                st.context["session_name"] = meta.get("name", "")
                st.context["session_window"] = {
                    k: meta[k] for k in ("date", "start_at", "end_at") if k in meta
                }
            else:
                # conversation started before windows were stashed — degrade
                name = (st.context.get("_session_names") or {}).get(arg, "")
                if name:
                    st.context["session_name"] = name
                st.context.pop("session_window", None)
            # A time stated before the session was chosen ("kal subah 10 baje")
            # can only be resolved now. Honour it instead of asking again.
            pending = st.context.get("requested")
            if pending and pending != "asap":
                return await self._accept_time(
                    now, clinic, wa, lang, st, pending, st.context.get("requested_text") or ""
                )
            return await self._offer_time(now, clinic, wa, lang, st)
        if prefix == "time":  # time:asap
            st.context["requested"] = "asap"
            st.context.pop("requested_at", None)
            st.context.pop("requested_text", None)
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
        today = now.astimezone(IST).date()
        rows = [
            {
                "id": f"sess:{s.id}",
                "title": session_label(s.name, lang),
                "description": _slots_line(lang, s.free, s.date, today),
            }
            for s in sessions
        ]
        # Save session_id → {name, window} so _button can recover both: the name
        # for LLM context, the window for resolving a typed time to the right
        # day. _session_names is kept for conversations already in flight.
        st.context["_sessions"] = {str(s.id): _session_meta(s) for s in sessions}
        st.context["_session_names"] = {str(s.id): s.name for s in sessions}
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

    async def _accept_time(self, now, clinic, wa, lang, st, hhmm: str, text: str) -> None:
        """Resolve a typed time against the chosen session, or re-ask.

        The LLM's HH:MM is only a 12-hour hint — see convo/timeparse.py. When
        neither reading fits the session we re-ask rather than clamp, because
        silently handing someone a time five hours from what they typed is the
        single worst trust failure in this flow.
        """
        res = timeparse.resolve(
            now, hhmm, explicit=timeparse.has_meridiem(text), window=_window(st)
        )
        if res.outcome is timeparse.Outcome.invalid:
            return await self._low_confidence(now, clinic, wa, lang, st)
        if res.outcome is timeparse.Outcome.out_of_window:
            return await self._reask_time(now, clinic, wa, lang, st)
        st.context["requested"] = hhmm
        st.context["requested_text"] = text
        st.context["requested_at"] = res.at.isoformat()
        return await self._offer_profiles(now, clinic, wa, lang, st)

    async def _reask_time(self, now, clinic, wa, lang, st) -> None:
        """Tell the patient the window and ask again — never a silent clamp."""
        win = _window(st)
        await self._say(
            now,
            clinic.id,
            wa,
            prompt(
                "time_out_of_window",
                lang,
                start=fmt_time(win.start_at) if win else "",
                end=fmt_time(win.end_at) if win else "",
            ),
        )
        for key in ("requested", "requested_at", "requested_text"):
            st.context.pop(key, None)
        await self._offer_time(now, clinic, wa, lang, st)

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
        req_dt: datetime | None = None
        if requested not in (None, "asap"):
            iso = st.context.get("requested_at")
            if iso:
                req_dt = datetime.fromisoformat(iso)
            else:
                # Not resolved earlier (stale context / older conversation).
                res = timeparse.resolve(
                    now,
                    requested,
                    explicit=timeparse.has_meridiem(st.context.get("requested_text")),
                    window=_window(st),
                )
                if res.outcome is timeparse.Outcome.out_of_window:
                    return await self._reask_time(now, clinic, wa, lang, st)
                req_dt = res.at
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
            today = now.astimezone(IST).date()
            alts = result.overflow.alternatives
            rows = [
                {
                    "id": f"sess:{a.session_id}",
                    "title": session_label(a.name, lang),
                    "description": _slots_line(lang, a.free, a.date, today),
                }
                for a in alts
            ]
            # Carry the alternatives' windows too, so a time typed after the
            # switch resolves against the session actually picked.
            st.context["_sessions"] = {str(a.session_id): _session_meta(a) for a in alts}
            st.context["_session_names"] = {str(a.session_id): a.name for a in alts}
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
        # One plain sentence for anything the patient did not ask for — sent
        # BEFORE the token details, as its own message (booking_confirmed is a
        # Meta-approved template with a fixed parameter list).
        notice = _booking_notice(now, lang, result.booking)
        if notice:
            await self._say(now, clinic.id, wa, notice)
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
    async def _greeting(self, now, clinic, wa, lang, st, first: bool) -> None:
        """Greeting keyword handler — runs before any LLM call.

        Precedence rule: if the patient already has an active token, show their
        current status and preserve conversation state — silently wiping an
        in-flight booking is worse than being redundant. If no active token,
        reset to idle and re-welcome (with consent line on very first contact).
        """
        info = await self.backend.active_entry(clinic.id, wa)
        if info is not None:
            await self._say(
                now,
                clinic.id,
                wa,
                prompt(
                    "greeting_has_active",
                    lang,
                    token=info.token_number,
                    ahead=info.ahead,
                    eta=fmt_time(info.eta),
                ),
            )
            return
        await self._offer_sessions(now, clinic, wa, lang, ConvState(), first)

    async def _low_confidence(self, now, clinic, wa, lang, st) -> None:
        """Re-render current step's prompt so no state is a dead end.

        Every non-idle state re-sends its own buttons after the low-confidence
        message, and all states mention 'menu' as a plain-text escape hatch.
        """
        await self._say(now, clinic.id, wa, prompt("low_confidence", lang))
        if st.state in ("idle", "choosing_session"):
            await self._offer_sessions(now, clinic, wa, lang, st, first=False)
        elif st.state == "choosing_time":
            await self._offer_time(now, clinic, wa, lang, st)
        elif st.state == "choosing_profile":
            await self._offer_profiles(now, clinic, wa, lang, st)
        elif st.state == "confirm_cancel":
            await self._ask_cancel(now, clinic, wa, lang, st)

    async def _say(self, now, clinic_id, wa, text: str, *, first: bool = False) -> None:
        await self.sender.send_text(now, wa, text, clinic_id=clinic_id)

    async def _dispatch(self, now, result) -> None:
        if result.notifications:
            disp = NotificationDispatcher(self.sender, self.backend.resolver())
            await disp.dispatch(now, result)
