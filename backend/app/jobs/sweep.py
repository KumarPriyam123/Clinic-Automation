"""sweep_tick — the 60s heartbeat: auto-open, grace/gap expiries, auto-close.
Plus stamp_daily (00:05 IST) which materializes sessions from the timetable.

All notifications produced here (expired_rebook, gap-offer lapse, etc.) come
from the engine's own EngineResult and are dispatched once; re-running the
sweep is a no-op because the underlying statuses have already changed.
"""

from __future__ import annotations

from datetime import datetime

from app import engine
from app.jobs.store import JobBackend
from app.wa.notify import NotificationDispatcher


async def sweep_tick(
    backend: JobBackend, dispatcher: NotificationDispatcher, now: datetime
) -> None:
    # 1. scheduled sessions whose start_at has passed -> open (live clock starts)
    for sid in await backend.sessions_to_open(now):
        res = await backend.engine_call(lambda r, sid=sid: engine.open_session(r, now, sid))
        await dispatcher.dispatch(now, res)

    # 2. grace expiries + gap-offer expiries across all open sessions
    res = await backend.engine_call(lambda r: engine.sweep(r, now))
    await dispatcher.dispatch(now, res)

    # 3. sessions past end_at -> close (pending tokens expire + rebook nudge)
    for sid in await backend.sessions_to_close(now):
        res = await backend.engine_call(lambda r, sid=sid: engine.close_session(r, now, sid))
        await dispatcher.dispatch(now, res)


async def stamp_daily(backend: JobBackend, now: datetime) -> list:
    """Materialize sessions from the weekly timetable for today + 2 days."""
    return await backend.stamp_sessions(now)
