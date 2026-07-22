"""FastAPI app factory.

v1 = one process: webhook receiver + panel REST API + queue engine +
scheduler jobs. The lifespan opens the db pool and installs the WhatsApp
message handler (webhook -> flow -> engine -> dispatcher).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI

from app import db
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


async def _handle_inbound(inbound: InboundMessage) -> None:
    flow = Flow(PgConvo(), Sender(PoolWaStore()), llm_parse)
    await flow.handle(datetime.now(UTC), inbound)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init_pool()
    set_message_handler(_handle_inbound)

    backend = PgJobs()
    sender = Sender(PoolWaStore())
    dispatcher = NotificationDispatcher(sender, backend.resolver())
    scheduler = build_scheduler(backend, dispatcher, sender)
    scheduler.start()
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)
        set_message_handler(None)
        await db.close_pool()


def create_app() -> FastAPI:
    app = FastAPI(title="ClinicQ", version="0.1.0", lifespan=lifespan)

    @app.get("/healthz")
    async def healthz() -> dict[str, bool]:
        return {"ok": True}

    app.include_router(build_wa_router(PoolWaStore()))

    return app


app = create_app()
