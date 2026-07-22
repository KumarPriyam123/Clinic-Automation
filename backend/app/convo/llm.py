"""LLM intent parser — provider-agnostic, strict JSON, temperature 0.

The LLM NEVER mutates state and NEVER generates medical content. It maps free
text (Hinglish + Devanagari) to a fixed Intent schema. Any error, malformed
JSON, or unknown intent collapses to intent='other' so the flow re-asks with
buttons instead of guessing.
"""

from __future__ import annotations

import dataclasses as dc
import json

import httpx

from app.config import settings

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

_SYSTEM = (
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
    try:
        raw = await _call_provider(text, context or {})
        return _coerce(json.loads(raw))
    except Exception:
        return Intent()  # intent='other', confidence 0.0


async def _call_provider(text: str, context: dict) -> str:
    provider = settings.LLM_PROVIDER
    if provider == "claude-haiku":
        return await _call_claude(text)
    return await _call_gemini(text)  # default: gemini-flash


async def _call_gemini(text: str) -> str:
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-1.5-flash:generateContent?key={settings.LLM_API_KEY}"
    )
    body = {
        "system_instruction": {"parts": [{"text": _SYSTEM}]},
        "contents": [{"role": "user", "parts": [{"text": text}]}],
        "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(url, json=body)
        resp.raise_for_status()
        data = resp.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]


async def _call_claude(text: str) -> str:
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
                "system": _SYSTEM,
                "messages": [{"role": "user", "content": text}],
            },
        )
        resp.raise_for_status()
        data = resp.json()
    return data["content"][0]["text"]
