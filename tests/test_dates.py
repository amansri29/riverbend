from datetime import date

import pytest

from app.dates import resolve
from tests.conftest import date_expr

# Received Tuesday 2026-09-22.


@pytest.mark.parametrize(
    "weekday,next_week,expected",
    [
        ("wednesday", False, date(2026, 9, 23)),
        ("thursday", False, date(2026, 9, 24)),
        ("friday", False, date(2026, 9, 25)),
        ("saturday", False, date(2026, 9, 26)),
        ("sunday", False, date(2026, 9, 27)),
        ("monday", False, date(2026, 9, 28)),
        ("tuesday", False, date(2026, 9, 29)),  # same weekday as today → a week out
        ("monday", True, date(2026, 9, 28)),  # "next Monday"
        ("tuesday", True, date(2026, 9, 29)),  # "next Tuesday"
        ("wednesday", True, date(2026, 9, 30)),  # "next Wednesday" skips tomorrow
    ],
)
def test_weekdays(received_at, weekday, next_week, expected):
    r = resolve(date_expr(kind="weekday", weekday=weekday, next_week=next_week), received_at)
    assert r.date == expected and r.has_info and r.error is None


def test_relative_days(received_at):
    assert resolve(date_expr(kind="relative_days", relative_days=0), received_at).date == date(2026, 9, 22)
    assert resolve(date_expr(kind="relative_days", relative_days=1), received_at).date == date(2026, 9, 23)


def test_part_of_day_and_time_become_note(received_at):
    r = resolve(date_expr(kind="weekday", weekday="thursday", part_of_day="morning", time="10:00"), received_at)
    assert r.date == date(2026, 9, 24)
    assert r.note == "morning, 10:00"


def test_absolute(received_at):
    r = resolve(date_expr(kind="absolute", absolute_date="2026-10-04"), received_at)
    assert r.date == date(2026, 10, 4)


def test_absolute_in_past_is_error(received_at):
    r = resolve(date_expr(kind="absolute", absolute_date="2026-09-01"), received_at)
    assert r.date is None and r.error and "past" in r.error


def test_absolute_unparseable(received_at):
    r = resolve(date_expr(kind="absolute", absolute_date="October 4"), received_at)
    assert r.error


def test_month_this_year_and_next(received_at):
    r = resolve(date_expr(kind="month", month=10), received_at)
    assert r.date is None and r.note == "October 2026" and r.has_info
    r = resolve(date_expr(kind="month", month=3), received_at)
    assert r.note == "March 2027"


def test_vague_keeps_text(received_at):
    r = resolve(date_expr(kind="vague", text="any day next week"), received_at)
    assert r.date is None and r.note == "any day next week" and r.has_info


def test_none_has_no_info(received_at):
    r = resolve(date_expr(kind="none"), received_at)
    assert not r.has_info and r.date is None and r.error is None
