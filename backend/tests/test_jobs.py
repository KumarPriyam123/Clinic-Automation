"""Scheduler job tests — FakeClock, no network, no real APScheduler.

Drives a scripted session (delay, skip + grace-expiry, cancel-gap, close) and
asserts each proactive notification fires exactly once at the right tick, and
that re-running a job at the same instant sends nothing extra (crash-safety).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, time
from uuid import uuid4

from app import engine
from app.engine.state import Patient, SessionState
from app.jobs.digest import run_digest
from app.jobs.pings import ping_scan
from app.jobs.store import ClinicRow, MemJobs, TimetableRow
from app.jobs.sweep import stamp_daily, sweep_tick
from app.models import SessionStatus, Source, Status
from app.wa.notify import NotificationDispatcher
from app.wa.sender import Sender

A, B, C, D = (f"+91100000000{i}" for i in range(1, 5))


def dt(h, m=0):
    return datetime(2026, 7, 6, h, m, tzinfo=UTC)  # 2026-07-06 is a Monday


def run(coro):
    return asyncio.run(coro)


class CapSender(Sender):
    """Records every send() as (now, wa, template); never hits the network."""

    def __init__(self):
        super().__init__(_NullStore(), token="t", phone_number_id="1", backoff_base=0)
        self.sent: list[tuple[datetime, str, str]] = []

    async def send(
        self, now, wa, *, template_name, ctx, lang="hi", clinic_id=None, force_template=False
    ):
        self.sent.append((now, wa, template_name))
        return {}


class _NullStore:
    async def record_outbound(self, **kw):
        pass

    async def last_inbound_at(self, wa):
        return None


def cnt(sender, template, wa=None):
    return sum(1 for (_, w, t) in sender.sent if t == template and (wa is None or w == wa))


def _mk(backend, now, *, avg=600, cap=40, doctor_free_at=None, end_h=15):
    clinic = ClinicRow(uuid4(), "hi", "C", "Dr", "+9199999")
    backend.add_clinic(clinic)
    s = SessionState(
        id=uuid4(),
        clinic_id=clinic.id,
        date=now.date(),
        name="morning",
        start_at=now,
        end_at=dt(end_h),
        token_cap=cap,
        status=SessionStatus.open,
        doctor_free_at=doctor_free_at or now,
        avg_consult_s=avg,
    )
    backend.repo.add_session(s)
    pats = {}
    for wa in (A, B, C, D):
        p = Patient(id=uuid4(), clinic_id=clinic.id, wa_number=wa)
        backend.repo.add_patient(p)
        pats[wa] = p.id
    return clinic, s, pats


def _book(backend, clinic, sid, pid, now, req=None):
    return run(
        backend.engine_call(
            lambda r: engine.book(
                r,
                now,
                clinic_id=clinic.id,
                session_id=sid,
                patient_id=pid,
                requested_time=req,
                source=Source.whatsapp,
            )
        )
    )


def _entry_id(backend, pid):
    return next(e.id for e in backend.repo.entries.values() if e.patient_id == pid)


def _act(backend, disp, now, factory):
    """Simulate a panel/flow action: run one engine transition + dispatch it."""
    res = run(backend.engine_call(factory))
    run(disp.dispatch(now, res))
    return res


# --------------------------------------------------------------------------- #
def test_scripted_session_each_notification_once():
    backend = MemJobs()
    cap = CapSender()
    disp = NotificationDispatcher(cap, backend.resolver())
    clinic, s, pats = _mk(backend, dt(9))

    _book(backend, clinic, s.id, pats[A], dt(9))  # asap
    _book(backend, clinic, s.id, pats[B], dt(9))  # asap
    _book(backend, clinic, s.id, pats[C], dt(9))  # asap
    _book(backend, clinic, s.id, pats[D], dt(9), req=dt(11))  # future

    # --- tick 1: pre_arrival (A,B,C past lead) + three_away (D at pos 3) ---
    run(ping_scan(backend, disp, dt(9)))
    n = len(cap.sent)
    run(ping_scan(backend, disp, dt(9)))  # idempotent re-run
    assert len(cap.sent) == n
    for wa in (A, B, C):
        assert cnt(cap, "pre_arrival", wa) == 1
    assert cnt(cap, "pre_arrival", D) == 0
    assert cnt(cap, "three_away", D) == 1
    assert cnt(cap, "eta_shift") == 0  # baseline only

    # --- delay 30 min -> eta_shift for the asap trio, once ----------------
    run(backend.engine_call(lambda r: engine.delay_session(r, dt(9, 5), s.id, 30)))
    run(ping_scan(backend, disp, dt(9, 5)))
    n = len(cap.sent)
    run(ping_scan(backend, disp, dt(9, 5)))  # idempotent
    assert len(cap.sent) == n
    for wa in (A, B, C):
        assert cnt(cap, "eta_shift", wa) == 1

    # --- skip: A absent at the front, B arrived -> A skipped, B served ----
    _act(
        backend,
        disp,
        dt(9, 5),
        lambda r: engine.mark_arrived(r, dt(9, 5), _entry_id(backend, pats[B])),
    )
    _act(backend, disp, dt(9, 5), lambda r: engine.next_patient(r, dt(9, 5), s.id))
    assert cnt(cap, "skipped_grace", A) == 1
    assert cnt(cap, "you_are_next", B) == 1

    # --- grace expiry via sweep -> A expired + rebook, once ---------------
    run(sweep_tick(backend, disp, dt(9, 26)))
    n = len(cap.sent)
    run(sweep_tick(backend, disp, dt(9, 26)))  # idempotent
    assert len(cap.sent) == n
    assert cnt(cap, "expired_rebook", A) == 1

    # --- cancel C: the hole before D is real, but D is too far out to offer -
    # D asked for 11:00. Offering them the 9:26 slot would ask them to arrive
    # 94 minutes early, which is the P8.6 defect. The pull-forward horizon
    # (default 30 min, measured against priority_time) suppresses it.
    # In-horizon dispatch is covered by test_gap_offer_dispatched_once below.
    _act(
        backend, disp, dt(9, 26), lambda r: engine.cancel(r, dt(9, 26), _entry_id(backend, pats[C]))
    )
    assert cnt(cap, "gap_offer", D) == 0

    # --- close at end_at -> pending (B in-consult, D) expire + rebook -----
    run(sweep_tick(backend, disp, dt(15, 1)))
    n = len(cap.sent)
    run(sweep_tick(backend, disp, dt(15, 1)))  # idempotent
    assert len(cap.sent) == n
    assert cnt(cap, "expired_rebook", D) == 1  # pending future patient expires
    assert backend.repo.sessions[s.id].status == SessionStatus.closed


def test_gap_offer_dispatched_once():
    """A gap offer inside the horizon reaches WhatsApp exactly once.

    Guards the dispatch path that test_scripted_session_each_notification_once
    used to cover before the horizon (correctly) suppressed its 94-minute-early
    offer.
    """
    backend = MemJobs()
    cap = CapSender()
    disp = NotificationDispatcher(cap, backend.resolver())
    clinic, s, pats = _mk(backend, dt(9))

    near = _book(backend, clinic, s.id, pats[A], dt(9)).entry  # asap -> seen first
    soon = _book(backend, clinic, s.id, pats[B], dt(9), req=dt(9, 45)).entry

    # doctor actually works: A arrives, is called in, and finishes at 9:20
    _act(backend, disp, dt(9), lambda r: engine.mark_arrived(r, dt(9), near.id))
    _act(backend, disp, dt(9), lambda r: engine.next_patient(r, dt(9), s.id))
    _act(backend, disp, dt(9, 20), lambda r: engine.next_patient(r, dt(9, 20), s.id))

    # 9:45 is 25 min out — inside the 30 min horizon
    _act(backend, disp, dt(9, 20), lambda r: engine.gap_check(r, dt(9, 20), s.id))
    assert cnt(cap, "gap_offer", B) == 1
    assert soon.gap_offered_at == dt(9, 20)

    # re-running must not send a second offer (one offer per patient per session)
    n = len(cap.sent)
    _act(backend, disp, dt(9, 21), lambda r: engine.gap_check(r, dt(9, 21), s.id))
    assert len(cap.sent) == n
    assert cnt(cap, "gap_offer", B) == 1


def test_stamp_sessions_idempotent():
    backend = MemJobs()
    clinic = ClinicRow(uuid4(), "hi", "C", "Dr", "+9199999")
    backend.add_clinic(clinic)
    wd = dt(9).weekday()
    backend.timetable = [
        TimetableRow(clinic.id, wd, "morning", time(9, 0), time(13, 0), 40),
        TimetableRow(clinic.id, wd, "evening", time(17, 0), time(21, 0), 40),
    ]
    created = run(stamp_daily(backend, dt(9)))
    assert len(created) == 2  # today matches both rows (today+2 only re-hits this weekday once)
    again = run(stamp_daily(backend, dt(9)))
    assert again == []  # conflict-free re-run creates nothing


def test_doctor_digest_once_per_clinic():
    backend = MemJobs()
    cap = CapSender()
    clinic, s, pats = _mk(backend, dt(9))
    # 2 seen, 1 no-show
    for wa, st in ((A, Status.done), (B, Status.done), (C, Status.expired)):
        e = _book(backend, clinic, s.id, pats[wa], dt(9)).entry
        e.status = st
    sent = run(run_digest(backend, cap, dt(21, 45)))
    assert sent == 1
    assert cnt(cap, "doctor_digest", "+9199999") == 1
