"""Operational endpoints: /metrics (JSON, no new deps).

Point an uptime monitor at /healthz (liveness), which is unauthenticated and
returns a bare {"ok": true}. /metrics is for a dashboard / alerting: today's
booking + WhatsApp volume, send failures, the scheduler's last tick (staleness
=> jobs stopped), and DB pool health. All counts are IST "today" since the
clinic operates in Asia/Kolkata.

/metrics REQUIRES a bearer token. Two reasons, and the second is the one that
matters for the pilot:

 1. `bookings_today` is a cross-tenant patient count. No names or identifiers,
    but it is still every clinic's daily volume served to anyone who guesses
    the path, on a host reachable through the public tunnel.
 2. Each request acquires a pool connection and runs two count(*) scans. The
    pool maxes out at 10 and the live queue needs it. An unauthenticated
    endpoint that does real database work is a cheap way to starve the thing
    a receptionist is actively using.

With METRICS_TOKEN unset the route 404s rather than serving unguarded data:
missing config must not silently downgrade to "public".
"""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Header, HTTPException, status

from app import db, obs
from app.config import settings

router = APIRouter(tags=["ops"])


def _authorize(authorization: str | None) -> None:
    """404 when unconfigured, 401 when the token is absent or wrong.

    404-not-401 for the unconfigured case on purpose: if the operator never set
    a token there is nothing here to authenticate against, and advertising the
    endpoint's existence to an unauthenticated caller buys nothing.
    """
    expected = settings.METRICS_TOKEN
    if not expected:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")

    prefix = "Bearer "
    supplied = (
        authorization[len(prefix) :] if authorization and authorization.startswith(prefix) else ""
    )
    # Constant-time: a length-independent early return would leak the token
    # prefix to a patient attacker.
    if not secrets.compare_digest(supplied, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid metrics token")


@router.get("/metrics")
async def metrics(authorization: str | None = Header(default=None)) -> dict:
    _authorize(authorization)
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
