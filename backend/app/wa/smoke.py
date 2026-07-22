"""Smoke test CLI: send one interactive button message to a number.

    python -m app.wa.smoke +91XXXXXXXXXX

Uses the real Graph API with WA_TOKEN / WA_PHONE_NUMBER_ID from the env, so the
target must be a whitelisted recipient on the Meta test number. Logs the send
to wa_messages if a DB is configured, else uses an in-memory store.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime

from app.wa.sender import Sender
from app.wa.store import InMemoryWaStore
from app.wa.templates import Button


async def _run(to: str) -> None:
    sender = Sender(InMemoryWaStore())
    now = datetime.now(tz=UTC)
    resp = await sender.send_buttons(
        now,
        to,
        "ClinicQ test ✅ — tap a button to confirm the round-trip.",
        [
            Button(id="arrived:test", title="📍 आ गया / Arrived"),
            Button(id="cancel:test", title="❌ Cancel"),
        ],
    )
    print("sent:", resp)


def main() -> None:
    if len(sys.argv) != 2 or not sys.argv[1].startswith("+"):
        print("usage: python -m app.wa.smoke +91XXXXXXXXXX", file=sys.stderr)
        raise SystemExit(2)
    asyncio.run(_run(sys.argv[1]))


if __name__ == "__main__":
    main()
