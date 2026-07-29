"""LLM intent parser tests — network mocked with respx (no live calls).

Covers:
  - session-aware time disambiguation ("8 baje" in morning vs evening)
  - standard intents ("kal subah 10 baje", "shaam ko")
  - non-200 collapses to intent='other'
  - session_name context embedded in Gemini request body
"""

from __future__ import annotations

import asyncio
import json
import re

import httpx
import respx

from app.convo.llm import parse

GEMINI_RE = re.compile(r"https://generativelanguage\.googleapis\.com/.*")


def run(coro):
    return asyncio.run(coro)


def _gemini_ok(**fields) -> httpx.Response:
    defaults = {
        "intent": "book",
        "session_pref": None,
        "time_pref": None,
        "profile_name": None,
        "confidence": 0.9,
    }
    defaults.update(fields)
    text = json.dumps(defaults)
    data = {"candidates": [{"content": {"parts": [{"text": text}]}}]}
    return httpx.Response(200, json=data)


# --- session-aware time disambiguation ------------------------------------ #


@respx.mock
def test_morning_8_baje_returns_08_00():
    route = respx.post(GEMINI_RE).mock(return_value=_gemini_ok(time_pref="08:00"))
    intent = run(parse("8 baje", {"session_name": "morning"}))
    assert intent.time_pref == "08:00"
    # session_name must appear in the request so the LLM can use it
    req_body = json.loads(route.calls.last.request.content)
    system_text = req_body["system_instruction"]["parts"][0]["text"]
    assert "morning" in system_text


@respx.mock
def test_evening_8_baje_returns_20_00():
    route = respx.post(GEMINI_RE).mock(return_value=_gemini_ok(time_pref="20:00"))
    intent = run(parse("8 baje", {"session_name": "evening"}))
    assert intent.time_pref == "20:00"
    req_body = json.loads(route.calls.last.request.content)
    system_text = req_body["system_instruction"]["parts"][0]["text"]
    assert "evening" in system_text


@respx.mock
def test_no_session_context_omits_hint():
    route = respx.post(GEMINI_RE).mock(return_value=_gemini_ok(time_pref="08:00"))
    run(parse("8 baje", {}))
    req_body = json.loads(route.calls.last.request.content)
    system_text = req_body["system_instruction"]["parts"][0]["text"]
    # no session context → no session hint in prompt
    assert "chosen the" not in system_text


# --- standard intent fixtures --------------------------------------------- #


@respx.mock
def test_kal_subah_10_baje():
    respx.post(GEMINI_RE).mock(return_value=_gemini_ok(time_pref="10:00"))
    intent = run(parse("kal subah 10 baje", {}))
    assert intent.intent == "book"
    assert intent.time_pref == "10:00"
    assert intent.confidence > 0.0


@respx.mock
def test_shaam_ko_session_pref():
    respx.post(GEMINI_RE).mock(
        return_value=_gemini_ok(intent="book", session_pref="evening", time_pref=None)
    )
    intent = run(parse("shaam ko", {}))
    assert intent.intent == "book"
    assert intent.session_pref == "evening"


# --- failure modes --------------------------------------------------------- #


@respx.mock
def test_non_200_collapses_to_other():
    respx.post(GEMINI_RE).mock(
        return_value=httpx.Response(429, json={"error": {"message": "quota exceeded"}})
    )
    intent = run(parse("anything", {}))
    assert intent.intent == "other"
    assert intent.confidence == 0.0


@respx.mock
def test_malformed_json_collapses_to_other():
    data = {"candidates": [{"content": {"parts": [{"text": "not json {{{"}]}}]}
    respx.post(GEMINI_RE).mock(return_value=httpx.Response(200, json=data))
    intent = run(parse("anything", {}))
    assert intent.intent == "other"


@respx.mock
def test_unknown_intent_collapses_to_other():
    respx.post(GEMINI_RE).mock(return_value=_gemini_ok(intent="fly_to_mars", confidence=0.99))
    intent = run(parse("anything", {}))
    assert intent.intent == "other"
