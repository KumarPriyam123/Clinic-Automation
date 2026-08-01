"""Queue-snapshot shaping (pure — a stub connection, no DB).

The rest of the panel routes are covered by the DATABASE_URL_TEST-gated suite;
this pins the part that has no SQL in it: read_only, allowed_actions and the
wire shape the panel's TS types read.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.api.panel import _queue_snapshot, _session_list
from app.api.schemas import QueueSnapshot

IST = ZoneInfo("Asia/Kolkata")


def run(coro):
    return asyncio.run(coro)


def today_ist() -> date:
    return datetime.now(IST).date()


class StubCon:
    """Just enough asyncpg surface for _queue_snapshot: one fetch()."""

    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    async def fetch(self, *_args):
        return self._rows


def entry_row(token: int, status: str, **over):
    row = {
        "id": uuid4(),
        "token_number": token,
        "status": status,
        "source": "whatsapp",
        "priority_time": datetime(2026, 8, 1, 12, tzinfo=UTC),
        "eta": datetime(2026, 8, 1, 12, tzinfo=UTC),
        "report_time": None,
        "arrived_at": None,
        "consult_start": None,
        "grace_until": None,
        "next_up": False,
        "name": f"T{token}",
    }
    row.update(over)
    return row


def session_row(day: date, **over):
    row = {
        "id": uuid4(),
        "name": "evening",
        "status": "open",
        "date": day,
        "start_at": datetime(2026, 8, 1, 11, 30, tzinfo=UTC),
        "end_at": datetime(2026, 8, 1, 18, 0, tzinfo=UTC),
        "token_cap": 40,
        "avg_consult_s": 420,
        "doctor_free_at": None,
    }
    row.update(over)
    return row


def snap(day: date, rows: list[dict] | None = None) -> dict:
    return run(_queue_snapshot(StubCon(rows or []), session_row(day)))


# --------------------------------------------------------------------------- #
def test_todays_session_is_actionable():
    body = snap(today_ist(), [entry_row(1, "booked")])
    assert body["session"]["read_only"] is False
    assert "next" in body["session"]["allowed_actions"]


def test_a_future_day_is_read_only_and_offers_no_actions():
    """You cannot serve, admit or mark present a patient in a session that has
    not happened yet — so the server offers no actions for it at all."""
    body = snap(today_ist() + timedelta(days=1), [entry_row(1, "booked")])
    assert body["session"]["read_only"] is True
    assert body["session"]["allowed_actions"] == []
    # ...but the queue itself is still visible: that is the whole point.
    assert len(body["entries"]) == 1


def test_a_past_day_is_read_only_too():
    body = snap(today_ist() - timedelta(days=1))
    assert body["session"]["read_only"] is True


def test_snapshot_validates_against_the_pinned_contract():
    body = snap(
        today_ist(),
        [
            entry_row(1, "booked"),
            entry_row(2, "arrived"),
            entry_row(3, "in_consult", consult_start=datetime(2026, 8, 1, 12, tzinfo=UTC)),
            entry_row(4, "done"),
        ],
    )
    body["sessions"] = _session_list([session_row(today_ist())])
    body["upcoming"] = {"date": (today_ist() + timedelta(days=1)).isoformat(), "count": 3}
    QueueSnapshot.model_validate(body)  # extra="forbid": any drift fails here


def test_counts_split_served_waiting_and_now_serving():
    body = snap(
        today_ist(),
        [
            entry_row(1, "done"),
            entry_row(2, "booked"),
            entry_row(3, "skipped"),
            entry_row(4, "in_consult"),
        ],
    )
    assert body["session"]["served"] == 1
    assert body["session"]["waiting"] == 2  # booked + skipped
    assert body["now_serving"]["token_number"] == 4
    assert [e["token_number"] for e in body["entries"]] == [2, 3]


def test_session_list_carries_the_date_so_the_panel_can_group_by_day():
    day = today_ist()
    items = _session_list([session_row(day)])
    assert items[0]["date"] == day.isoformat()
