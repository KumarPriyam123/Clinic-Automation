"""The single send() gateway — nothing else talks to the Graph API.

Responsibilities:
  * build Cloud API payloads (text / interactive buttons / interactive list /
    template),
  * pick free-form vs approved template by the 24-hour window,
  * retry 5xx/429 with exponential backoff,
  * log every send to wa_messages via the WaStore.

Every time-sensitive call takes an injected ``now`` (no wall-clock reads).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from uuid import UUID

import httpx

from app.config import settings
from app.wa.store import WaStore
from app.wa.templates import Button, Template, get

WINDOW = timedelta(hours=24)
GRAPH_BASE = "https://graph.facebook.com/v20.0"


class Sender:
    def __init__(
        self,
        store: WaStore,
        *,
        token: str | None = None,
        phone_number_id: str | None = None,
        base_url: str = GRAPH_BASE,
        max_retries: int = 3,
        backoff_base: float = 0.5,
        timeout: float = 15.0,
    ) -> None:
        self._store = store
        self._token = token if token is not None else settings.WA_TOKEN
        self._phone_id = phone_number_id or settings.WA_PHONE_NUMBER_ID
        self._base = base_url.rstrip("/")
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._timeout = timeout
        self._sleep = asyncio.sleep  # patchable in tests

    # --- window ---------------------------------------------------------- #
    async def is_window_open(self, now: datetime, wa_number: str) -> bool:
        last = await self._store.last_inbound_at(wa_number)
        return last is not None and (now - last) <= WINDOW

    # --- gateway: picks free-form (in window) or template (out) ---------- #
    async def send(
        self,
        now: datetime,
        wa_number: str,
        *,
        template_name: str,
        ctx: dict,
        lang: str = "hi",
        clinic_id: UUID | None = None,
        force_template: bool = False,
    ) -> dict:
        tmpl = get(template_name)
        if not force_template and await self.is_window_open(now, wa_number):
            buttons = tmpl.render_buttons(lang, ctx)
            body = tmpl.text(lang, ctx)
            if buttons:
                return await self.send_buttons(now, wa_number, body, buttons, clinic_id=clinic_id)
            return await self.send_text(now, wa_number, body, clinic_id=clinic_id)
        return await self.send_template(now, wa_number, tmpl, lang, ctx, clinic_id=clinic_id)

    # --- low-level typed sends ------------------------------------------ #
    async def send_text(
        self, now: datetime, wa_number: str, text: str, *, clinic_id: UUID | None = None
    ) -> dict:
        payload = {
            "messaging_product": "whatsapp",
            "to": wa_number,
            "type": "text",
            "text": {"body": text},
        }
        return await self._dispatch(payload, wa_number, "text", clinic_id)

    async def send_buttons(
        self,
        now: datetime,
        wa_number: str,
        body: str,
        buttons: list[Button],
        *,
        clinic_id: UUID | None = None,
    ) -> dict:
        if not 1 <= len(buttons) <= 3:
            raise ValueError("WhatsApp reply buttons must number 1–3")
        payload = {
            "messaging_product": "whatsapp",
            "to": wa_number,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": body},
                "action": {
                    "buttons": [
                        {"type": "reply", "reply": {"id": b.id, "title": b.title}} for b in buttons
                    ]
                },
            },
        }
        return await self._dispatch(payload, wa_number, "button", clinic_id)

    async def send_list(
        self,
        now: datetime,
        wa_number: str,
        body: str,
        sections: list[dict],
        *,
        button: str = "चुनें",
        clinic_id: UUID | None = None,
    ) -> dict:
        payload = {
            "messaging_product": "whatsapp",
            "to": wa_number,
            "type": "interactive",
            "interactive": {
                "type": "list",
                "body": {"text": body},
                "action": {"button": button, "sections": sections},
            },
        }
        return await self._dispatch(payload, wa_number, "list", clinic_id)

    async def send_template(
        self,
        now: datetime,
        wa_number: str,
        tmpl: Template,
        lang: str,
        ctx: dict,
        *,
        clinic_id: UUID | None = None,
    ) -> dict:
        components: list[dict] = []
        params = tmpl.component_params(ctx)
        if params:
            components.append(
                {"type": "body", "parameters": [{"type": "text", "text": p} for p in params]}
            )
        for i, b in enumerate(tmpl.render_buttons(lang, ctx)):
            components.append(
                {
                    "type": "button",
                    "sub_type": "quick_reply",
                    "index": i,
                    "parameters": [{"type": "payload", "payload": b.id}],
                }
            )
        payload = {
            "messaging_product": "whatsapp",
            "to": wa_number,
            "type": "template",
            "template": {
                "name": tmpl.name,
                "language": {"code": "hi" if lang == "hi" else "en"},
                "components": components,
            },
        }
        return await self._dispatch(payload, wa_number, f"template:{tmpl.name}", clinic_id)

    # --- transport ------------------------------------------------------- #
    async def _dispatch(
        self, payload: dict, wa_number: str, kind: str, clinic_id: UUID | None
    ) -> dict:
        result = await self._post(payload)
        await self._store.record_outbound(
            clinic_id=clinic_id, wa_number=wa_number, kind=kind, payload=payload
        )
        return result

    async def _post(self, payload: dict) -> dict:
        url = f"{self._base}/{self._phone_id}/messages"
        headers = {"Authorization": f"Bearer {self._token}"}
        delay = self._backoff_base
        last_resp: httpx.Response | None = None
        for attempt in range(self._max_retries + 1):
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(url, json=payload, headers=headers)
            last_resp = resp
            if resp.status_code < 400:
                return resp.json()
            retryable = resp.status_code == 429 or 500 <= resp.status_code < 600
            if retryable and attempt < self._max_retries:
                await self._sleep(delay)
                delay *= 2
                continue
            break
        assert last_resp is not None
        last_resp.raise_for_status()
        return last_resp.json()
