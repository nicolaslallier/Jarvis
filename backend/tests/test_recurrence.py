from datetime import datetime

import pytest

from app.recurrence import parse_recurrence


def test_daily():
    anchor = datetime(2026, 1, 1, 9, 0)
    assert parse_recurrence("daily").next_after(anchor) == datetime(2026, 1, 2, 9, 0)


def test_weekly():
    anchor = datetime(2026, 1, 1, 9, 0)
    assert parse_recurrence("weekly").next_after(anchor) == datetime(2026, 1, 8, 9, 0)


def test_monthly():
    anchor = datetime(2026, 3, 15, 9, 0)
    assert parse_recurrence("monthly").next_after(anchor) == datetime(2026, 4, 15, 9, 0)


def test_every_n_days():
    anchor = datetime(2026, 1, 1, 9, 0)
    assert parse_recurrence("every 3 days").next_after(anchor) == datetime(2026, 1, 4, 9, 0)
    assert parse_recurrence("every 10 days").next_after(anchor) == datetime(2026, 1, 11, 9, 0)


def test_rule_is_case_and_whitespace_insensitive():
    anchor = datetime(2026, 1, 1, 9, 0)
    assert parse_recurrence("  Daily  ").next_after(anchor) == datetime(2026, 1, 2, 9, 0)
    assert parse_recurrence("Every 2 Days".lower()).next_after(anchor) == datetime(2026, 1, 3, 9, 0)


def test_invalid_rule_raises_value_error():
    with pytest.raises(ValueError):
        parse_recurrence("fortnightly")
    with pytest.raises(ValueError):
        parse_recurrence("every days")
    with pytest.raises(ValueError):
        parse_recurrence("")


def test_every_n_days_rejects_zero():
    with pytest.raises(ValueError):
        parse_recurrence("every 0 days")


def test_monthly_rollover_jan_31_clamps_to_feb():
    # Jan 31 + 1 month has no Feb 31 — clamp to the last day of Feb.
    anchor = datetime(2026, 1, 31, 8, 30)
    assert parse_recurrence("monthly").next_after(anchor) == datetime(2026, 2, 28, 8, 30)


def test_monthly_rollover_across_year_boundary():
    anchor = datetime(2026, 12, 15, 0, 0)
    assert parse_recurrence("monthly").next_after(anchor) == datetime(2027, 1, 15, 0, 0)


def test_monthly_rollover_leap_year_feb():
    # 2028 is a leap year, so Jan 31 + 1 month clamps to Feb 29, not 28.
    anchor = datetime(2028, 1, 31, 0, 0)
    assert parse_recurrence("monthly").next_after(anchor) == datetime(2028, 2, 29, 0, 0)
