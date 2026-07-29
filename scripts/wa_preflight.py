"""wa_preflight.py — pre-session sanity check for the WA round-trip.

Run before every test session:
    cd backend && .venv/Scripts/python.exe ../scripts/wa_preflight.py

Checks:
  1. .env has all four WA_* vars, WA_APP_SECRET looks valid (32 hex chars)
  2. DB reachable and demo clinic has the right wa_phone_number_id
  3. GET /webhook verify endpoint echoes the challenge (backend must be running)
  4. App is subscribed to the WABA (subscribed_apps)
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import sys
import urllib.request
import urllib.parse

REQUIRED = [
    "WA_TOKEN",
    "WA_PHONE_NUMBER_ID",
    "WA_VERIFY_TOKEN",
    "WA_APP_SECRET",
]
EXPECTED_PHONE_ID = "1198540706681830"
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")


def _env() -> dict[str, str]:
    # load .env from current dir if present
    env: dict[str, str] = {}
    env_file = ".env"
    if os.path.exists(env_file):
        for line in open(env_file, encoding="utf-8"):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    env.update({k: v for k, v in os.environ.items()})
    return env


def ok(label: str) -> None:
    print(f"  PASS  {label}")


def fail(label: str, detail: str = "") -> None:
    print(f"  FAIL  {label}" + (f" — {detail}" if detail else ""))


def warn(label: str, detail: str = "") -> None:
    print(f"  WARN  {label}" + (f" — {detail}" if detail else ""))


def check_env(env: dict[str, str]) -> bool:
    print("\n[1] ENV vars")
    passed = True
    for k in REQUIRED:
        v = env.get(k, "")
        if not v:
            fail(k, "missing or empty")
            passed = False
        elif k == "WA_APP_SECRET" and len(v) != 32:
            fail(k, f"expected 32 hex chars, got {len(v)}")
            passed = False
        elif k == "WA_APP_SECRET":
            ok(f"{k} (len=32)")
        else:
            ok(f"{k} (set)")
    return passed


async def check_db(env: dict[str, str]) -> bool:
    print("\n[2] Database — demo clinic wa_phone_number_id")
    try:
        import asyncpg
    except ImportError:
        fail("asyncpg", "not installed")
        return False

    dsn = env.get("DATABASE_URL", "")
    if not dsn:
        fail("DATABASE_URL", "not set")
        return False

    try:
        con = await asyncpg.connect(dsn)
        row = await con.fetchrow(
            "SELECT slug, wa_phone_number_id FROM clinics WHERE slug = $1", "demo"
        )
        await con.close()
    except Exception as e:
        fail("DB connect", str(e))
        return False

    if row is None:
        fail("demo clinic", "row not found — run: make db-reset")
        return False

    phone_id = row["wa_phone_number_id"]
    if phone_id == EXPECTED_PHONE_ID:
        ok(f"demo clinic wa_phone_number_id = {phone_id}")
        return True
    else:
        fail(
            "demo clinic wa_phone_number_id",
            f"got {phone_id!r}, expected {EXPECTED_PHONE_ID!r}",
        )
        print(
            f"    Fix: UPDATE clinics SET wa_phone_number_id = '{EXPECTED_PHONE_ID}' "
            "WHERE slug = 'demo';"
        )
        return False


def check_webhook_verify(env: dict[str, str]) -> bool:
    print("\n[3] GET /webhook verify handshake")
    verify_token = env.get("WA_VERIFY_TOKEN", "")
    challenge = "preflight_challenge_42"
    url = (
        f"{BACKEND_URL}/webhook"
        f"?hub.mode=subscribe"
        f"&hub.verify_token={urllib.parse.quote(verify_token)}"
        f"&hub.challenge={challenge}"
    )
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            body = resp.read().decode()
            status = resp.status
    except Exception as e:
        fail(f"GET {BACKEND_URL}/webhook", str(e))
        print("    Is the backend running? cd backend && .venv/Scripts/python.exe -m uvicorn app.main:app --reload")
        return False

    if status == 200 and body == challenge:
        ok(f"GET /webhook echoed challenge (HTTP {status})")
        return True
    elif status == 403:
        fail("GET /webhook", f"HTTP 403 — WA_VERIFY_TOKEN mismatch? token={verify_token!r}")
        return False
    else:
        fail("GET /webhook", f"HTTP {status} body={body!r}")
        return False


def _app_name(app: object) -> str:
    """Defensive name extraction — Meta's subscribed_apps shape varies by token type."""
    if not isinstance(app, dict):
        return "?"
    # Top-level name (system-user token) OR nested whatsapp_business_api_data.name
    name = app.get("name")
    if not name:
        wba = app.get("whatsapp_business_api_data")
        if isinstance(wba, dict):
            name = wba.get("name")
    return str(name) if name else "?"


def check_subscribed_apps(env: dict[str, str]) -> bool:
    print("\n[4] WABA subscribed_apps")
    token = env.get("WA_TOKEN", "")
    waba_id = "1328874952562037"
    url = f"https://graph.facebook.com/v20.0/{waba_id}/subscribed_apps"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        import json
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        fail("subscribed_apps API call", str(e))
        return False

    try:
        apps = data.get("data", []) if isinstance(data, dict) else []
    except Exception:
        apps = []

    if apps:
        names = [_app_name(a) for a in apps]
        ok(f"WABA subscribed ({len(apps)} app(s)): {names}")
        return True
    else:
        fail("subscribed_apps", "no apps subscribed — POST /<waba_id>/subscribed_apps")
        return False


async def main() -> int:
    env = _env()
    results: list[bool] = []

    results.append(check_env(env))
    results.append(await check_db(env))
    results.append(check_webhook_verify(env))
    results.append(check_subscribed_apps(env))

    print()
    if all(results):
        print("All checks PASSED. Ready to test.")
        return 0
    else:
        n_fail = results.count(False)
        print(f"{n_fail} check(s) FAILED. Fix above before testing.")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
