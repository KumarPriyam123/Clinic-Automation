"""Panel auth: slug + 6-digit PIN -> JWT (HS256, stdlib only).

We hand-roll a minimal HS256 JWT with hmac/hashlib so the backend gains no new
dependency (bcrypt is already required for the PIN hash). The token carries the
clinic id + slug and an expiry; ``clinic_from_token`` is the FastAPI dependency
every panel route depends on.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from uuid import UUID

from fastapi import Depends, Header, HTTPException, status

from app.config import settings

_ALG = "HS256"
TOKEN_TTL_S = 60 * 60 * 12  # 12h — a clinic's working day + margin


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _b64u_decode(seg: str) -> bytes:
    return base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4))


def _sign(signing_input: bytes, secret: str) -> str:
    return _b64u(hmac.new(secret.encode(), signing_input, hashlib.sha256).digest())


def encode_token(*, clinic_id: UUID, slug: str, now: float | None = None) -> str:
    issued = int(now if now is not None else time.time())
    header = _b64u(json.dumps({"alg": _ALG, "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64u(
        json.dumps(
            {"sub": str(clinic_id), "slug": slug, "iat": issued, "exp": issued + TOKEN_TTL_S},
            separators=(",", ":"),
        ).encode()
    )
    signing_input = f"{header}.{payload}".encode()
    return f"{header}.{payload}.{_sign(signing_input, settings.JWT_SECRET)}"


def decode_token(token: str, *, now: float | None = None) -> dict:
    try:
        header_b64, payload_b64, sig = token.split(".")
    except ValueError as exc:
        raise ValueError("malformed token") from exc
    expected = _sign(f"{header_b64}.{payload_b64}".encode(), settings.JWT_SECRET)
    if not hmac.compare_digest(expected, sig):
        raise ValueError("bad signature")
    payload = json.loads(_b64u_decode(payload_b64))
    clock = now if now is not None else time.time()
    if payload.get("exp", 0) < clock:
        raise ValueError("expired")
    return payload


class Clinic:
    """The authenticated principal handed to every route."""

    __slots__ = ("id", "slug")

    def __init__(self, clinic_id: UUID, slug: str) -> None:
        self.id = clinic_id
        self.slug = slug


async def clinic_from_token(authorization: str | None = Header(default=None)) -> Clinic:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    try:
        payload = decode_token(authorization.split(" ", 1)[1].strip())
    except ValueError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
    return Clinic(UUID(payload["sub"]), payload["slug"])


CurrentClinic = Depends(clinic_from_token)
