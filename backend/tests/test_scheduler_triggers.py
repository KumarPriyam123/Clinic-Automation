"""Scheduler cron triggers must resolve to the intended IST clock times.

The scheduler runs in UTC; the daily jobs use explicit IST timezone objects. This
pins that a fresh build fires stamp_sessions at 00:05 IST and the digest at
21:45 IST (and, as a UTC sanity check, at the corresponding UTC instants) so a
naive-local-time regression can't silently shift them.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.jobs.scheduler import IST, build_scheduler
from app.jobs.store import MemJobs
from app.wa.notify import NotificationDispatcher
from app.wa.sender import Sender
from app.wa.store import InMemoryWaStore


def _sched():
    backend = MemJobs()
    sender = Sender(InMemoryWaStore())
    dispatcher = NotificationDispatcher(sender, backend.resolver())
    return build_scheduler(backend, dispatcher, sender)


def test_daily_jobs_fire_at_ist_clock_times():
    jobs = {j.id: j for j in _sched().get_jobs()}
    assert {"sweep", "ping_scan", "stamp_sessions", "doctor_digest"} <= set(jobs)

    now = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)  # arbitrary reference
    expected_ist = {"stamp_sessions": (0, 5), "doctor_digest": (21, 45)}
    for jid, (h, m) in expected_ist.items():
        nxt = jobs[jid].trigger.get_next_fire_time(None, now)
        ist = nxt.astimezone(IST)
        assert (ist.hour, ist.minute) == (h, m), f"{jid} fired at {ist} IST"


def test_ist_maps_to_expected_utc_instants():
    jobs = {j.id: j for j in _sched().get_jobs()}
    now = datetime(2026, 7, 23, 0, 0, tzinfo=UTC)
    # IST = UTC+5:30 -> 00:05 IST == 18:35 UTC (prev day); 21:45 IST == 16:15 UTC
    stamp_utc = jobs["stamp_sessions"].trigger.get_next_fire_time(None, now).astimezone(UTC)
    digest_utc = jobs["doctor_digest"].trigger.get_next_fire_time(None, now).astimezone(UTC)
    assert (stamp_utc.hour, stamp_utc.minute) == (18, 35)
    assert (digest_utc.hour, digest_utc.minute) == (16, 15)
