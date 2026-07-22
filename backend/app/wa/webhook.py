"""WhatsApp webhook — GET verify + POST receive.

Verifies X-Hub-Signature-256, dedupes inbound by wamid, normalizes each
message to an InboundMessage, ACKs 200 immediately, and processes in a
background task via the registered handler (wired in P4/convo).
"""

from __future__ import annotations

import dataclasses as dc
import hashlib
import hmac
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Request, Response

from app.config import settings
from app.wa.store import WaStore

Handler = Callable[["InboundMessage"], Awaitable[None]]


@dc.dataclass(slots=True)
class InboundMessage:
    wa_number: str
    kind: str  # text | button_reply | list_reply
    text: str | None
    button_id: str | None
    timestamp: datetime
    wamid: str | None = None
    phone_number_id: str | None = None


# --- pure helpers (unit-tested) ----------------------------------------- #
def verify_signature(app_secret: str, body: bytes, header: str | None) -> bool:
    """Validate the 'X-Hub-Signature-256: sha256=<hex>' header, constant-time."""
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header[len("sha256=") :])


def _ts(raw: str | None) -> datetime:
    try:
        return datetime.fromtimestamp(int(raw), tz=UTC)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return datetime.now(tz=UTC)


def normalize_inbound(payload: dict) -> list[InboundMessage]:
    """Flatten a webhook body into InboundMessages (one per message)."""
    out: list[InboundMessage] = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            phone_id = value.get("metadata", {}).get("phone_number_id")
            for m in value.get("messages", []):
                out.append(_normalize_one(m, phone_id))
    return out


def _normalize_one(m: dict, phone_id: str | None) -> InboundMessage:
    mtype = m.get("type")
    wa_number = m.get("from", "")
    ts = _ts(m.get("timestamp"))
    wamid = m.get("id")
    kind, text, button_id = "text", None, None

    if mtype == "text":
        text = m.get("text", {}).get("body")
    elif mtype == "interactive":
        inter = m.get("interactive", {})
        if inter.get("type") == "button_reply":
            kind = "button_reply"
            button_id = inter["button_reply"].get("id")
            text = inter["button_reply"].get("title")
        elif inter.get("type") == "list_reply":
            kind = "list_reply"
            button_id = inter["list_reply"].get("id")
            text = inter["list_reply"].get("title")
    elif mtype == "button":  # template quick-reply
        kind = "button_reply"
        button_id = m.get("button", {}).get("payload")
        text = m.get("button", {}).get("text")

    return InboundMessage(
        wa_number=wa_number,
        kind=kind,
        text=text,
        button_id=button_id,
        timestamp=ts,
        wamid=wamid,
        phone_number_id=phone_id,
    )


# --- handler registry (set by convo layer in P4) ------------------------ #
_handler: Handler | None = None


def set_message_handler(fn: Handler | None) -> None:
    global _handler
    _handler = fn


# --- router ------------------------------------------------------------- #
def build_router(store: WaStore) -> APIRouter:
    router = APIRouter()

    @router.get("/webhook")
    async def verify(request: Request) -> Response:
        q = request.query_params
        if (
            q.get("hub.mode") == "subscribe"
            and q.get("hub.verify_token") == settings.WA_VERIFY_TOKEN
        ):
            return Response(content=q.get("hub.challenge", ""), media_type="text/plain")
        return Response(status_code=403)

    @router.post("/webhook")
    async def receive(request: Request, background: BackgroundTasks) -> Response:
        body = await request.body()
        sig = request.headers.get("X-Hub-Signature-256")
        # If an app secret is configured, enforce it; empty secret = dev bypass.
        if settings.WA_APP_SECRET and not verify_signature(settings.WA_APP_SECRET, body, sig):
            return Response(status_code=403)

        payload = await request.json()
        for msg in normalize_inbound(payload):
            fresh = await store.record_inbound(
                clinic_id=None,
                wa_number=msg.wa_number,
                wamid=msg.wamid,
                kind=msg.kind,
                payload={"text": msg.text, "button_id": msg.button_id},
                at=msg.timestamp,
            )
            if fresh and _handler is not None:
                background.add_task(_handler, msg)
        return Response(status_code=200)

    return router
