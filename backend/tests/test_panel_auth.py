"""Panel JWT auth — pure, DB-free (the HS256 helpers + the FastAPI dependency).

The queue routes themselves need Postgres and are exercised by the Pg
integration suite; here we lock down token integrity and the 401 paths.
"""

from __future__ import annotations

import asyncio
import time
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api import security


def run(coro):
    return asyncio.run(coro)


def test_encode_decode_roundtrip():
    cid = uuid4()
    token = security.encode_token(clinic_id=cid, slug="demo")
    payload = security.decode_token(token)
    assert payload["sub"] == str(cid)
    assert payload["slug"] == "demo"


def test_tampered_signature_rejected():
    token = security.encode_token(clinic_id=uuid4(), slug="demo")
    head, body, _sig = token.split(".")
    forged = f"{head}.{body}.deadbeef"
    with pytest.raises(ValueError):
        security.decode_token(forged)


def test_expired_token_rejected():
    past = time.time() - security.TOKEN_TTL_S - 10
    token = security.encode_token(clinic_id=uuid4(), slug="demo", now=past)
    with pytest.raises(ValueError):
        security.decode_token(token)


def test_dependency_requires_bearer():
    with pytest.raises(HTTPException) as exc:
        run(security.clinic_from_token(authorization=None))
    assert exc.value.status_code == 401


def test_dependency_accepts_valid_token():
    cid = uuid4()
    token = security.encode_token(clinic_id=cid, slug="demo")
    clinic = run(security.clinic_from_token(authorization=f"Bearer {token}"))
    assert clinic.id == cid
    assert clinic.slug == "demo"
