"""FastAPI app factory.

v1 = one process: webhook receiver + panel REST API + queue engine +
scheduler jobs. The lifespan opens the db pool and installs the WhatsApp
message handler (webhook -> flow -> engine -> dispatcher).
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app import db, obs
from app.api.ops import router as ops_router
from app.api.panel import build_router as build_panel_router
from app.config import settings
from app.convo.flow import Flow
from app.convo.llm import parse as llm_parse
from app.convo.store import PgConvo
from app.jobs.scheduler import build_scheduler
from app.jobs.store import PgJobs
from app.wa.notify import NotificationDispatcher
from app.wa.sender import Sender
from app.wa.store import PoolWaStore
from app.wa.webhook import InboundMessage, set_message_handler
from app.wa.webhook import build_router as build_wa_router

log = logging.getLogger("clinicq")
IST = ZoneInfo("Asia/Kolkata")


async def _handle_inbound(inbound: InboundMessage) -> None:
    flow = Flow(PgConvo(), Sender(PoolWaStore()), llm_parse)
    await flow.handle(datetime.now(UTC), inbound)


@asynccontextmanager
async def lifespan(app: FastAPI):
    obs.configure_logging()
    settings.assert_wa_secret_valid()
    await db.init_pool()
    set_message_handler(_handle_inbound)

    # Catch-up: stamp today+2 sessions in case the server missed the 00:05 IST
    # nightly job (laptop sleep, container restart, etc.).  stamp_sessions is
    # idempotent (ON CONFLICT DO NOTHING) so running it on every startup is cheap
    # and safe.  Without this, /session/today returns null after a cold start and
    # the receptionist sees "no session today" until midnight.
    try:
        from app.jobs.store import PgJobs as _PgJobs

        _stamped = await _PgJobs().stamp_sessions(datetime.now(UTC))
        if _stamped:
            log.info("startup_stamp_sessions created=%d session(s) for today+2", len(_stamped))
    except Exception as _exc:
        log.warning("startup_stamp_sessions failed: %s", _exc)

    # SINGLE-INSTANCE GUARD: the scheduler must be active in exactly one process.
    # With uvicorn --workers >1 every job double-fires (duplicate patient sends).
    scheduler = None
    if settings.RUN_SCHEDULER:
        backend = PgJobs()
        sender = Sender(PoolWaStore())
        dispatcher = NotificationDispatcher(sender, backend.resolver())
        scheduler = build_scheduler(backend, dispatcher, sender)
        scheduler.start()
        fires = {
            j.id: j.next_run_time.astimezone(IST).strftime("%Y-%m-%d %H:%M %Z")
            for j in scheduler.get_jobs()
            if j.next_run_time
        }
        log.info("scheduler ACTIVE (RUN_SCHEDULER=true) next-fires(IST)=%s", fires)
    else:
        log.warning("scheduler DISABLED (RUN_SCHEDULER=false) — no jobs fire in this process")
    try:
        yield
    finally:
        if scheduler is not None:
            scheduler.shutdown(wait=False)
        set_message_handler(None)
        await db.close_pool()


def create_app() -> FastAPI:
    app = FastAPI(title="ClinicQ", version="0.1.0", lifespan=lifespan)

    # Panel is a separate origin (Next.js dev / PWA). Allow it to call the API.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.PANEL_ORIGINS,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def _access_log(request: Request, call_next):
        # Structured request log — path only (no bodies), never PII/token.
        # The redaction filter (obs) scrubs anything phone/token shaped anyway.
        start = time.perf_counter()
        response = await call_next(request)
        dur_ms = round((time.perf_counter() - start) * 1000)
        log.info(
            "http method=%s path=%s status=%s dur_ms=%s",
            request.method,
            request.url.path,
            response.status_code,
            dur_ms,
        )
        return response

    @app.get("/healthz")
    async def healthz() -> dict[str, bool]:
        return {"ok": True}

    app.include_router(build_wa_router(PoolWaStore()))
    app.include_router(build_panel_router())
    app.include_router(ops_router)

    return app


app = create_app()
