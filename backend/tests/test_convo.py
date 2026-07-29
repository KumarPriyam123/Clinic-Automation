"""Conversation flow tests — scripted dialogues, LLM mocked (no network).

Asserts the flow's handling of each inbound (button or free text + returned
Intent): the sends it emits and the resulting engine state in MemConvo.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

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
            convo.repo, dt(9),
            clinic_id=clinic.id, session_id=s.id,
            patient_id=pid, requested_time=None, source=Source.whatsapp,
        )
    )
    store.outbound.clear()
    run(_in(flow, store, text="hi"))
    assert len(store.outbound) == 1
    reply = body(last(store))
    from app.wa.templates import prompt
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
        for o in store.outbound if o["kind"] == "button"
    )


def test_low_confidence_confirm_cancel_reasks_confirm_buttons():
    """Gibberish in confirm_cancel re-sends the yes/no cancel buttons."""
    store, sender, convo, clinic, s, parse, flow = build()
    pid = run(convo.get_or_create_patient(clinic.id, WA, "self"))
    run(
        engine.book(
            convo.repo, dt(9),
            clinic_id=clinic.id, session_id=s.id,
            patient_id=pid, requested_time=None, source=Source.whatsapp,
        )
    )
    run(_in(flow, store, text="cancel"))  # -> confirm_cancel
    store.outbound.clear()
    parse.push(intent="other", confidence=0.1)
    run(_in(flow, store, text="idontknow"))
    assert any(
        set(btn_ids(o)) == {"confirmcancel:yes", "confirmcancel:no"}
        for o in store.outbound if o["kind"] == "button"
    )


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
