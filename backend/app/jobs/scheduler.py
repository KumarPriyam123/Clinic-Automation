"""APScheduler wiring — one AsyncIOScheduler started in the FastAPI lifespan.

The job bodies are pure functions taking an injected ``now`` (tested with a
FakeClock); here they are bound to real wall-clock triggers. Jobs are the only
place that reads the clock in production.
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.jobs.digest import run_digest
from app.jobs.pings import ping_scan
from app.jobs.store import JobBackend
from app.jobs.sweep import stamp_daily, sweep_tick
from app.wa.notify import NotificationDispatcher
from app.wa.sender import Sender

IST = ZoneInfo("Asia/Kolkata")


def build_scheduler(
    backend: JobBackend, dispatcher: NotificationDispatcher, sender: Sender
) -> AsyncIOScheduler:
    sched = AsyncIOScheduler(timezone=UTC)

    async def _sweep() -> None:
        await sweep_tick(backend, dispatcher, datetime.now(UTC))

    async def _ping() -> None:
        await ping_scan(backend, dispatcher, datetime.now(UTC))

    async def _stamp() -> None:
        await stamp_daily(backend, datetime.now(UTC))

    async def _digest() -> None:
        await run_digest(backend, sender, datetime.now(UTC))

    sched.add_job(_sweep, IntervalTrigger(seconds=60), id="sweep", max_instances=1)
    sched.add_job(_ping, IntervalTrigger(seconds=60), id="ping_scan", max_instances=1)
    sched.add_job(_stamp, CronTrigger(hour=0, minute=5, timezone=IST), id="stamp_sessions")
    sched.add_job(_digest, CronTrigger(hour=21, minute=45, timezone=IST), id="doctor_digest")
    return sched
