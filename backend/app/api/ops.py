"""Operational endpoints: /metrics (JSON, no new deps).

Point an uptime monitor at /healthz (liveness). /metrics is for a dashboard /
alerting: today's booking + WhatsApp volume, send failures, the scheduler's
last tick (staleness => jobs stopped), and DB pool health. All counts are IST
"today" since the clinic operates in Asia/Kolkata.
"""

from __future__ import annotations

from fastapi import APIRouter

from app import db, obs

router = APIRouter(tags=["ops"])


@router.get("/metrics")
async def metrics() -> dict:
    pool = db.get_pool()
    async with pool.acquire() as con:
        bookings_today = await con.fetchval(
            "select count(*) from queue_entries "
            "where (booked_at at time zone 'Asia/Kolkata')::date "
            "    = (now() at time zone 'Asia/Kolkata')::date"
        )
        wa_sends_today = await con.fetchval(
            "select count(*) from wa_messages "
            "where direction = 'out' "
            "  and (created_at at time zone 'Asia/Kolkata')::date "
            "    = (now() at time zone 'Asia/Kolkata')::date"
        )
    tick = obs.last_scheduler_tick()
    return {
        "bookings_today": bookings_today or 0,
        "wa_sends_today": wa_sends_today or 0,
        "wa_send_failures": obs.counters()["wa_send_failures"],
        "scheduler_last_tick": tick.isoformat() if tick else None,
        "scheduler_active": obs.last_scheduler_tick() is not None,
        "db_pool": {
            "size": pool.get_size(),
            "idle": pool.get_idle_size(),
            "max": pool.get_max_size(),
            "min": pool.get_min_size(),
        },
    }
