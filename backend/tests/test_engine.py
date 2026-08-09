"""Queue engine tests — pure, deterministic, FakeClock via injected `now`.

Runs entirely against the in-memory MemRepo: no DB, no network. Covers the
17 scenarios from the P2 build prompt (t1–t17).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app import engine
from app.engine.repo import MemRepo
from app.engine.state import Entry, GapPolicy, Patient, SessionState
from app.models import SessionStatus, Source, Status


def dt(h: int, m: int = 0, s: int = 0) -> datetime:
    return datetime(2026, 7, 3, h, m, s, tzinfo=UTC)


def run(coro):
    return asyncio.run(coro)


def open_session(
    repo: MemRepo, now: datetime, *, avg=420, cap=40, free=None, end=None
) -> SessionState:
    s = SessionState(
        id=uuid4(),
        clinic_id=uuid4(),
        date=now.date(),
        name="morning",
        start_at=now,
        end_at=end or now + timedelta(hours=6),
        token_cap=cap,
        status=SessionStatus.open,
        doctor_free_at=now if free is None else free,
        avg_consult_s=avg,
    )
    return repo.add_session(s)


def patient(repo: MemRepo, clinic_id, i: int, profile="self") -> Patient:
    return repo.add_patient(
        Patient(id=uuid4(), clinic_id=clinic_id, wa_number=f"+9190000{i:05d}", profile_name=profile)
    )


def do_book(repo, s, p, now, req=None, source=Source.whatsapp):
    return run(
        engine.book(
            repo,
            now,
            clinic_id=s.clinic_id,
            session_id=s.id,
            patient_id=p.id,
            requested_time=req,
            source=source,
        )
    )


def ordered(repo, sid):
    return sorted(run(repo.list_entries(sid)), key=Entry.order_key)


# --------------------------------------------------------------------------- #
def test_t1_priority_time_order_not_booking_order():
    repo = MemRepo()
    s = open_session(repo, dt(9))
    p1, p2, p3 = (patient(repo, s.clinic_id, i) for i in (1, 2, 3))
    do_book(repo, s, p1, dt(9), req=dt(12))
    do_book(repo, s, p2, dt(9), req=dt(11))
    do_book(repo, s, p3, dt(9), req=dt(10))
    assert [e.priority_time for e in ordered(repo, s.id)] == [dt(10), dt(11), dt(12)]


def test_t2_cancel_middle_shifts_up_with_notifications():
    repo = MemRepo()
    s = open_session(repo, dt(10), avg=900, free=dt(10))
    ps = [patient(repo, s.clinic_id, i) for i in (1, 2, 3)]
    e = [do_book(repo, s, ps[i], dt(10, 0, i)).entry for i in range(3)]
    before = e[2].eta
    res = run(engine.cancel(repo, dt(10), e[1].id))
    assert e[1].status == Status.cancelled
    assert e[2].eta < before  # third patient moved up
    assert any(n.type == engine.NotificationType.eta_shift for n in res.notifications)


def test_t3_requested_past_time_clamped_to_now():
    repo = MemRepo()
    s = open_session(repo, dt(10))
    p = patient(repo, s.clinic_id, 1)
    r = do_book(repo, s, p, dt(10), req=dt(9))
    assert r.entry.priority_time == dt(10)


def test_t4_two_now_bookings_fifo_by_booked_at():
    repo = MemRepo()
    s = open_session(repo, dt(10))
    p1, p2 = patient(repo, s.clinic_id, 1), patient(repo, s.clinic_id, 2)
    a = do_book(repo, s, p1, dt(10, 0, 0)).entry
    b = do_book(repo, s, p2, dt(10, 0, 1)).entry
    assert [x.id for x in ordered(repo, s.id)] == [a.id, b.id]


def test_t5_walkin_lands_ahead_of_future_bookings():
    repo = MemRepo()
    s = open_session(repo, dt(10))
    p1, p2 = patient(repo, s.clinic_id, 1), patient(repo, s.clinic_id, 2)
    do_book(repo, s, p1, dt(10), req=dt(11))
    walk = do_book(repo, s, p2, dt(10), source=Source.walkin).entry
    assert ordered(repo, s.id)[0].id == walk.id


def test_t6_eta_respects_doctor_free_at_never_before_priority():
    repo = MemRepo()
    s = open_session(repo, dt(10), avg=600, free=dt(10, 30))
    p1, p2 = patient(repo, s.clinic_id, 1), patient(repo, s.clinic_id, 2)
    a = do_book(repo, s, p1, dt(10), req=dt(10)).entry
    b = do_book(repo, s, p2, dt(10), req=dt(10, 5)).entry
    assert a.eta == dt(10, 30)  # doctor_free_at, not the 10:00 target
    assert a.eta >= a.priority_time and b.eta >= b.priority_time
    assert b.eta == dt(10, 40)


def test_t7_next_skips_absent_front_serves_arrived():
    repo = MemRepo()
    s = open_session(repo, dt(10), avg=600)
    pa, pb = patient(repo, s.clinic_id, 1), patient(repo, s.clinic_id, 2)
    a = do_book(repo, s, pa, dt(10), req=dt(10)).entry
    b = do_book(repo, s, pb, dt(10), req=dt(10, 5)).entry
    run(engine.mark_arrived(repo, dt(10), b.id))
    res = run(engine.next_patient(repo, dt(10), s.id))
    assert a.status == Status.skipped and a.grace_until is not None
    assert b.status == Status.in_consult
    types = {n.type for n in res.notifications}
    assert engine.NotificationType.skipped_grace in types
    assert engine.NotificationType.you_are_next in types


def test_t8_arrived_within_grace_served_next():
    repo = MemRepo()
    s = open_session(repo, dt(10), avg=600)
    pa, pb = patient(repo, s.clinic_id, 1), patient(repo, s.clinic_id, 2)
    a = do_book(repo, s, pa, dt(10), req=dt(10)).entry
    b = do_book(repo, s, pb, dt(10), req=dt(10, 5)).entry
    run(engine.mark_arrived(repo, dt(10), b.id))
    run(engine.next_patient(repo, dt(10), s.id))  # a skipped, b in consult
    run(engine.arrived_during_grace(repo, dt(10, 5), a.id))
    run(engine.next_patient(repo, dt(10, 10), s.id))  # finish b, serve a next
    assert b.status == Status.done
    assert a.status == Status.in_consult


def test_t9_grace_expiry_via_sweep():
    repo = MemRepo()
    s = open_session(repo, dt(10), avg=600)
    pa, pb = patient(repo, s.clinic_id, 1), patient(repo, s.clinic_id, 2)
    a = do_book(repo, s, pa, dt(10), req=dt(10)).entry
    b = do_book(repo, s, pb, dt(10), req=dt(10, 5)).entry
    run(engine.mark_arrived(repo, dt(10), b.id))
    run(engine.next_patient(repo, dt(10), s.id))  # a -> skipped, grace_until 10:20
    res = run(engine.sweep(repo, dt(10, 21)))
    assert a.status == Status.expired
    assert repo.patients[pa.id].strikes == 1
    assert any(n.type == engine.NotificationType.expired_rebook for n in res.notifications)


def test_t10_skip_guard_holds_when_nobody_arrived():
    repo = MemRepo()
    s = open_session(repo, dt(10))
    pa, pb = patient(repo, s.clinic_id, 1), patient(repo, s.clinic_id, 2)
    a = do_book(repo, s, pa, dt(10), req=dt(10)).entry
    b = do_book(repo, s, pb, dt(10), req=dt(10, 5)).entry
    res = run(engine.next_patient(repo, dt(10), s.id))
    assert res.entry is None
    assert a.status == Status.booked and b.status == Status.booked


def test_t11_cancel_gap_autopulls_arrived():
    repo = MemRepo()
    s = open_session(repo, dt(10), avg=600, free=dt(10))
    px, py = patient(repo, s.clinic_id, 1), patient(repo, s.clinic_id, 2)
    x = do_book(repo, s, px, dt(10), req=dt(10)).entry
    y = do_book(repo, s, py, dt(10), req=dt(11)).entry
    run(engine.mark_arrived(repo, dt(10), y.id))
    run(engine.cancel(repo, dt(10), x.id))
    assert y.priority_time == dt(10)  # pulled forward to now


def test_t12_gap_offer_accept_and_expiry():
    repo = MemRepo()
    s = open_session(repo, dt(10))
    pz, pw = patient(repo, s.clinic_id, 1), patient(repo, s.clinic_id, 2)
    z = do_book(repo, s, pz, dt(10), req=dt(11)).entry
    w = do_book(repo, s, pw, dt(10), req=dt(11, 30)).entry
    z.gap_offered_at = dt(10)
    w.gap_offered_at = dt(10)
    run(engine.accept_gap_offer(repo, dt(10, 3), z.id))
    assert z.priority_time == dt(10, 3) and z.gap_offered_at is None
    run(engine.accept_gap_offer(repo, dt(10, 6), w.id))  # > 5 min -> expired
    assert w.priority_time == dt(11, 30)  # unchanged


def test_t13_overflow_suggests_alternatives():
    repo = MemRepo()
    s = open_session(repo, dt(10), cap=1)
    alt = open_session(repo, dt(10), cap=40)
    alt.clinic_id = s.clinic_id  # same clinic, has space
    p1, p2 = patient(repo, s.clinic_id, 1), patient(repo, s.clinic_id, 2)
    do_book(repo, s, p1, dt(10))
    res = do_book(repo, s, p2, dt(10))
    assert res.overflow is not None and res.overflow.reason == "cap"
    assert any(a.session_id == alt.id for a in res.overflow.alternatives)


def test_t13b_overflow_eta_past_end():
    """Queue depth pushes projected ETA past session end -> OverflowSuggestion."""
    repo = MemRepo()
    # 30-min avg, session ends at 10:35 — 3rd patient's ETA = 11:00 > 10:35
    s = open_session(repo, dt(10), cap=40, avg=1800, end=dt(10, 35))
    alt = open_session(repo, dt(10), cap=40)
    alt.clinic_id = s.clinic_id
    p1, p2, p3 = (patient(repo, s.clinic_id, i) for i in (1, 2, 3))
    do_book(repo, s, p1, dt(10, 0, 0))  # ETA 10:00, clock -> 10:30
    do_book(repo, s, p2, dt(10, 0, 1))  # ETA 10:30, clock -> 11:00
    res = do_book(repo, s, p3, dt(10, 0, 2))  # projected ETA 11:00 >= end 10:35
    assert res.overflow is not None and res.overflow.reason == "past_end"
    assert any(a.session_id == alt.id for a in res.overflow.alternatives)


def test_asap_into_future_session_uses_start_at():
    """ASAP booking into a not-yet-started session uses session.start_at as priority_time."""
    repo = MemRepo()
    s = SessionState(
        id=uuid4(),
        clinic_id=uuid4(),
        date=dt(10).date(),
        name="morning",
        start_at=dt(10),
        end_at=dt(16),
        token_cap=40,
        status=SessionStatus.scheduled,
        avg_consult_s=420,
    )
    repo.add_session(s)
    p = patient(repo, s.clinic_id, 1)
    res = do_book(repo, s, p, dt(8))  # book 2h before session start, ASAP
    assert res.entry.priority_time == dt(10)


def test_asap_into_running_session_uses_now():
    """ASAP into an already-running session uses now (session.start_at is in the past)."""
    repo = MemRepo()
    s = open_session(repo, dt(9))  # session running since 09:00
    p = patient(repo, s.clinic_id, 1)
    res = do_book(repo, s, p, dt(10))  # book at 10:00 ASAP
    assert res.entry.priority_time == dt(10)


def test_specific_time_before_session_start_clamped():
    """A specific time before session start is clamped to session.start_at."""
    repo = MemRepo()
    s = SessionState(
        id=uuid4(),
        clinic_id=uuid4(),
        date=dt(10).date(),
        name="morning",
        start_at=dt(10),
        end_at=dt(16),
        token_cap=40,
        status=SessionStatus.scheduled,
        avg_consult_s=420,
    )
    repo.add_session(s)
    p = patient(repo, s.clinic_id, 1)
    res = do_book(repo, s, p, dt(8), req=dt(8, 0))  # requested 08:00 for 10:00 session
    assert res.entry.priority_time == dt(10)  # clamped to session start


def test_t14_second_active_token_same_number_rejected():
    repo = MemRepo()
    s = open_session(repo, dt(10))
    p = patient(repo, s.clinic_id, 1, profile="self")
    p_family = patient(repo, s.clinic_id, 1, profile="mummy")  # same wa_number
    do_book(repo, s, p, dt(10))
    with pytest.raises(engine.DuplicateActiveToken):
        do_book(repo, s, p_family, dt(10))


def test_t15_emergency_insert_front_shifts_others():
    repo = MemRepo()
    s = open_session(repo, dt(10), avg=900, free=dt(10))
    p1, p2, pe = (patient(repo, s.clinic_id, i) for i in (1, 2, 3))
    a = do_book(repo, s, p1, dt(10, 0, 0)).entry
    b = do_book(repo, s, p2, dt(10, 0, 1)).entry
    res = run(engine.emergency_insert(repo, dt(10), s.id, pe.id))
    assert ordered(repo, s.id)[0].id == res.entry.id
    assert res.entry.priority_time < a.priority_time and res.entry.priority_time < b.priority_time
    assert any(n.type == engine.NotificationType.eta_shift for n in res.notifications)


def test_t16_delay_session_shifts_all_etas():
    repo = MemRepo()
    s = open_session(repo, dt(10), avg=600, free=dt(10))
    p1, p2 = patient(repo, s.clinic_id, 1), patient(repo, s.clinic_id, 2)
    a = do_book(repo, s, p1, dt(10)).entry
    b = do_book(repo, s, p2, dt(10)).entry
    before = {a.id: a.eta, b.id: b.eta}
    res = run(engine.delay_session(repo, dt(10), s.id, 30))
    assert a.eta == before[a.id] + timedelta(minutes=30)
    assert b.eta == before[b.id] + timedelta(minutes=30)
    shifted = {n.entry_id for n in res.notifications if n.type == engine.NotificationType.eta_shift}
    assert {a.id, b.id} <= shifted


def test_t17_close_expires_pending_persists_avg():
    repo = MemRepo()
    s = open_session(repo, dt(10), avg=420, free=dt(10))
    pa, pb = patient(repo, s.clinic_id, 1), patient(repo, s.clinic_id, 2)
    a = do_book(repo, s, pa, dt(10)).entry
    run(engine.mark_arrived(repo, dt(10), a.id))
    run(engine.next_patient(repo, dt(10), s.id))  # serve a (consult_start 10:00)
    run(engine.next_patient(repo, dt(10, 10), s.id))  # finish a, actual 600s
    assert s.avg_consult_s == 474  # round(0.7*420 + 0.3*600)
    b = do_book(repo, s, pb, dt(10, 10)).entry  # still pending
    res = run(engine.close_session(repo, dt(10, 20), s.id))
    assert b.status == Status.expired
    assert s.status == SessionStatus.closed
    assert s.avg_consult_s == 474
    assert any(n.type == engine.NotificationType.expired_rebook for n in res.notifications)


# --------------------------------------------------------------------------- #
# A session whose end_at has passed cannot be made live again.
#
# The 60s sweep closes every open/paused session past its end_at — that is
# correct and stays. What was wrong is that the panel *accepted* a reopen on
# such a session, showed success, and then the sweep silently undid it a minute
# later, so the button looked broken.
# --------------------------------------------------------------------------- #
def test_reopen_rejects_a_session_whose_time_has_passed():
    repo = MemRepo()
    s = open_session(repo, dt(9), end=dt(13))
    run(engine.close_session(repo, dt(13), s.id))
    assert s.status == SessionStatus.closed
    with pytest.raises(engine.SessionEnded):
        run(engine.reopen_session(repo, dt(13, 5), s.id))
    assert s.status == SessionStatus.closed  # and nothing was half-applied


def test_reopen_still_works_before_end_at():
    """A genuine mis-tap mid-session must still be recoverable."""
    repo = MemRepo()
    s = open_session(repo, dt(9), end=dt(13))
    run(engine.close_session(repo, dt(11), s.id))
    run(engine.reopen_session(repo, dt(11, 1), s.id))
    assert s.status == SessionStatus.open


def test_start_and_resume_reject_a_session_whose_time_has_passed():
    repo = MemRepo()
    s = open_session(repo, dt(9), end=dt(13))
    s.status = SessionStatus.scheduled
    with pytest.raises(engine.SessionEnded):
        run(engine.open_session(repo, dt(13, 5), s.id))
    s.status = SessionStatus.paused
    with pytest.raises(engine.SessionEnded):
        run(engine.resume_session(repo, dt(13, 5), s.id))


def test_sweep_close_still_wins_after_end_at():
    """Guard rails added above must not weaken the auto-close itself."""
    repo = MemRepo()
    s = open_session(repo, dt(9), end=dt(13))
    run(engine.close_session(repo, dt(13), s.id))
    assert s.status == SessionStatus.closed


# --------------------------------------------------------------------------- #
# book() reports what it granted, so the patient can be told (rule 1 clamp is
# correct; applying it silently is what breaks trust).
# --------------------------------------------------------------------------- #
def test_booking_info_flags_a_clamp_to_the_session_start():
    repo = MemRepo()
    s = open_session(repo, dt(10), end=dt(16))  # starts at 10:00
    p = patient(repo, s.clinic_id, 1)
    res = do_book(repo, s, p, dt(9), req=dt(8))  # asked 08:00, session opens 10:00
    assert res.booking.adjust_reason == "session_start"
    assert res.booking.requested == dt(8)
    assert res.booking.granted == dt(10)
    assert res.booking.session_date == dt(10).date()


def test_booking_info_flags_a_pull_to_now_mid_session():
    repo = MemRepo()
    s = open_session(repo, dt(9), end=dt(16))
    p = patient(repo, s.clinic_id, 1)
    res = do_book(repo, s, p, dt(11), req=dt(9, 30))  # that slot is long gone
    assert res.booking.adjust_reason == "now"
    assert res.booking.granted == dt(11)


def test_booking_info_is_silent_when_nothing_moved():
    repo = MemRepo()
    s = open_session(repo, dt(9), end=dt(16))
    p1, p2 = patient(repo, s.clinic_id, 1), patient(repo, s.clinic_id, 2)
    on_time = do_book(repo, s, p1, dt(9), req=dt(11))
    assert on_time.booking.adjust_reason is None
    asap = do_book(repo, s, p2, dt(9), req=None)
    assert asap.booking.adjust_reason is None and asap.booking.requested is None


def test_booking_info_ignores_a_move_under_ten_minutes():
    """Don't nag about a 5-minute shift — only a material one."""
    repo = MemRepo()
    s = open_session(repo, dt(10), end=dt(16))
    p = patient(repo, s.clinic_id, 1)
    res = do_book(repo, s, p, dt(9), req=dt(9, 55))
    assert res.booking.granted == dt(10)
    assert res.booking.adjust_reason is None


# --------------------------------------------------------------------------- #
# P8.6 — gap-offer horizon + "doctor is actually working" guard
#
# Observed defect: an evening session opened 17:00, two patients booked ~19:00
# and got 19:05 / 19:12. The first cancelled at 17:30 and the second was offered
# 17:30 — 90 minutes before the time they chose. `17:30` was just `now`.
#
# That gap was not created by the cancellation; it was the empty stretch before
# anyone had booked. The cancel only triggered re-evaluation of a hole that was
# always there.
# --------------------------------------------------------------------------- #
def _gap_offers(res):
    """gap_offer notifications emitted by an EngineResult."""
    from app.engine.results import NotificationType

    return [n for n in res.notifications if n.type == NotificationType.gap_offer]


def _evening_session(repo):
    """Opens 17:00, two patients targeting ~19:00 — the reported scenario."""
    s = open_session(repo, dt(17), avg=420, free=dt(17), end=dt(21))
    p1, p2 = patient(repo, s.clinic_id, 1), patient(repo, s.clinic_id, 2)
    a = do_book(repo, s, p1, dt(17), req=dt(19)).entry
    b = do_book(repo, s, p2, dt(17), req=dt(19, 12)).entry
    return s, a, b


def test_gap_no_offer_before_doctor_has_worked():
    """The reported bug: cancel at 17:30 must NOT offer 17:30 to a 19:12 patient."""
    repo = MemRepo()
    s, a, b = _evening_session(repo)
    res = run(engine.cancel(repo, dt(17, 30), a.id))
    assert _gap_offers(res) == []
    assert b.gap_offered_at is None
    assert b.priority_time == dt(19, 12)  # untouched


def test_gap_offer_inside_horizon_is_emitted():
    """Doctor finishes at 18:40, next target 19:00 — a 20 min pull-forward."""
    repo = MemRepo()
    s = open_session(repo, dt(17), avg=420, free=dt(17), end=dt(21))
    p1, p2 = patient(repo, s.clinic_id, 1), patient(repo, s.clinic_id, 2)
    seen = do_book(repo, s, p1, dt(17), req=dt(18)).entry
    later = do_book(repo, s, p2, dt(17), req=dt(19)).entry

    # doctor actually works: call the first patient in, then finish at 18:40
    run(engine.mark_arrived(repo, dt(18), seen.id))
    run(engine.next_patient(repo, dt(18), s.id))
    run(engine.next_patient(repo, dt(18, 40), s.id))  # consult ends 18:40
    res = run(engine.gap_check(repo, dt(18, 40), s.id))

    assert s.consults_done == 1
    offers = _gap_offers(res)
    assert [n.entry_id for n in offers] == [later.id]
    assert later.gap_offered_at == dt(18, 40)


def test_gap_offer_outside_horizon_is_suppressed():
    """Same, but the next patient asked for 19:30 — a 50 min pull-forward."""
    repo = MemRepo()
    s = open_session(repo, dt(17), avg=420, free=dt(17), end=dt(21))
    p1, p2 = patient(repo, s.clinic_id, 1), patient(repo, s.clinic_id, 2)
    seen = do_book(repo, s, p1, dt(17), req=dt(18)).entry
    later = do_book(repo, s, p2, dt(17), req=dt(19, 30)).entry

    run(engine.mark_arrived(repo, dt(18), seen.id))
    run(engine.next_patient(repo, dt(18), s.id))
    run(engine.next_patient(repo, dt(18, 40), s.id))  # consult ends 18:40
    res = run(engine.gap_check(repo, dt(18, 40), s.id))

    assert s.consults_done == 1
    assert _gap_offers(res) == []
    assert later.gap_offered_at is None
    assert later.priority_time == dt(19, 30)


def test_gap_horizon_is_measured_against_priority_time_not_eta():
    """The horizon keys off what the patient asked for, not the drifting eta.

    Rule 2 clamps eta to `max(clock, priority_time)`, so an eta only ever drifts
    LATER than the requested time. Here the second waiting patient asked for
    19:05 (25 min out, inside the 30 min horizon) but their eta has been pushed
    to ~19:33 by the consult ahead of them (53 min out, outside it). They must
    still be offered: the requested time is what they planned their day around.
    """
    repo = MemRepo()
    s = open_session(repo, dt(17), avg=1800, free=dt(17), end=dt(22))
    p1, p2, p3 = (patient(repo, s.clinic_id, i) for i in (1, 2, 3))
    seen = do_book(repo, s, p1, dt(17), req=dt(18)).entry
    first = do_book(repo, s, p2, dt(17), req=dt(19)).entry
    second = do_book(repo, s, p3, dt(17), req=dt(19, 5)).entry

    run(engine.mark_arrived(repo, dt(18), seen.id))
    run(engine.next_patient(repo, dt(18), s.id))
    run(engine.next_patient(repo, dt(18, 40), s.id))  # consult ends 18:40
    res = run(engine.gap_check(repo, dt(18, 40), s.id))

    # eta has drifted well outside the horizon; priority_time has not
    assert second.eta is not None
    assert second.eta - dt(18, 40) > timedelta(minutes=30)
    assert second.priority_time - dt(18, 40) <= timedelta(minutes=30)

    offered = {n.entry_id for n in _gap_offers(res)}
    assert first.id in offered
    assert second.id in offered, "horizon was measured against eta, not priority_time"


def test_gap_arrived_autopull_ignores_the_horizon():
    """Someone in the waiting room only benefits; the horizon must not apply."""
    repo = MemRepo()
    s = open_session(repo, dt(17), avg=420, free=dt(17), end=dt(21))
    p1, p2 = patient(repo, s.clinic_id, 1), patient(repo, s.clinic_id, 2)
    a = do_book(repo, s, p1, dt(17), req=dt(17, 30)).entry
    far = do_book(repo, s, p2, dt(17), req=dt(20)).entry  # 3h out, way past 30 min

    run(engine.mark_arrived(repo, dt(17, 30), far.id))
    run(engine.cancel(repo, dt(17, 30), a.id))

    assert far.priority_time == dt(17, 30)  # pulled forward regardless


def test_gap_offers_disabled_suppresses_the_offer_only():
    """`gap_offers` governs the remote OFFER, not the ARRIVED auto-pull.

    P8.6 implemented this literally as "nothing emitted on any path" and made
    the switch no-op the whole gap check. That was wrong: the setting is about
    unsolicited patient messaging, while the auto-pull sends nothing at all and
    merely calls someone already in the waiting room a few minutes earlier.
    Coupling them let a messaging preference silently degrade throughput.
    """
    repo = MemRepo()
    repo.gap_policy = GapPolicy(offers_enabled=False)

    # offer path: doctor has worked and the next patient is inside the horizon
    s = open_session(repo, dt(17), avg=420, free=dt(17), end=dt(21))
    p1, p2 = patient(repo, s.clinic_id, 1), patient(repo, s.clinic_id, 2)
    seen = do_book(repo, s, p1, dt(17), req=dt(18)).entry
    later = do_book(repo, s, p2, dt(17), req=dt(19)).entry
    run(engine.mark_arrived(repo, dt(18), seen.id))
    run(engine.next_patient(repo, dt(18), s.id))
    run(engine.next_patient(repo, dt(18, 40), s.id))  # consult ends 18:40
    res = run(engine.gap_check(repo, dt(18, 40), s.id))
    assert _gap_offers(res) == []
    assert later.gap_offered_at is None

    # auto-pull path: an ARRIVED patient IS still pulled forward
    repo2 = MemRepo()
    repo2.gap_policy = GapPolicy(offers_enabled=False)
    s2 = open_session(repo2, dt(17), avg=420, free=dt(17), end=dt(21))
    q1, q2 = patient(repo2, s2.clinic_id, 1), patient(repo2, s2.clinic_id, 2)
    x = do_book(repo2, s2, q1, dt(17), req=dt(17, 30)).entry
    y = do_book(repo2, s2, q2, dt(17), req=dt(20)).entry
    run(engine.mark_arrived(repo2, dt(17, 30), y.id))
    res2 = run(engine.cancel(repo2, dt(17, 30), x.id))
    assert y.priority_time == dt(17, 30), "auto-pull was disabled by a messaging toggle"
    assert _gap_offers(res2) == []  # and still no offer, on any path


def test_gap_offers_disabled_emits_no_offer_on_any_path():
    """The half of the P8.6 assertion that survives: no gap_offer is ever sent."""
    repo = MemRepo()
    repo.gap_policy = GapPolicy(offers_enabled=False)
    s = open_session(repo, dt(17), avg=420, free=dt(17), end=dt(21))
    p1, p2, p3 = (patient(repo, s.clinic_id, i) for i in (1, 2, 3))
    seen = do_book(repo, s, p1, dt(17), req=dt(18)).entry
    a = do_book(repo, s, p2, dt(17), req=dt(19)).entry
    b = do_book(repo, s, p3, dt(17), req=dt(19, 10)).entry

    run(engine.mark_arrived(repo, dt(18), seen.id))
    run(engine.next_patient(repo, dt(18), s.id))
    res_next = run(engine.next_patient(repo, dt(18, 40), s.id))
    res_gap = run(engine.gap_check(repo, dt(18, 40), s.id))
    res_cancel = run(engine.cancel(repo, dt(18, 41), a.id))

    for res in (res_next, res_gap, res_cancel):
        assert _gap_offers(res) == []
    assert a.gap_offered_at is None and b.gap_offered_at is None


def test_gap_horizon_is_per_clinic_configurable():
    """A clinic may widen the horizon; 50 min is inside a 60 min setting."""
    repo = MemRepo()
    repo.gap_policy = GapPolicy(pull_forward_max=timedelta(minutes=60))
    s = open_session(repo, dt(17), avg=420, free=dt(17), end=dt(21))
    p1, p2 = patient(repo, s.clinic_id, 1), patient(repo, s.clinic_id, 2)
    seen = do_book(repo, s, p1, dt(17), req=dt(18)).entry
    later = do_book(repo, s, p2, dt(17), req=dt(19, 30)).entry

    run(engine.mark_arrived(repo, dt(18), seen.id))
    run(engine.next_patient(repo, dt(18), s.id))
    run(engine.next_patient(repo, dt(18, 40), s.id))  # consult ends 18:40
    res = run(engine.gap_check(repo, dt(18, 40), s.id))

    assert [n.entry_id for n in _gap_offers(res)] == [later.id]


def test_gap_offer_ttl_is_per_clinic_configurable():
    repo = MemRepo()
    repo.gap_policy = GapPolicy(offer_ttl=timedelta(minutes=15))
    s = open_session(repo, dt(10))
    p = patient(repo, s.clinic_id, 1)
    e = do_book(repo, s, p, dt(10), req=dt(11)).entry
    e.gap_offered_at = dt(10)
    run(engine.accept_gap_offer(repo, dt(10, 12), e.id))  # past the 5 min default
    assert e.priority_time == dt(10, 12)  # accepted under the 15 min setting
