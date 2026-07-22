"""ping_scan — proactive per-entry pings for open sessions (runs every 60s).

Owns three notifications, each idempotent so a job crash never double-sends:
  * pre_arrival  at eta - (buffer + 15 min), once  (notified_pre_arrival_at)
  * three_away   when exactly 3 waiting entries are ahead, once (notified_three_away_at)
  * eta_shift    only when |eta - last_notified_eta| > 10 min (last_notified_eta)
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.engine.results import EngineResult, NotificationType
from app.engine.state import ETA_PING_THRESHOLD_S, WAITING_STATUSES, Entry, buffer_seconds
from app.jobs.store import JobBackend
from app.wa.notify import NotificationDispatcher

PRE_ARRIVAL_LEAD_S = 15 * 60


async def ping_scan(backend: JobBackend, dispatcher: NotificationDispatcher, now: datetime) -> None:
    for session in await backend.open_sessions():
        entries = await backend.list_entries(session.id)
        waiting = sorted((e for e in entries if e.status in WAITING_STATUSES), key=Entry.order_key)
        buf = buffer_seconds(session.avg_consult_s)
        result = EngineResult()

        for ahead, e in enumerate(waiting):
            if e.eta is None:
                continue

            # pre_arrival — one lead-time reminder
            if e.notified_pre_arrival_at is None:
                trigger = e.eta - timedelta(seconds=buf + PRE_ARRIVAL_LEAD_S)
                if now >= trigger:
                    e.notified_pre_arrival_at = now
                    await backend.save_entry(e)
                    result.notify(
                        NotificationType.pre_arrival, e.id, eta=e.eta, report=e.report_time
                    )

            # three_away — fire once when exactly 3 are ahead
            if ahead == 3 and e.notified_three_away_at is None:
                e.notified_three_away_at = now
                await backend.save_entry(e)
                result.notify(NotificationType.three_away, e.id, eta=e.eta)

            # eta_shift — only on drift > 10 min from what the patient last heard
            if e.last_notified_eta is None:
                e.last_notified_eta = e.eta  # baseline (booking confirm already gave it)
                await backend.save_entry(e)
            elif abs((e.eta - e.last_notified_eta).total_seconds()) > ETA_PING_THRESHOLD_S:
                e.last_notified_eta = e.eta
                await backend.save_entry(e)
                result.notify(NotificationType.eta_shift, e.id, eta=e.eta)

        await dispatcher.dispatch(now, result, allow_eta_shift=True)
