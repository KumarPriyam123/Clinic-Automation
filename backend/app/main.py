"""FastAPI app factory.

v1 = one process: webhook receiver + panel REST API + queue engine +
scheduler jobs. This file only wires the app and the health probe; the
engine / wa / convo / jobs / api layers land in later build phases.
"""

from __future__ import annotations

from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="ClinicQ", version="0.1.0")

    @app.get("/healthz")
    async def healthz() -> dict[str, bool]:
        return {"ok": True}

    return app


app = create_app()
