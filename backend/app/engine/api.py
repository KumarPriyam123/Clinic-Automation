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

from datetime import datetime, timedelta
from uuid import UUID, uuid4

from app.engine.errors import DuplicateActiveToken, GraceExpired, InvalidTransition
from app.engine.etas import recompute_etas
from app.engine.repo import Repo
from app.engine.results import EngineResult, NotificationType, OverflowSuggestion
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


# --------------------------------------------------------------------------- #
# session lifecycle
# --------------------------------------------------------------------------- #
async def open_session(repo: Repo, now: datetime, session_id: UUID) -> EngineResult:
    session = await repo.lock_session(session_id)
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
    session.status = SessionStatus.open
    await repo.save_session(session)
    await repo.add_event(session.clinic_id, session.id, None, "session_resumed")
    result = EngineResult()
    await _recompute_and_shift(repo, session, await repo.list_entries(session_id), now, result)
    return result


async def close_session(repo: Repo, now: datetime, session_id: UUID) -> EngineResult:
    """Close a session: any still-pending token EXPIRES (absent ones take a
    strike + rebook nudge). avg_consult_s is already persisted from DONEs."""
    session = await repo.lock_session(session_id)
    entries = await repo.list_entries(session_id)
    result = EngineResult()

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

    # priority_time = max(requested_time or now, now) — no leapfrogging waiters
    priority_time = max(requested_time or now, now)

    # overflow checks -> suggest alternatives instead of forcing the token in
    reason: str | None = None
    if session.status in (SessionStatus.closed, SessionStatus.cancelled):
        reason = "closed"
    elif _issued_count(entries) >= session.token_cap:
        reason = "cap"
    elif priority_time >= session.end_at:
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

    result = EngineResult(entry=entry)
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
    for e in entries:
        if e.status == Status.in_consult:
            actual = (
                (now - e.consult_start).total_seconds()
                if e.consult_start
                else session.avg_consult_s
            )
            e.status = Status.done
            e.done_at = now
            session.avg_consult_s = round(0.7 * session.avg_consult_s + 0.3 * actual)
            session.consults_done += 1
            session.doctor_free_at = now
            await repo.save_entry(e)
            await repo.save_session(session)
            await repo.add_event(session.clinic_id, session.id, e.id, "done")
            result.touched(e)

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
