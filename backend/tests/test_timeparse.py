"""Ambiguous bare-time resolution (pure — no LLM, no network, no DB).

Production bug this pins: a patient typed "11:30" into a 17:00–23:30 evening
session, it was read as 11:30 AM, and the engine's rule-1 clamp then handed
them 5:00 PM with no explanation. The parse was wrong, not the clamp.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.convo.timeparse import Outcome, Window, has_meridiem, resolve, window_from

IST = ZoneInfo("Asia/Kolkata")

DAY = date(2026, 8, 1)
TOMORROW = DAY + timedelta(days=1)


def ist(day: date, h: int, m: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, h, m, tzinfo=IST).astimezone(UTC)


def window(day: date, start_h: int, start_m: int, end_h: int, end_m: int) -> Window:
    return Window(date=day, start_at=ist(day, start_h, start_m), end_at=ist(day, end_h, end_m))


EVENING = window(DAY, 17, 0, 23, 30)  # the production session
MORNING = window(DAY, 9, 0, 13, 0)
EARLY = window(DAY, 8, 0, 13, 0)

NOW = ist(DAY, 23, 10)  # 23:10 IST — when the live booking happened


def hhmm(at: datetime | None) -> str:
    return "" if at is None else at.astimezone(IST).strftime("%H:%M")


# --- the reported bug ------------------------------------------------------ #
def test_bare_1130_in_evening_session_resolves_to_2330():
    r = resolve(NOW, "11:30", explicit=False, window=EVENING)
    assert r.outcome is Outcome.ok
    assert hhmm(r.at) == "23:30"
    assert r.at.astimezone(IST).date() == DAY


def test_bare_1130_in_morning_session_stays_1130():
    r = resolve(ist(DAY, 9, 30), "11:30", explicit=False, window=MORNING)
    assert r.outcome is Outcome.ok
    assert hhmm(r.at) == "11:30"


def test_bare_8_in_evening_session_is_2000():
    r = resolve(ist(DAY, 17, 30), "08:00", explicit=False, window=EVENING)
    assert r.outcome is Outcome.ok
    assert hhmm(r.at) == "20:00"


def test_bare_8_in_morning_session_is_0800():
    r = resolve(ist(DAY, 7, 0), "20:00", explicit=False, window=EARLY)
    assert r.outcome is Outcome.ok
    # the LLM guessed PM; only the AM reading is servable in an 08:00-13:00 slot
    assert hhmm(r.at) == "08:00"


def test_explicit_pm_outside_morning_window_is_out_of_window():
    """'8 PM' in a morning session: the marker is explicit, so we do NOT
    silently reinterpret it as 08:00 — the flow re-asks instead."""
    r = resolve(ist(DAY, 9, 0), "20:00", explicit=True, window=MORNING)
    assert r.outcome is Outcome.out_of_window
    assert r.at is None


def test_kal_subah_10_baje_lands_on_tomorrows_session_date():
    tomorrow_morning = window(TOMORROW, 9, 0, 13, 0)
    r = resolve(NOW, "10:00", explicit=True, window=tomorrow_morning)
    assert r.outcome is Outcome.ok
    assert r.at.astimezone(IST).date() == TOMORROW
    assert hhmm(r.at) == "10:00"


# --- the remaining branches ------------------------------------------------ #
def test_neither_reading_inside_window_is_out_of_window():
    """'8 baje' against a 09:00-13:00 session: 08:00 is too early, 20:00 too
    late. Never clamp — the caller re-asks."""
    r = resolve(ist(DAY, 9, 0), "08:00", explicit=False, window=MORNING)
    assert r.outcome is Outcome.out_of_window
    assert r.ambiguous is True


def test_both_readings_inside_picks_nearest_to_the_live_clock():
    all_day = window(DAY, 6, 0, 23, 59)  # both 09:30 and 21:30 are servable
    late = resolve(ist(DAY, 20, 0), "09:30", explicit=False, window=all_day)
    assert hhmm(late.at) == "21:30"
    early = resolve(ist(DAY, 7, 0), "09:30", explicit=False, window=all_day)
    assert hhmm(early.at) == "09:30"


def test_both_inside_before_session_starts_measures_from_session_start():
    all_day = window(DAY, 18, 0, 23, 59)
    r = resolve(ist(DAY, 6, 0), "07:00", explicit=False, window=all_day)
    assert hhmm(r.at) == "19:00"


def test_window_bounds_are_inclusive():
    assert hhmm(resolve(NOW, "17:00", explicit=True, window=EVENING).at) == "17:00"
    assert hhmm(resolve(NOW, "23:30", explicit=True, window=EVENING).at) == "23:30"


def test_afternoon_hours_are_unambiguous_but_still_checked():
    r = resolve(ist(DAY, 17, 30), "19:00", explicit=False, window=EVENING)
    assert hhmm(r.at) == "19:00"  # the 07:00 reading is outside, so 19:00 wins


def test_garbage_time_is_invalid_not_a_guess():
    for bad in (None, "", "abc", "25:00", "10:75", "10"):
        assert resolve(NOW, bad, explicit=False, window=EVENING).outcome is Outcome.invalid


def test_no_window_falls_back_to_todays_date():
    """Conversation context predating this feature: degrade, never crash."""
    r = resolve(NOW, "11:30", explicit=False, window=None)
    assert r.outcome is Outcome.ok
    assert r.at.astimezone(IST).date() == DAY
    assert hhmm(r.at) == "11:30"


# --- marker detection ------------------------------------------------------ #
def test_meridiem_markers_latin_and_devanagari():
    for text in (
        "8 PM",
        "8 p.m.",
        "shaam 7 baje",
        "kal subah 10 baje",
        "शाम को आऊँगा",
        "सुबह 9 बजे",
        "रात 8 baje",
        "tomorrow morning 10",
    ):
        assert has_meridiem(text), text


def test_bare_times_have_no_marker():
    for text in ("11:30", "8 baje", "10 बजे", "", None, "kal 11:30"):
        assert not has_meridiem(text), text


# --- context round-trip ---------------------------------------------------- #
def test_window_from_context_round_trip():
    meta = {
        "date": DAY.isoformat(),
        "start_at": EVENING.start_at.isoformat(),
        "end_at": EVENING.end_at.isoformat(),
    }
    assert window_from(meta) == EVENING


def test_window_from_bad_context_is_none():
    for meta in (None, {}, {"date": "nope"}, {"date": DAY.isoformat()}):
        assert window_from(meta) is None
