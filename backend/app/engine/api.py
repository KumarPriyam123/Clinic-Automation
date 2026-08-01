"""Public queue-engine API — one deterministic transition per function.

Every function:
  * takes an injected ``now`` (no wall-clock reads anywhere in the engine),
  * obtains the session under a write lock via ``repo.lock_session`` (the
    production repo issues ``SELECT ... FOR UPDATE``),
  * applies exactly one transition, recomputes ETAs (rule 2),
  * writes an ``events`` row for every state change,
  * returns an :class:`EngineResult` carrying changed entries + notification
    *data* (never sends anything).

The three queue rules in CLAUDE.md §3 are law; this module is their only
implementation.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from app.engine.errors import (
    DuplicateActiveToken,
    GraceExpired,
    InvalidTransition,
    SessionEnded,
)
from app.engine.etas import recompute_etas
from app.engine.repo import Repo
from app.engine.results import (
    BOOKING_NOTICE_THRESHOLD_S,
    BookingInfo,
    EngineResult,
    NotificationType,
    OverflowSuggestion,
)
from app.engine.state import (
    ACTIVE_STATUSES,
    GAP_OFFER_TTL,
    GAP_THRESHOLD,
    RELEASED_STATUSES,
    WAITING_STATUSES,
    Entry,
    SessionState,
    grace_seconds,
)
from app.models import SessionStatus, Source, Status

log = logging.getLogger("clinicq.engine")

# Consult duration sanity bounds.  Durations outside this window are discarded
# before updating avg_consult_s so a forgotten NEXT tap cannot poison the ETA
# for the rest of the session.  The patient is still marked DONE; only the
# rolling-average update is skipped.
CONSULT_MIN_S = 30  # anything shorter is a mis-tap, not a real consult
CONSULT_MAX_S = 2700  # 45 min; beyond this assume the doctor forgot to tap NEXT


def _project_eta(
    session: SessionState, entries: list[Entry], priority_time: datetime, now: datetime
) -> datetime:
    """Dry-run ETA for a would-be new entry, without inserting it.

    Walks the queue forward past all existing waiting entries then returns
    where the new entry's ETA would land.  Used to catch ETA-past-end before
    committing the booking.
    """
    waiting = sorted(
        (e for e in entries if e.status in WAITING_STATUSES),
        key=Entry.order_key,
    )
    clock = max(now, session.doctor_free_at) if session.doctor_free_at else now
    avg = timedelta(seconds=session.avg_consult_s)
    for e in waiting:
        clock = max(clock, e.priority_time) + avg
    return max(clock, priority_time)


# --------------------------------------------------------------------------- #
# internal helpers
# --------------------------------------------------------------------------- #
async def _recompute_and_shift(
    repo: Repo, session: SessionState, entries: list[Entry], now: datetime, result: EngineResult
) -> None:
    """Recompute ETAs, persist moved entries, emit eta_shift notifications."""
    moved = recompute_etas(session, entries, now)
    for e in moved:
        await repo.save_entry(e)
        result.touched(e)
        result.notify(NotificationType.eta_shift, e.id, eta=e.eta)


def _issued_count(entries: list[Entry]) -> int:
    return sum(1 for e in entries if e.status not in RELEASED_STATUSES)


def _ordered_waiting(entries: list[Entry]) -> list[Entry]:
    return sorted((e for e in entries if e.status in WAITING_STATUSES), key=Entry.order_key)


async def _finalize_in_consult(
    repo: Repo,
    session: SessionState,
    entries: list[Entry],
    now: datetime,
    result: EngineResult,
    *,
    via_close: bool = False,
) -> None:
    """Finish any IN_CONSULT entry -> DONE: record duration, learn avg_consult_s
    (same rolling formula everywhere), bump consults_done, free the doctor.

    Shared by NEXT and the close/cancel paths — a patient in the room WAS seen,
    so the learning and the day's counts must not depend on which action ended
    the consult. The finalized patient gets no notification (nothing to tell
    someone who was being served). ``via_close`` only tags the audit event.
    """
    for e in entries:
        if e.status != Status.in_consult:
            continue
        actual = (
            (now - e.consult_start).total_seconds() if e.consult_start else session.avg_consult_s
        )
        e.status = Status.done
        e.done_at = now
        if CONSULT_MIN_S <= actual <= CONSULT_MAX_S:
            session.avg_consult_s = round(0.7 * session.avg_consult_s + 0.3 * actual)
        else:
            log.warning(
                "consult_out_of_range entry_id=%s actual_s=%.0f — avg_consult_s unchanged",
                e.id,
                actual,
            )
        session.consults_done += 1
        session.doctor_free_at = now
        await repo.save_entry(e)
        await repo.save_session(session)
        payload = {"via": "session_close"} if via_close else None
        await repo.add_event(session.clinic_id, session.id, e.id, "done", payload)
        result.touched(e)


# --------------------------------------------------------------------------- #
# session lifecycle
# --------------------------------------------------------------------------- #
def _assert_not_ended(session: SessionState, now: datetime) -> None:
    """Refuse to make a session live once its end_at has passed.

    The 60s sweep closes every open/paused session past end_at — correctly, and
    we do not weaken that. But accepting the transition anyway means the panel
    shows success and the sweep silently undoes it a minute later, which reads
    as a broken button. Reject up front so the reason is visible instead.
    """
    if session.end_at <= now:
        raise SessionEnded(f"session ended at {session.end_at.isoformat()}")


async def open_session(repo: Repo, now: datetime, session_id: UUID) -> EngineResult:
    session = await repo.lock_session(session_id)
    _assert_not_ended(session, now)
    session.status = SessionStatus.open
    session.doctor_free_at = now  # live clock starts
    await repo.save_session(session)
    await repo.add_event(session.clinic_id, session.id, None, "session_opened")
    result = EngineResult()
    await _recompute_and_shift(repo, session, await repo.list_entries(session_id), now, result)
    return result


async def pause_session(repo: Repo, now: datetime, session_id: UUID) -> EngineResult:
    session = await repo.lock_session(session_id)
    session.status = SessionStatus.paused
    await repo.save_session(session)
    await repo.add_event(session.clinic_id, session.id, None, "session_paused")
    return EngineResult()


async def resume_session(repo: Repo, now: datetime, session_id: UUID) -> EngineResult:
    session = await repo.lock_session(session_id)
    _assert_not_ended(session, now)
    session.status = SessionStatus.open
    await repo.save_session(session)
    await repo.add_event(session.clinic_id, session.id, None, "session_resumed")
    result = EngineResult()
    await _recompute_and_shift(repo, session, await repo.list_entries(session_id), now, result)
    return result


async def close_session(repo: Repo, now: datetime, session_id: UUID) -> EngineResult:
    """Close a session: finalize whoever is in the room (IN_CONSULT -> DONE, they
    were seen), then any still-pending token EXPIRES (absent ones take a strike +
    rebook nudge)."""
    session = await repo.lock_session(session_id)
    entries = await repo.list_entries(session_id)
    result = EngineResult()

    # the last patient is usually still in the room at end-of-day: count them
    await _finalize_in_consult(repo, session, entries, now, result, via_close=True)

    for e in entries:
        if e.status in (Status.booked, Status.arrived, Status.called, Status.skipped):
            absent = e.status in (Status.booked, Status.skipped)
            e.status = Status.expired
            e.done_at = now
            if absent:
                await repo.add_strike(e.patient_id)
            await repo.save_entry(e)
            await repo.add_event(session.clinic_id, session.id, e.id, "grace_expired")
            result.touched(e)
            result.notify(NotificationType.expired_rebook, e.id)

    session.status = SessionStatus.closed
    await repo.save_session(session)
    await repo.add_event(session.clinic_id, session.id, None, "session_closed")
    return result


async def reopen_session(repo: Repo, now: datetime, session_id: UUID) -> EngineResult:
    """Recover from a mis-tapped close or cancel: status (closed|cancelled) -> open.

    Deliberately does NOT touch entries. Expired/cancelled patients have already
    been sent "book tomorrow" / "clinic closed" messages — resurrecting them
    would summon people who were told not to come. Reopening only restores the
    ability to work the queue again (walk-ins, new bookings, NEXT).

    Allowed from: closed, cancelled (mis-tap recovery for today's session), and
    only while the session's own end_at is still in the future — see
    ``_assert_not_ended``.
    """
    session = await repo.lock_session(session_id)
    if session.status not in (SessionStatus.closed, SessionStatus.cancelled):
        raise InvalidTransition(f"cannot reopen from {session.status}")
    _assert_not_ended(session, now)
    session.status = SessionStatus.open
    session.doctor_free_at = now
    await repo.save_session(session)
    await repo.add_event(session.clinic_id, session.id, None, "session_reopened")
    result = EngineResult()
    await _recompute_and_shift(repo, session, await repo.list_entries(session_id), now, result)
    return result


# --------------------------------------------------------------------------- #
# booking
# --------------------------------------------------------------------------- #
async def book(
    repo: Repo,
    now: datetime,
    *,
    clinic_id: UUID,
    session_id: UUID,
    patient_id: UUID,
    requested_time: datetime | None,
    source: Source = Source.whatsapp,
) -> EngineResult:
    session = await repo.lock_session(session_id)
    entries = await repo.list_entries(session_id)
    patient = await repo.get_patient(patient_id)

    # rule: one ACTIVE token per (clinic, wa_number) across today's sessions
    if await repo.has_active_token(clinic_id, patient.wa_number):
        raise DuplicateActiveToken(patient.wa_number)

    # floor = earliest time anyone can be served: max(now, session.start_at).
    # ASAP => floor.  Specific time => max(requested, floor) — no leapfrogging,
    # and no booking before the session opens.
    floor = max(now, session.start_at)
    priority_time = floor if requested_time is None else max(requested_time, floor)

    # Record WHY the granted time is what it is. The clamp above is correct
    # (rule 1), but applying it silently is what makes a patient who asked for
    # 11:30 and got 5:00 PM believe the clinic's system is broken. The flow
    # turns this into one plain sentence ahead of the token details.
    adjust_reason: str | None = None
    if (
        requested_time is not None
        and (priority_time - requested_time).total_seconds() > BOOKING_NOTICE_THRESHOLD_S
    ):
        adjust_reason = "session_start" if floor == session.start_at else "now"

    # overflow checks -> suggest alternatives instead of forcing the token in
    reason: str | None = None
    if session.status in (SessionStatus.closed, SessionStatus.cancelled):
        reason = "closed"
    elif _issued_count(entries) >= session.token_cap:
        reason = "cap"
    elif _project_eta(session, entries, priority_time, now) >= session.end_at:
        # covers both priority_time-past-end AND ETA-past-end due to queue depth
        reason = "past_end"
    if reason:
        alts = await repo.future_sessions_with_space(clinic_id, now)
        alts = [a for a in alts if a.session_id != session_id]
        return EngineResult(overflow=OverflowSuggestion(reason=reason, alternatives=alts))

    entry = Entry(
        id=uuid4(),
        session_id=session_id,
        clinic_id=clinic_id,
        patient_id=patient_id,
        token_number=await repo.next_token_number(session_id),
        priority_time=priority_time,
        booked_at=now,
        status=Status.booked,
        source=source,
    )
    await repo.insert_entry(entry)
    await repo.add_event(clinic_id, session_id, entry.id, "booked", {"source": source.value})

    entries.append(entry)
    recompute_etas(session, entries, now)  # sets entry.eta; suppress shift pings on book
    for e in entries:
        await repo.save_entry(e)

    result = EngineResult(
        entry=entry,
        booking=BookingInfo(
            session_date=session.date,
            session_name=session.name,
            session_start=session.start_at,
            session_end=session.end_at,
            granted=priority_time,
            requested=requested_time,
            adjust_reason=adjust_reason,
        ),
    )
    result.touched(entry)
    return result


async def cancel(repo: Repo, now: datetime, entry_id: UUID) -> EngineResult:
    entry = await repo.get_entry(entry_id)
    session = await repo.lock_session(entry.session_id)
    entry.status = Status.cancelled
    entry.done_at = now
    await repo.save_entry(entry)
    await repo.add_event(session.clinic_id, session.id, entry.id, "cancelled")

    result = EngineResult()
    result.touched(entry)
    entries = await repo.list_entries(session.id)
    await _recompute_and_shift(repo, session, entries, now, result)
    await _gap_check(repo, now, session, result)
    return result


# --------------------------------------------------------------------------- #
# presence
# --------------------------------------------------------------------------- #
async def mark_arrived(repo: Repo, now: datetime, entry_id: UUID) -> EngineResult:
    entry = await repo.get_entry(entry_id)
    session = await repo.lock_session(entry.session_id)
    if entry.status == Status.skipped:
        return await arrived_during_grace(repo, now, entry_id)
    if entry.status != Status.booked:
        raise InvalidTransition(f"cannot mark arrived from {entry.status}")
    entry.status = Status.arrived
    entry.arrived_at = now
    await repo.save_entry(entry)
    await repo.add_event(session.clinic_id, session.id, entry.id, "arrived")

    result = EngineResult()
    result.touched(entry)
    await _recompute_and_shift(repo, session, await repo.list_entries(session.id), now, result)
    return result


async def arrived_during_grace(repo: Repo, now: datetime, entry_id: UUID) -> EngineResult:
    """A skipped patient shows up within grace: re-insert at the head so they
    are served at the very next NEXT (priority_time = now-1s + next_up flag)."""
    entry = await repo.get_entry(entry_id)
    session = await repo.lock_session(entry.session_id)
    if entry.status != Status.skipped:
        raise InvalidTransition(f"not in grace: {entry.status}")
    if entry.grace_until and now > entry.grace_until:
        raise GraceExpired(str(entry_id))

    entry.status = Status.arrived
    entry.arrived_at = now
    entry.priority_time = now - timedelta(seconds=1)
    entry.next_up = True
    await repo.save_entry(entry)
    await repo.add_event(session.clinic_id, session.id, entry.id, "arrived")

    result = EngineResult()
    result.touched(entry)
    await _recompute_and_shift(repo, session, await repo.list_entries(session.id), now, result)
    return result


async def call_now(repo: Repo, now: datetime, entry_id: UUID) -> EngineResult:
    """Receptionist override: make this present patient head-of-line so the very
    next NEXT serves them. Marks a BOOKED entry ARRIVED, sets ``next_up`` and
    ``priority_time = now-1s`` (rule 1's max still blocks leapfrogging a *target*
    time, but next_up wins the order_key). Does not itself start the consult —
    NEXT does — so the doctor-never-idle skip guard stays intact."""
    entry = await repo.get_entry(entry_id)
    session = await repo.lock_session(entry.session_id)
    if entry.status in (Status.done, Status.cancelled, Status.expired, Status.in_consult):
        raise InvalidTransition(f"cannot call from {entry.status}")
    if entry.status in (Status.booked, Status.skipped):
        entry.arrived_at = entry.arrived_at or now
    entry.status = Status.arrived
    entry.priority_time = now - timedelta(seconds=1)
    entry.next_up = True
    await repo.save_entry(entry)
    await repo.add_event(session.clinic_id, session.id, entry.id, "arrived", {"call_now": True})

    result = EngineResult(entry=entry)
    result.touched(entry)
    await _recompute_and_shift(repo, session, await repo.list_entries(session.id), now, result)
    return result


# --------------------------------------------------------------------------- #
# serving — rule 3
# --------------------------------------------------------------------------- #
async def next_patient(repo: Repo, now: datetime, session_id: UUID) -> EngineResult:
    session = await repo.lock_session(session_id)
    entries = await repo.list_entries(session_id)
    result = EngineResult()

    # 1. finish whoever is in consult -> DONE, learn avg, free the doctor
    await _finalize_in_consult(repo, session, entries, now, result)

    # 2. skip guard: only skip when an ARRIVED replacement exists; else hold
    ordered = _ordered_waiting(entries)
    first_arrived_idx = next((i for i, e in enumerate(ordered) if e.status == Status.arrived), None)
    if first_arrived_idx is None:
        await _recompute_and_shift(repo, session, entries, now, result)
        return result

    # 3. every BOOKED entry ahead of the served one is passed over -> SKIPPED
    for e in ordered[:first_arrived_idx]:
        if e.status == Status.booked:
            e.status = Status.skipped
            e.grace_until = now + timedelta(seconds=grace_seconds(session.avg_consult_s))
            e.skip_count += 1
            await repo.save_entry(e)
            await repo.add_event(session.clinic_id, session.id, e.id, "skipped")
            result.touched(e)
            result.notify(NotificationType.skipped_grace, e.id, grace_until=e.grace_until)

    # 4. serve the first ARRIVED: CALLED then IN_CONSULT immediately (v1)
    served = ordered[first_arrived_idx]
    served.status = Status.in_consult
    served.called_at = now
    served.consult_start = now
    served.next_up = False
    await repo.save_entry(served)
    await repo.add_event(session.clinic_id, session.id, served.id, "called")
    result.touched(served)
    result.entry = served
    result.notify(NotificationType.you_are_next, served.id, token_number=served.token_number)

    await _recompute_and_shift(repo, session, entries, now, result)
    return result


# --------------------------------------------------------------------------- #
# sweeper (scheduler, every 60s)
# --------------------------------------------------------------------------- #
async def sweep(repo: Repo, now: datetime) -> EngineResult:
    result = EngineResult()
    for session in await repo.open_sessions():
        entries = await repo.list_entries(session.id)
        changed = False
        for e in entries:
            # grace expiry: skipped and never came back -> EXPIRED + strike
            if e.status == Status.skipped and e.grace_until and now > e.grace_until:
                e.status = Status.expired
                e.done_at = now
                await repo.add_strike(e.patient_id)
                await repo.save_entry(e)
                await repo.add_event(session.clinic_id, session.id, e.id, "grace_expired")
                result.touched(e)
                result.notify(NotificationType.expired_rebook, e.id)
                changed = True
            # gap-offer expiry: unanswered offer lapses (max 1 per session)
            elif e.gap_offered_at and now > e.gap_offered_at + GAP_OFFER_TTL:
                e.gap_offered_at = None
                await repo.save_entry(e)
                result.touched(e)
                changed = True
        if changed:
            await _recompute_and_shift(repo, session, entries, now, result)
    return result


# --------------------------------------------------------------------------- #
# delays / session-wide
# --------------------------------------------------------------------------- #
async def delay_session(repo: Repo, now: datetime, session_id: UUID, minutes: int) -> EngineResult:
    session = await repo.lock_session(session_id)
    base = session.doctor_free_at or now
    session.doctor_free_at = base + timedelta(minutes=minutes)
    await repo.save_session(session)
    await repo.add_event(
        session.clinic_id, session.id, None, "delay_broadcast", {"minutes": minutes}
    )

    result = EngineResult()
    await _recompute_and_shift(repo, session, await repo.list_entries(session_id), now, result)
    return result


async def cancel_session_today(repo: Repo, now: datetime, session_id: UUID) -> EngineResult:
    session = await repo.lock_session(session_id)
    entries = await repo.list_entries(session_id)
    result = EngineResult()
    # a patient already inside WAS seen — record them done, don't cancel them
    await _finalize_in_consult(repo, session, entries, now, result, via_close=True)
    for e in entries:
        if e.status in ACTIVE_STATUSES:
            e.status = Status.cancelled
            e.done_at = now
            await repo.save_entry(e)
            await repo.add_event(session.clinic_id, session.id, e.id, "cancelled")
            result.touched(e)
            result.notify(NotificationType.closed_broadcast, e.id)
    session.status = SessionStatus.cancelled
    await repo.save_session(session)
    await repo.add_event(session.clinic_id, session.id, None, "session_closed")
    return result


async def emergency_insert(
    repo: Repo, now: datetime, session_id: UUID, patient_id: UUID
) -> EngineResult:
    """Insert a present emergency patient at the front (priority_time = now-1s,
    ARRIVED so they are served at the next NEXT). Others' ETAs shift."""
    session = await repo.lock_session(session_id)
    entry = Entry(
        id=uuid4(),
        session_id=session_id,
        clinic_id=session.clinic_id,
        patient_id=patient_id,
        token_number=await repo.next_token_number(session_id),
        priority_time=now - timedelta(seconds=1),
        booked_at=now,
        status=Status.arrived,
        source=Source.walkin,
        arrived_at=now,
    )
    await repo.insert_entry(entry)
    await repo.add_event(session.clinic_id, session.id, entry.id, "walkin", {"emergency": True})

    result = EngineResult(entry=entry)
    result.touched(entry)
    await _recompute_and_shift(repo, session, await repo.list_entries(session_id), now, result)
    return result


# --------------------------------------------------------------------------- #
# gap pull-forward (CLAUDE.md § gap)
# --------------------------------------------------------------------------- #
async def _gap_check(
    repo: Repo, now: datetime, session: SessionState, result: EngineResult
) -> None:
    """After a cancel/expiry: if the doctor would idle >10 min before the next
    patient's target, pull an ARRIVED patient forward, else offer to remotes."""
    entries = await repo.list_entries(session.id)
    waiting = _ordered_waiting(entries)
    if not waiting:
        return
    free_at = session.doctor_free_at or now
    if free_at + GAP_THRESHOLD >= waiting[0].priority_time:
        return  # no meaningful gap

    # 1. auto-pull the earliest ARRIVED patient (they only benefit)
    arrived = [e for e in waiting if e.status == Status.arrived]
    if arrived:
        pull = min(arrived, key=lambda e: e.priority_time)
        pull.priority_time = now
        await repo.save_entry(pull)
        await repo.add_event(session.clinic_id, session.id, pull.id, "gap_taken")
        result.touched(pull)
        await _recompute_and_shift(repo, session, entries, now, result)
        return

    # 2. else offer the slot to the next 2-3 remote patients (one offer each)
    offered = 0
    for e in waiting:
        if offered >= 3:
            break
        if e.status == Status.booked and e.gap_offered_at is None:
            e.gap_offered_at = now
            await repo.save_entry(e)
            await repo.add_event(session.clinic_id, session.id, e.id, "gap_offered")
            result.touched(e)
            result.notify(NotificationType.gap_offer, e.id)
            offered += 1
    # 3./4. else a walk-in fills it, else a genuine break — nothing to do


async def gap_check(repo: Repo, now: datetime, session_id: UUID) -> EngineResult:
    session = await repo.lock_session(session_id)
    result = EngineResult()
    await _gap_check(repo, now, session, result)
    return result


async def accept_gap_offer(repo: Repo, now: datetime, entry_id: UUID) -> EngineResult:
    entry = await repo.get_entry(entry_id)
    session = await repo.lock_session(entry.session_id)
    result = EngineResult()
    # offer valid only within TTL of when it was made
    if entry.gap_offered_at is None or now > entry.gap_offered_at + GAP_OFFER_TTL:
        return result  # expired / no offer -> no-op
    entry.priority_time = now
    entry.gap_offered_at = None
    await repo.save_entry(entry)
    await repo.add_event(session.clinic_id, session.id, entry.id, "gap_taken")
    result.touched(entry)
    await _recompute_and_shift(repo, session, await repo.list_entries(session.id), now, result)
    return result


async def recompute_etas_public(repo: Repo, now: datetime, session_id: UUID) -> EngineResult:
    """Explicit recompute (rule 2) — sets eta + report_time, returns entries
    whose eta moved > 10 min as eta_shift notifications."""
    session = await repo.lock_session(session_id)
    result = EngineResult()
    await _recompute_and_shift(repo, session, await repo.list_entries(session_id), now, result)
    return result
