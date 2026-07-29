"""LLM intent parser — provider-agnostic, strict JSON, temperature 0.

The LLM NEVER mutates state and NEVER generates medical content. It maps free
text (Hinglish + Devanagari) to a fixed Intent schema. Any error, malformed
JSON, or unknown intent collapses to intent='other' so the flow re-asks with
buttons instead of guessing.

Model is configured via LLM_MODEL in .env — changing a retired model is a
config-only change, no code change required.
"""

from __future__ import annotations

import dataclasses as dc
import json
import logging

import httpx

from app.config import settings

log = logging.getLogger("clinicq.llm")

VALID_INTENTS = {
    "book",
    "cancel",
    "status",
    "arrived",
    "reschedule",
    "greeting",
    "medical_question",
    "other",
}

_SYSTEM_BASE = (
    "You classify a patient's WhatsApp message to a single-doctor clinic. "
    "Handle Hindi, English, and Hinglish (Latin or Devanagari), e.g. "
    "'kal subah 10 baje', 'shaam ko aaunga', 'शाम को आऊँगा'. "
    "Reply with ONLY a JSON object, no prose, matching exactly: "
    '{"intent": one of '
    "[book,cancel,status,arrived,reschedule,greeting,medical_question,other], "
    '"session_pref": string|null, "time_pref": "HH:MM"|null, '
    '"profile_name": string|null, "confidence": number 0..1}. '
    "time_pref is 24h HH:MM if a specific time is stated, else null. "
    "Any clinical/medical question => intent 'medical_question'. "
    "If unsure => intent 'other' with low confidence."
)

_SESSION_HINT = (
    " The patient has chosen the {session_name!r} session. "
    "Resolve ambiguous bare hours against this window: "
    "'morning' sessions run in AM (e.g. '8 baje' => 08:00), "
    "'evening' sessions run in PM (e.g. '8 baje' => 20:00)."
)


def _build_system(context: dict) -> str:
    sn = context.get("session_name", "")
    if sn:
        return _SYSTEM_BASE + _SESSION_HINT.format(session_name=sn)
    return _SYSTEM_BASE


@dc.dataclass(slots=True)
class Intent:
    intent: str = "other"
    session_pref: str | None = None
    time_pref: str | None = None
    profile_name: str | None = None
    confidence: float = 0.0


def _coerce(data: dict) -> Intent:
    intent = data.get("intent")
    if intent not in VALID_INTENTS:
        return Intent()
    try:
        conf = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        conf = 0.0
    tp = data.get("time_pref")
    return Intent(
        intent=intent,
        session_pref=data.get("session_pref"),
        time_pref=tp if isinstance(tp, str) else None,
        profile_name=data.get("profile_name"),
        confidence=max(0.0, min(1.0, conf)),
    )


async def parse(text: str, context: dict | None = None) -> Intent:
    """Free text -> Intent. Never raises; failures collapse to 'other'."""
    ctx = context or {}
    try:
        raw = await _call_provider(text, ctx)
        return _coerce(json.loads(raw))
    except Exception as exc:
        log.warning("llm_parse_failed %s: %s", type(exc).__name__, exc)
        return Intent()  # intent='other', confidence 0.0


async def _call_provider(text: str, context: dict) -> str:
    provider = settings.LLM_PROVIDER
    if provider == "claude-haiku":
        return await _call_claude(text, context)
    return await _call_gemini(text, context)


async def _call_gemini(text: str, context: dict) -> str:
    model = settings.LLM_MODEL
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={settings.LLM_API_KEY}"
    )
    system = _build_system(context)
    body = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": text}]}],
        "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(url, json=body)
    if resp.status_code != 200:
        log.warning(
            "gemini_non200 model=%s status=%d body=%.300s",
            model,
            resp.status_code,
            resp.text,
        )
        resp.raise_for_status()
    data = resp.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]


async def _call_claude(text: str, context: dict) -> str:
    system = _build_system(context)
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": settings.LLM_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 256,
                "temperature": 0,
                "system": system,
                "messages": [{"role": "user", "content": text}],
            },
        )
    if resp.status_code != 200:
        log.warning(
            "claude_non200 status=%d body=%.300s",
            resp.status_code,
            resp.text,
        )
        resp.raise_for_status()
    data = resp.json()
    return data["content"][0]["text"]
