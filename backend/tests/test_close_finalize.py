"""Close/cancel must finalize the in-consult patient (bug fix).

Ending the day with a patient still in the room is the NORMAL path. Before the
fix, close/cancel left them stuck in_consult forever — duration uncounted,
avg_consult_s unlearned, consults_done short. These tests pin the fix + the
reopen recovery, MemRepo + injected `now` (pure, no DB).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app import engine
from app.engine import NotificationType
from app.engine.repo import MemRepo
from app.engine.state import Patient, SessionState
from app.models import SessionStatus, Source, Status


def dt(h: int, m: int = 0, s: int = 0) -> datetime:
    return datetime(2026, 7, 3, h, m, s, tzinfo=UTC)


def run(coro):
    return asyncio.run(coro)


def open_session(repo: MemRepo, now: datetime, *, avg=600) -> SessionState:
    return repo.add_session(
        SessionState(
            id=uuid4(),
            clinic_id=uuid4(),
            date=now.date(),
            name="morning",
            start_at=now,
            end_at=now + timedelta(hours=6),
            token_cap=40,
            status=SessionStatus.open,
            doctor_free_at=now,
            avg_consult_s=avg,
        )
    )


def patient(repo: MemRepo, clinic_id, i: int) -> Patient:
    return repo.add_patient(Patient(id=uuid4(), clinic_id=clinic_id, wa_number=f"+9190000{i:05d}"))


def book(repo, s, p, now, req=None, source=Source.whatsapp):
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
    ).entry


def serve(repo, s, p, now):
    """Book + arrive + NEXT -> that entry is now IN_CONSULT (consult_start=now)."""
    e = book(repo, s, p, now)
    run(engine.mark_arrived(repo, now, e.id))
    run(engine.next_patient(repo, now, s.id))
    return e


# --------------------------------------------------------------------------- #
def test_close_finalizes_in_consult_and_expires_rest():
    repo = MemRepo()
    s = open_session(repo, dt(10), avg=600)
    served = serve(repo, s, patient(repo, s.clinic_id, 0), dt(10))
    b1 = book(repo, s, patient(repo, s.clinic_id, 1), dt(10), req=dt(11))
    b2 = book(repo, s, patient(repo, s.clinic_id, 2), dt(10), req=dt(12))

    res = run(engine.close_session(repo, dt(10, 20), s.id))

    # in-consult patient finalized (seen), not left stuck
    assert served.status == Status.done
    assert served.done_at == dt(10, 20)
    assert s.avg_consult_s == round(0.7 * 600 + 0.3 * 1200)  # 20-min actual consult
    assert s.consults_done == 1
    assert s.doctor_free_at == dt(10, 20)
    assert s.status == SessionStatus.closed

    # the two waiting patients expire with a strike + rebook nudge
    assert b1.status == Status.expired and b2.status == Status.expired
    assert repo.patients[b1.patient_id].strikes == 1
    assert repo.patients[b2.patient_id].strikes == 1
    rebooks = {n.entry_id for n in res.notifications if n.type == NotificationType.expired_rebook}
    assert rebooks == {b1.id, b2.id}

    # the finalized patient gets NO notification
    assert all(n.entry_id != served.id for n in res.notifications)


def test_cancel_today_finalizes_in_consult_others_broadcast():
    repo = MemRepo()
    s = open_session(repo, dt(10), avg=600)
    served = serve(repo, s, patient(repo, s.clinic_id, 0), dt(10))
    waiting = book(repo, s, patient(repo, s.clinic_id, 1), dt(10), req=dt(11))

    res = run(engine.cancel_session_today(repo, dt(10, 20), s.id))

    assert served.status == Status.done  # was inside -> recorded seen
    assert s.consults_done == 1
    assert waiting.status == Status.cancelled
    assert s.status == SessionStatus.cancelled
    closed = {n.entry_id for n in res.notifications if n.type == NotificationType.closed_broadcast}
    assert closed == {waiting.id}
    assert all(n.entry_id != served.id for n in res.notifications)


def test_close_with_no_in_consult_unchanged():
    """Regression guard: with nobody in the room, close behaves as before —
    booked expire with strikes, no phantom DONE, consults_done untouched."""
    repo = MemRepo()
    s = open_session(repo, dt(10), avg=600)
    b1 = book(repo, s, patient(repo, s.clinic_id, 1), dt(10), req=dt(11))

    res = run(engine.close_session(repo, dt(10, 20), s.id))

    assert b1.status == Status.expired
    assert s.consults_done == 0
    assert s.avg_consult_s == 600
    assert s.status == SessionStatus.closed
    assert all(n.type == NotificationType.expired_rebook for n in res.notifications)
    assert not any(e.status == Status.done for e in run(repo.list_entries(s.id)))


def test_avg_parity_close_vs_next():
    """The learning must not differ by path: finishing a 20-min consult via close
    yields the same avg_consult_s as finishing it via NEXT."""
    # via close
    repo_a = MemRepo()
    sa = open_session(repo_a, dt(10), avg=600)
    serve(repo_a, sa, patient(repo_a, sa.clinic_id, 0), dt(10))
    run(engine.close_session(repo_a, dt(10, 20), sa.id))

    # via NEXT (a second NEXT 20 min later finishes the same in-consult patient)
    repo_b = MemRepo()
    sb = open_session(repo_b, dt(10), avg=600)
    serve(repo_b, sb, patient(repo_b, sb.clinic_id, 0), dt(10))
    run(engine.next_patient(repo_b, dt(10, 20), sb.id))

    assert sa.avg_consult_s == sb.avg_consult_s
    assert sa.consults_done == sb.consults_done == 1


def test_reopen_does_not_resurrect_notified_patients():
    repo = MemRepo()
    s = open_session(repo, dt(10), avg=600)
    b1 = book(repo, s, patient(repo, s.clinic_id, 1), dt(10), req=dt(11))
    b2 = book(repo, s, patient(repo, s.clinic_id, 2), dt(10), req=dt(12))
    run(engine.close_session(repo, dt(10, 20), s.id))
    assert b1.status == Status.expired and b2.status == Status.expired

    res = run(engine.reopen_session(repo, dt(10, 30), s.id))

    assert s.status == SessionStatus.open
    assert s.doctor_free_at == dt(10, 30)
    # patients already told "book tomorrow" stay gone — no queue of the un-invited
    assert b1.status == Status.expired and b2.status == Status.expired
    assert not any(
        e.status in (Status.booked, Status.arrived) for e in run(repo.list_entries(s.id))
    )
    assert res.notifications == []


# --------------------------------------------------------------------------- #
# Part 1: reopen from cancelled
# --------------------------------------------------------------------------- #
def test_reopen_from_cancelled_status_open_entries_untouched():
    """Mis-tap on cancel-today: reopen restores status=open, entries unchanged."""
    repo = MemRepo()
    s = open_session(repo, dt(10), avg=600)
    b1 = book(repo, s, patient(repo, s.clinic_id, 1), dt(10), req=dt(11))
    b2 = book(repo, s, patient(repo, s.clinic_id, 2), dt(10), req=dt(12))
    run(engine.cancel_session_today(repo, dt(10, 20), s.id))
    assert s.status == SessionStatus.cancelled
    assert b1.status == Status.cancelled and b2.status == Status.cancelled

    res = run(engine.reopen_session(repo, dt(10, 25), s.id))

    assert s.status == SessionStatus.open
    assert s.doctor_free_at == dt(10, 25)
    # already-cancelled entries stay cancelled — no resurrection
    assert b1.status == Status.cancelled and b2.status == Status.cancelled
    assert res.notifications == []


def test_reopened_cancelled_session_accepts_new_booking():
    """After reopen from cancelled, new bookings are accepted normally."""
    repo = MemRepo()
    s = open_session(repo, dt(10), avg=600)
    run(engine.cancel_session_today(repo, dt(10, 20), s.id))
    run(engine.reopen_session(repo, dt(10, 25), s.id))

    # fresh patient walks in after reopen
    new_p = patient(repo, s.clinic_id, 99)
    res = book(repo, s, new_p, dt(10, 26))
    assert res is not None  # entry created
    assert res.status == Status.booked


# --------------------------------------------------------------------------- #
# Part 2: avg_consult_s clamping
# --------------------------------------------------------------------------- #
def test_long_consult_does_not_poison_avg():
    """26-hour consult (forgotten NEXT) must NOT update avg_consult_s."""
    repo = MemRepo()
    s = open_session(repo, dt(10), avg=600)
    served = serve(repo, s, patient(repo, s.clinic_id, 0), dt(10))
    # "close" 26 hours later — actual = 26 * 3600 = 93600s >> CONSULT_MAX_S
    run(engine.next_patient(repo, dt(10) + timedelta(hours=26), s.id))
    assert s.avg_consult_s == 600  # unchanged
    assert served.status == Status.done
    assert s.consults_done == 1


def test_short_normal_consult_updates_avg():
    """4-minute consult is within range and updates avg normally."""
    repo = MemRepo()
    s = open_session(repo, dt(10), avg=600)
    serve(repo, s, patient(repo, s.clinic_id, 0), dt(10))
    run(engine.next_patient(repo, dt(10, 4), s.id))  # 4-min actual = 240s
    assert s.avg_consult_s == round(0.7 * 600 + 0.3 * 240)  # = 492


def test_out_of_range_via_close_skips_avg():
    """26-hour consult finalized via close_session: avg unchanged."""
    repo = MemRepo()
    s = open_session(repo, dt(10), avg=600)
    serve(repo, s, patient(repo, s.clinic_id, 0), dt(10))
    run(engine.close_session(repo, dt(10) + timedelta(hours=26), s.id))
    assert s.avg_consult_s == 600


def test_avg_clamping_parity_close_vs_next():
    """Out-of-range duration is discarded identically whether finalized by NEXT or close."""
    repo_a, repo_b = MemRepo(), MemRepo()
    sa = open_session(repo_a, dt(10), avg=600)
    sb = open_session(repo_b, dt(10), avg=600)
    serve(repo_a, sa, patient(repo_a, sa.clinic_id, 0), dt(10))
    serve(repo_b, sb, patient(repo_b, sb.clinic_id, 0), dt(10))

    long_later = dt(10) + timedelta(hours=30)
    run(engine.close_session(repo_a, long_later, sa.id))
    run(engine.next_patient(repo_b, long_later, sb.id))

    assert sa.avg_consult_s == sb.avg_consult_s == 600
