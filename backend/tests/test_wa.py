"""WhatsApp layer tests — no network (Graph API mocked with respx)."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta

import httpx
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import settings as cfg
from app.wa.sender import Sender
from app.wa.store import InMemoryWaStore
from app.wa.templates import get
from app.wa.webhook import build_router, normalize_inbound, set_message_handler, verify_signature

T0 = datetime(2026, 7, 5, 9, 0, tzinfo=UTC)
GRAPH = "https://graph.facebook.com/v20.0/123/messages"
OK = {"messaging_product": "whatsapp", "messages": [{"id": "wamid.OUT"}]}


def run(coro):
    return asyncio.run(coro)


def sender(store, **kw):
    return Sender(store, token="tok", phone_number_id="123", backoff_base=0, **kw)


# --- signature ---------------------------------------------------------- #
def test_verify_signature_valid_and_invalid():
    secret, body = "s3cr3t", b'{"hello":"world"}'
    good = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert verify_signature(secret, body, good) is True
    assert verify_signature(secret, body, "sha256=deadbeef") is False
    assert verify_signature(secret, body, None) is False
    assert verify_signature(secret, body, "md5=x") is False


# --- inbound normalization --------------------------------------------- #
def test_normalize_inbound_text_and_button():
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": "123"},
                            "messages": [
                                {
                                    "from": "+919000000001",
                                    "id": "wamid.1",
                                    "timestamp": "1751706000",
                                    "type": "text",
                                    "text": {"body": "kitna time"},
                                },
                                {
                                    "from": "+919000000002",
                                    "id": "wamid.2",
                                    "timestamp": "1751706001",
                                    "type": "interactive",
                                    "interactive": {
                                        "type": "button_reply",
                                        "button_reply": {"id": "arrived:E9", "title": "आ गया"},
                                    },
                                },
                            ],
                        }
                    }
                ]
            }
        ]
    }
    msgs = normalize_inbound(payload)
    assert [m.kind for m in msgs] == ["text", "button_reply"]
    assert msgs[0].text == "kitna time" and msgs[0].wamid == "wamid.1"
    assert msgs[1].button_id == "arrived:E9" and msgs[1].phone_number_id == "123"


# --- wamid dedupe ------------------------------------------------------- #
def test_wamid_dedupe_insert_or_skip():
    store = InMemoryWaStore()

    async def go():
        a = await store.record_inbound(
            clinic_id=None, wa_number="+91x", wamid="wamid.A", kind="text", payload={}, at=T0
        )
        b = await store.record_inbound(
            clinic_id=None, wa_number="+91x", wamid="wamid.A", kind="text", payload={}, at=T0
        )
        return a, b

    first, second = run(go())
    assert first is True and second is False
    assert len(store.inbound) == 1


# --- 24h window --------------------------------------------------------- #
def test_is_window_open_boundary():
    store = InMemoryWaStore()
    s = sender(store)

    async def go():
        assert await s.is_window_open(T0, "+91x") is False  # no inbound yet
        await store.record_inbound(
            clinic_id=None, wa_number="+91x", wamid="w1", kind="text", payload={}, at=T0
        )
        within = await s.is_window_open(T0 + timedelta(hours=23), "+91x")
        beyond = await s.is_window_open(T0 + timedelta(hours=25), "+91x")
        return within, beyond

    within, beyond = run(go())
    assert within is True and beyond is False


# --- template rendering hi/en ------------------------------------------ #
def test_template_render_hi_and_en_with_button_ids():
    t = get("booking_confirmed")
    ctx = {"name": "Ravi", "token": 14, "eta": "7:20 PM", "report": "7:05 PM", "entry_id": "E1"}
    hi = t.text("hi", ctx)
    en = t.text("en", ctx)
    assert "टोकन नं. 14" in hi and "नमस्ते Ravi" in hi
    assert "Token no. 14" in en and "Hello Ravi" in en
    btn_ids = {b.id for b in t.render_buttons("hi", ctx)}
    assert btn_ids == {"arrived:E1", "cancel:E1"}
    # out-of-window template components carry the ordered params
    assert t.component_params(ctx) == ["Ravi", "14", "7:20 PM", "7:05 PM"]


# --- send: free-form in window ----------------------------------------- #
def test_send_text_posts_and_logs():
    store = InMemoryWaStore()
    s = sender(store)
    with respx.mock:
        route = respx.post(GRAPH).mock(return_value=httpx.Response(200, json=OK))
        run(s.send_text(T0, "+91x", "hello"))
        assert route.called
        body = json.loads(route.calls.last.request.content)
        assert body["type"] == "text" and body["text"]["body"] == "hello"
    assert store.outbound[0]["kind"] == "text"


# --- send(): picks template out of window ------------------------------ #
def test_send_gateway_uses_template_when_window_closed():
    store = InMemoryWaStore()  # no inbound -> window closed
    s = sender(store)
    ctx = {"name": "Ravi", "token": 14, "eta": "7:20 PM", "report": "7:05 PM", "entry_id": "E1"}
    with respx.mock:
        route = respx.post(GRAPH).mock(return_value=httpx.Response(200, json=OK))
        run(s.send(T0, "+91x", template_name="booking_confirmed", ctx=ctx, lang="hi"))
        body = json.loads(route.calls.last.request.content)
    assert body["type"] == "template"
    assert body["template"]["name"] == "booking_confirmed"
    assert body["template"]["language"]["code"] == "hi"
    assert store.outbound[0]["kind"] == "template:booking_confirmed"


# --- retry on 5xx ------------------------------------------------------- #
def test_retry_on_500_then_success():
    store = InMemoryWaStore()
    s = sender(store, max_retries=2)

    async def _noop(_):
        return None

    s._sleep = _noop  # no real backoff delay
    with respx.mock:
        route = respx.post(GRAPH).mock(
            side_effect=[httpx.Response(500), httpx.Response(200, json=OK)]
        )
        run(s.send_text(T0, "+91x", "hi"))
        assert route.call_count == 2


# --- webhook routes (GET verify, POST sig + dedupe) --------------------- #
def _client(store) -> TestClient:
    app = FastAPI()
    app.include_router(build_router(store))
    return TestClient(app)


def test_webhook_get_verify_challenge(monkeypatch):
    monkeypatch.setattr(cfg, "WA_VERIFY_TOKEN", "vtok")
    c = _client(InMemoryWaStore())
    ok = c.get(
        "/webhook",
        params={"hub.mode": "subscribe", "hub.verify_token": "vtok", "hub.challenge": "42"},
    )
    assert ok.status_code == 200 and ok.text == "42"
    bad = c.get(
        "/webhook",
        params={"hub.mode": "subscribe", "hub.verify_token": "nope", "hub.challenge": "42"},
    )
    assert bad.status_code == 403


def test_webhook_post_signature_and_dedupe(monkeypatch):
    monkeypatch.setattr(cfg, "WA_APP_SECRET", "appsec")
    store = InMemoryWaStore()
    seen: list = []

    async def handler(msg):
        seen.append(msg)

    set_message_handler(handler)
    try:
        c = _client(store)
        body = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "metadata": {"phone_number_id": "123"},
                                "messages": [
                                    {
                                        "from": "+919000000001",
                                        "id": "wamid.W1",
                                        "timestamp": "1751706000",
                                        "type": "text",
                                        "text": {"body": "hi"},
                                    }
                                ],
                            }
                        }
                    ]
                }
            ]
        }
        raw = json.dumps(body).encode()
        good = "sha256=" + hmac.new(b"appsec", raw, hashlib.sha256).hexdigest()
        hdr = {"X-Hub-Signature-256": good, "Content-Type": "application/json"}

        bad = c.post("/webhook", content=raw, headers={"X-Hub-Signature-256": "sha256=bad"})
        assert bad.status_code == 403

        assert c.post("/webhook", content=raw, headers=hdr).status_code == 200
        assert c.post("/webhook", content=raw, headers=hdr).status_code == 200  # dup wamid
        assert len(store.inbound) == 1  # deduped
        assert len(seen) == 1  # handler fired exactly once
    finally:
        set_message_handler(None)
