"""Conversation flow tests — scripted dialogues, LLM mocked (no network).

Asserts the flow's handling of each inbound (button or free text + returned
Intent): the sends it emits and the resulting engine state in MemConvo.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from app import engine
from app.convo.flow import Flow
from app.convo.llm import Intent
from app.convo.store import ClinicInfo, MemConvo
from app.engine.state import SessionState
from app.models import SessionStatus, Source, Status
from app.wa.sender import Sender
from app.wa.store import InMemoryWaStore
from app.wa.webhook import InboundMessage

WA = "+919000000001"


def dt(h, m=0):
    return datetime(2026, 7, 5, h, m, tzinfo=UTC)


def run(coro):
    return asyncio.run(coro)


class Parse:
    """Mock llm.parse — returns queued Intents, else low-confidence 'other'."""

    def __init__(self):
        self.q: list[Intent] = []

    def push(self, **kw):
        self.q.append(Intent(**kw))

    async def __call__(self, text, ctx):
        return self.q.pop(0) if self.q else Intent(intent="other", confidence=0.0)


class FakeSender(Sender):
    """Builds payloads + logs outbound like the real gateway, but never POSTs."""

    async def _post(self, payload):
        return {"messaging_product": "whatsapp", "messages": [{"id": "wamid.OUT"}]}


def build(*, lang="hi", cap=40):
    store = InMemoryWaStore()
    sender = FakeSender(store, token="t", phone_number_id="123", backoff_base=0)
    convo = MemConvo()
    clinic = ClinicInfo(id=uuid4(), language=lang, name="C", doctor_name="Dr")
    convo.add_clinic("123", clinic)
    s = _session(convo, clinic.id, cap=cap)
    parse = Parse()
    flow = Flow(convo, sender, parse)
    return store, sender, convo, clinic, s, parse, flow


def _session(convo, clinic_id, *, cap=40, name="morning"):
    now = dt(9)
    s = SessionState(
        id=uuid4(),
        clinic_id=clinic_id,
        date=now.date(),
        name=name,
        start_at=now,
        end_at=now + timedelta(hours=6),
        token_cap=cap,
        status=SessionStatus.open,
        doctor_free_at=now,
        avg_consult_s=600,
    )
    return convo.repo.add_session(s)


# --------------------------------------------------------------------------- #
# IST-anchored session helpers — the ambiguous-time rules are all about the
# session's *wall clock* window, so these tests state windows in IST.
# --------------------------------------------------------------------------- #
IST = ZoneInfo("Asia/Kolkata")
DAY = date(2026, 7, 5)


def ist(h, m=0, day=DAY):
    return datetime(day.year, day.month, day.day, h, m, tzinfo=IST).astimezone(UTC)


def hhmm(at):
    return "" if at is None else at.astimezone(IST).strftime("%H:%M")


def _ist_session(convo, clinic_id, *, name, start, end, day=DAY, cap=40, status=None):
    """A session whose window is given as IST wall-clock hours."""
    s = SessionState(
        id=uuid4(),
        clinic_id=clinic_id,
        date=day,
        name=name,
        start_at=ist(*start, day=day),
        end_at=ist(*end, day=day),
        token_cap=cap,
        status=status or SessionStatus.open,
        doctor_free_at=ist(*start, day=day),
        avg_consult_s=600,
    )
    return convo.repo.add_session(s)


async def _in(flow, store, *, text=None, button_id=None, now=None, wa=WA):
    now = now if now is not None else dt(9)
    kind = "button_reply" if button_id else "text"
    await store.record_inbound(
        clinic_id=None, wa_number=wa, wamid=uuid4().hex, kind=kind, payload={}, at=now
    )
    msg = InboundMessage(
        wa_number=wa,
        kind=kind,
        text=text,
        button_id=button_id,
        timestamp=now,
        wamid="x",
        phone_number_id="123",
    )
    await flow.handle(now, msg)


def last(store):
    return store.outbound[-1]


def body(o):
    return o["payload"]["text"]["body"]


def btn_ids(o):
    return [b["reply"]["id"] for b in o["payload"]["interactive"]["action"]["buttons"]]


def list_ids(o):
    return [r["id"] for r in o["payload"]["interactive"]["action"]["sections"][0]["rows"]]


def entries(convo):
    return list(convo.repo.entries.values())


# --------------------------------------------------------------------------- #
def test_happy_booking_hi_via_buttons():
    store, sender, convo, clinic, s, parse, flow = build(lang="hi")
    parse.push(intent="greeting", confidence=0.95)
    run(_in(flow, store, text="namaste"))
    assert last(store)["kind"] == "list"
    assert f"sess:{s.id}" in list_ids(last(store))

    run(_in(flow, store, button_id=f"sess:{s.id}"))
    assert "time:asap" in btn_ids(last(store))

    run(_in(flow, store, button_id="time:asap"))
    assert set(btn_ids(last(store))) == {"profile:self", "profile:family"}

    run(_in(flow, store, button_id="profile:self"))
    conf = last(store)
    assert conf["kind"] == "button"
    assert any(b.startswith("arrived:") for b in btn_ids(conf))  # Arrived button present
    es = entries(convo)
    assert len(es) == 1 and es[0].status == Status.booked


def test_happy_booking_en():
    store, sender, convo, clinic, s, parse, flow = build(lang="en")
    parse.push(intent="book", confidence=0.9)
    run(_in(flow, store, text="I want an appointment"))
    run(_in(flow, store, button_id=f"sess:{s.id}"))
    run(_in(flow, store, button_id="time:asap"))
    run(_in(flow, store, button_id="profile:self"))
    assert len(entries(convo)) == 1


def test_specific_time_booking():
    store, sender, convo, clinic, s, parse, flow = build()
    run(_in(flow, store, button_id=f"sess:{s.id}"))  # -> choosing_time
    parse.push(intent="book", time_pref="19:00", confidence=0.9)
    run(_in(flow, store, text="shaam 7 baje"))  # typed time -> choosing_profile
    assert set(btn_ids(last(store))) == {"profile:self", "profile:family"}
    run(_in(flow, store, button_id="profile:self"))
    e = entries(convo)[0]
    assert e.status == Status.booked
    assert (e.priority_time.hour, e.priority_time.minute) == (13, 30)  # 19:00 IST -> UTC


def test_status_keyword():
    store, sender, convo, clinic, s, parse, flow = build()
    pid = run(convo.get_or_create_patient(clinic.id, WA, "self"))
    e = run(
        engine.book(
            convo.repo,
            dt(9),
            clinic_id=clinic.id,
            session_id=s.id,
            patient_id=pid,
            requested_time=None,
            source=Source.whatsapp,
        )
    ).entry
    run(_in(flow, store, text="kitna time"))
    assert last(store)["kind"] == "text"
    assert str(e.token_number) in body(last(store))


def test_cancel_via_keyword_then_confirm():
    store, sender, convo, clinic, s, parse, flow = build()
    pid = run(convo.get_or_create_patient(clinic.id, WA, "self"))
    e = run(
        engine.book(
            convo.repo,
            dt(9),
            clinic_id=clinic.id,
            session_id=s.id,
            patient_id=pid,
            requested_time=None,
            source=Source.whatsapp,
        )
    ).entry
    run(_in(flow, store, text="cancel"))
    assert set(btn_ids(last(store))) == {"confirmcancel:yes", "confirmcancel:no"}
    run(_in(flow, store, button_id="confirmcancel:yes"))
    assert e.status == Status.cancelled


def test_arrived_button_tap():
    store, sender, convo, clinic, s, parse, flow = build()
    pid = run(convo.get_or_create_patient(clinic.id, WA, "self"))
    e = run(
        engine.book(
            convo.repo,
            dt(9),
            clinic_id=clinic.id,
            session_id=s.id,
            patient_id=pid,
            requested_time=None,
            source=Source.whatsapp,
        )
    ).entry
    run(_in(flow, store, button_id=f"arrived:{e.id}"))
    assert e.status == Status.arrived


def test_family_member_booking():
    store, sender, convo, clinic, s, parse, flow = build()
    run(_in(flow, store, button_id=f"sess:{s.id}"))
    run(_in(flow, store, button_id="time:asap"))
    run(_in(flow, store, button_id="profile:family"))
    assert last(store)["kind"] == "text"  # asked for name
    run(_in(flow, store, text="Mummy"))
    es = entries(convo)
    assert len(es) == 1
    p = convo.repo.patients[es[0].patient_id]
    assert p.profile_name == "Mummy"


def test_overflow_offers_alternatives():
    store, sender, convo, clinic, s, parse, flow = build(cap=1)
    alt = _session(convo, clinic.id, cap=40, name="evening")
    # fill s to cap with a different patient
    other = run(convo.get_or_create_patient(clinic.id, "+919000000099", "self"))
    run(
        engine.book(
            convo.repo,
            dt(9),
            clinic_id=clinic.id,
            session_id=s.id,
            patient_id=other,
            requested_time=None,
            source=Source.whatsapp,
        )
    )
    # WA picks the (now full) session via a stale button, then books
    run(_in(flow, store, button_id=f"sess:{s.id}"))
    run(_in(flow, store, button_id="time:asap"))
    run(_in(flow, store, button_id="profile:self"))
    o = last(store)
    assert o["kind"] == "list"
    assert f"sess:{alt.id}" in list_ids(o)
    assert not any(e.patient_id != other for e in entries(convo))  # WA not booked


def test_medical_question_safe_reply():
    store, sender, convo, clinic, s, parse, flow = build()
    parse.push(intent="medical_question", confidence=0.9)
    run(_in(flow, store, text="mujhe bukhar hai kya karun"))
    from app.wa.templates import prompt

    assert body(last(store)) == prompt("medical_safe", "hi")
    assert not entries(convo)


def test_gibberish_low_confidence_reasks_with_buttons():
    store, sender, convo, clinic, s, parse, flow = build()
    parse.push(intent="other", confidence=0.2)
    run(_in(flow, store, text="asdfghjkl"))
    from app.wa.templates import prompt

    # first send is the low-confidence re-ask; then session list (idle)
    kinds = [o["kind"] for o in store.outbound]
    assert any(
        body(o) == prompt("low_confidence", "hi") for o in store.outbound if o["kind"] == "text"
    )
    assert "list" in kinds


def test_greeting_bypass_llm_raises():
    """Greeting keyword works even when llm.parse raises — no network dependency."""
    store, sender, convo, clinic, s, parse, flow = build(lang="hi")

    async def broken_parse(text, ctx):
        raise RuntimeError("LLM unavailable")

    flow.parse = broken_parse
    run(_in(flow, store, text="hi"))
    assert last(store)["kind"] == "list"
    assert f"sess:{s.id}" in list_ids(last(store))


def test_greeting_variants_all_bypass():
    """All greeting words in the bypass list reach the session list without LLM."""
    for word in ("hello", "namaste", "नमस्ते", "menu", "start", "hey", "hii"):
        store, sender, convo, clinic, s, parse, flow = build(lang="hi")

        async def broken_parse(text, ctx):
            raise RuntimeError("LLM down")

        flow.parse = broken_parse
        run(_in(flow, store, text=word))
        assert last(store)["kind"] == "list", f"greeting word {word!r} did not produce session list"


def test_greeting_resets_mid_flow_no_active_token():
    """'Hi' while in choosing_session (no active token) resets and re-shows sessions."""
    store, sender, convo, clinic, s, parse, flow = build()
    # advance to choosing_session
    run(_in(flow, store, button_id=f"sess:{s.id}"))  # -> choosing_time
    # now send a greeting — no active token, should reset
    run(_in(flow, store, text="hi"))
    assert last(store)["kind"] == "list"


def test_greeting_with_active_token_shows_status_not_session_list():
    """'Hi' with an active booking shows status, does NOT reset or show session list."""
    store, sender, convo, clinic, s, parse, flow = build()
    pid = run(convo.get_or_create_patient(clinic.id, WA, "self"))
    run(
        engine.book(
            convo.repo,
            dt(9),
            clinic_id=clinic.id,
            session_id=s.id,
            patient_id=pid,
            requested_time=None,
            source=Source.whatsapp,
        )
    )
    store.outbound.clear()
    run(_in(flow, store, text="hi"))
    assert len(store.outbound) == 1
    reply = body(last(store))

    # reply uses greeting_has_active prompt — contains token number
    assert "1" in reply  # token number
    assert last(store)["kind"] == "text"


def test_low_confidence_choosing_time_reasks_time_buttons():
    """Gibberish in choosing_time state re-sends the ASAP button (no dead-end)."""
    store, sender, convo, clinic, s, parse, flow = build()
    run(_in(flow, store, button_id=f"sess:{s.id}"))  # -> choosing_time
    store.outbound.clear()
    # LLM returns low confidence
    parse.push(intent="other", confidence=0.1)
    run(_in(flow, store, text="blah blah"))
    kinds = [o["kind"] for o in store.outbound]
    assert "button" in kinds  # ASAP button re-sent
    assert any("time:asap" in btn_ids(o) for o in store.outbound if o["kind"] == "button")


def test_low_confidence_choosing_profile_reasks_profile_buttons():
    """Gibberish in choosing_profile re-sends the self/family buttons."""
    store, sender, convo, clinic, s, parse, flow = build()
    run(_in(flow, store, button_id=f"sess:{s.id}"))
    run(_in(flow, store, button_id="time:asap"))  # -> choosing_profile
    store.outbound.clear()
    parse.push(intent="other", confidence=0.1)
    run(_in(flow, store, text="blah"))
    assert any(
        set(btn_ids(o)) == {"profile:self", "profile:family"}
        for o in store.outbound
        if o["kind"] == "button"
    )


def test_low_confidence_confirm_cancel_reasks_confirm_buttons():
    """Gibberish in confirm_cancel re-sends the yes/no cancel buttons."""
    store, sender, convo, clinic, s, parse, flow = build()
    pid = run(convo.get_or_create_patient(clinic.id, WA, "self"))
    run(
        engine.book(
            convo.repo,
            dt(9),
            clinic_id=clinic.id,
            session_id=s.id,
            patient_id=pid,
            requested_time=None,
            source=Source.whatsapp,
        )
    )
    run(_in(flow, store, text="cancel"))  # -> confirm_cancel
    store.outbound.clear()
    parse.push(intent="other", confidence=0.1)
    run(_in(flow, store, text="idontknow"))
    assert any(
        set(btn_ids(o)) == {"confirmcancel:yes", "confirmcancel:no"}
        for o in store.outbound
        if o["kind"] == "button"
    )


# --------------------------------------------------------------------------- #
# Ambiguous typed times resolve INSIDE the chosen session (Part 1)
# --------------------------------------------------------------------------- #
def _pick(flow, store, session, now):
    """Walk the real entry path: greeting -> session list -> tap a session.

    Going through the list matters: that is where the flow stashes each
    session's window, which is what makes a bare hour resolvable at all.
    """
    run(_in(flow, store, text="hi", now=now))
    run(_in(flow, store, button_id=f"sess:{session.id}", now=now))


def _evening_clinic(cap=40):
    """A clinic whose only bookable session is the 17:00-23:30 evening OPD."""
    store, sender, convo, clinic, _s, parse, flow = build()
    convo.repo.sessions.clear()
    ev = _ist_session(convo, clinic.id, name="evening", start=(17, 0), end=(23, 30), cap=cap)
    return store, convo, clinic, ev, parse, flow


def test_bare_time_resolves_to_the_pm_reading_inside_an_evening_session():
    """'9:30' typed into a 17:00-23:30 session means 21:30, not 09:30."""
    store, convo, clinic, ev, parse, flow = _evening_clinic()
    now = ist(17, 30)
    _pick(flow, store, ev, now)
    parse.push(intent="book", time_pref="09:30", confidence=0.9)
    run(_in(flow, store, text="9:30", now=now))
    run(_in(flow, store, button_id="profile:self", now=now))
    e = entries(convo)[0]
    assert hhmm(e.priority_time) == "21:30"


def test_bare_1130_is_never_silently_clamped_to_the_session_start():
    """The production bug: '11:30' became 5:00 PM with no explanation.

    23:30 sits exactly at end_at so the engine legitimately overflows it to
    another session — what must never happen again is a token quietly issued
    at the session start.
    """
    store, convo, clinic, ev, parse, flow = _evening_clinic()
    _ist_session(
        convo, clinic.id, name="morning", start=(9, 0), end=(13, 0), day=DAY + timedelta(days=1)
    )
    now = ist(23, 10)  # the real booking's clock
    _pick(flow, store, ev, now)
    parse.push(intent="book", time_pref="11:30", confidence=0.9)
    run(_in(flow, store, text="11:30", now=now))
    run(_in(flow, store, button_id="profile:self", now=now))
    for e in entries(convo):
        assert hhmm(e.priority_time) != "17:00", "silently clamped to session start again"


def test_out_of_window_time_reasks_instead_of_clamping():
    """'8 PM' in a 09:00-13:00 morning session: re-ask, don't move them."""
    store, sender, convo, clinic, _s, parse, flow = build()
    convo.repo.sessions.clear()
    mor = _ist_session(convo, clinic.id, name="morning", start=(9, 0), end=(13, 0))
    now = ist(9, 30)
    _pick(flow, store, mor, now)
    store.outbound.clear()
    parse.push(intent="book", time_pref="20:00", confidence=0.9)
    run(_in(flow, store, text="8 PM", now=now))

    said = [body(o) for o in store.outbound if o["kind"] == "text"]
    assert said, "nothing said about the out-of-window time"
    assert "इस सत्र में नहीं" in said[0]
    assert "9:00 AM" in said[0] and "1:00 PM" in said[0]  # the window is stated
    # and it re-offers the time step rather than dead-ending or booking
    assert any("time:asap" in btn_ids(o) for o in store.outbound if o["kind"] == "button")
    assert not entries(convo)


def test_time_typed_before_choosing_a_session_resolves_on_that_sessions_day():
    """'kal subah 10 baje' typed first, then the session picked from the list."""
    store, sender, convo, clinic, _s, parse, flow = build()
    convo.repo.sessions.clear()
    tomorrow = DAY + timedelta(days=1)
    mor = _ist_session(convo, clinic.id, name="morning", start=(9, 0), end=(13, 0), day=tomorrow)
    now = ist(23, 10)
    parse.push(intent="book", time_pref="10:00", confidence=0.9)
    run(_in(flow, store, text="kal subah 10 baje", now=now))
    run(_in(flow, store, button_id=f"sess:{mor.id}", now=now))
    run(_in(flow, store, button_id="profile:self", now=now))
    e = entries(convo)[0]
    assert hhmm(e.priority_time) == "10:00"
    assert e.priority_time.astimezone(IST).date() == tomorrow


def test_session_list_rows_carry_the_date_for_non_today_sessions():
    """Two 'evening' rows on different days must be distinguishable."""
    store, sender, convo, clinic, _s, parse, flow = build()
    convo.repo.sessions.clear()
    _ist_session(convo, clinic.id, name="evening", start=(17, 0), end=(23, 30))
    _ist_session(
        convo, clinic.id, name="evening", start=(17, 0), end=(23, 30), day=DAY + timedelta(days=1)
    )
    run(_in(flow, store, text="hi", now=ist(16, 0)))
    rows = last(store)["payload"]["interactive"]["action"]["sections"][0]["rows"]
    assert len(rows) == 2
    assert rows[0]["description"] != rows[1]["description"]
    assert rows[0]["title"] == "शाम"  # patient-facing name, not the DB's 'evening'
    assert "6 Jul" in rows[1]["description"]  # tomorrow's row is dated


# --------------------------------------------------------------------------- #
# Never move a patient's time silently (Part 2)
# --------------------------------------------------------------------------- #
def test_clamped_booking_explains_itself_before_the_token():
    """Asked for 09:30 at 11:00 — the queue starts now, and we say so."""
    store, sender, convo, clinic, _s, parse, flow = build()
    convo.repo.sessions.clear()
    mor = _ist_session(convo, clinic.id, name="morning", start=(9, 0), end=(13, 0))
    now = ist(11, 0)
    _pick(flow, store, mor, now)
    parse.push(intent="book", time_pref="09:30", confidence=0.9)
    run(_in(flow, store, text="subah 9:30", now=now))
    store.outbound.clear()
    run(_in(flow, store, button_id="profile:self", now=now))

    texts = [body(o) for o in store.outbound if o["kind"] == "text"]
    assert texts, "no explanation sent before the token"
    assert "9:30 AM" in texts[0]
    assert "वह समय निकल चुका है" in texts[0]
    # ...and it precedes the confirmation, which still carries the Arrived button
    assert any(
        any(b.startswith("arrived:") for b in btn_ids(o))
        for o in store.outbound
        if o["kind"] == "button"
    )
    assert hhmm(entries(convo)[0].priority_time) == "11:00"


def test_tomorrow_booking_says_which_day():
    store, sender, convo, clinic, _s, parse, flow = build()
    convo.repo.sessions.clear()
    tomorrow = DAY + timedelta(days=1)
    ev = _ist_session(convo, clinic.id, name="evening", start=(17, 0), end=(23, 30), day=tomorrow)
    now = ist(23, 10)
    run(_in(flow, store, button_id=f"sess:{ev.id}", now=now))
    run(_in(flow, store, button_id="time:asap", now=now))
    store.outbound.clear()
    run(_in(flow, store, button_id="profile:self", now=now))
    texts = [body(o) for o in store.outbound if o["kind"] == "text"]
    assert texts, "next-day booking sent no day notice"
    assert "कल" in texts[0] and "6 Jul" in texts[0]
    assert "शाम" in texts[0]  # session named in Hindi, not 'evening'


def test_same_day_asap_booking_sends_no_notice():
    """Nothing moved and it is today — don't add noise to a clean booking."""
    store, sender, convo, clinic, _s, parse, flow = build()
    convo.repo.sessions.clear()
    mor = _ist_session(convo, clinic.id, name="morning", start=(9, 0), end=(13, 0))
    now = ist(9, 30)
    run(_in(flow, store, button_id=f"sess:{mor.id}", now=now))
    run(_in(flow, store, button_id="time:asap", now=now))
    store.outbound.clear()
    run(_in(flow, store, button_id="profile:self", now=now))
    assert [o["kind"] for o in store.outbound] == ["button"]  # confirmation only


def test_stop_deletes_and_cancels():
    store, sender, convo, clinic, s, parse, flow = build()
    pid = run(convo.get_or_create_patient(clinic.id, WA, "self"))
    e = run(
        engine.book(
            convo.repo,
            dt(9),
            clinic_id=clinic.id,
            session_id=s.id,
            patient_id=pid,
            requested_time=None,
            source=Source.whatsapp,
        )
    ).entry
    run(_in(flow, store, text="STOP"))
    from app.wa.templates import prompt

    assert body(last(store)) == prompt("stop_done", "hi")
    assert e.status == Status.cancelled
    assert pid not in convo.repo.patients  # patient rows deleted
