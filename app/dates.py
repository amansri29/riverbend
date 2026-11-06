"""Resolve a classified date expression against the received timestamp.

The model classifies ("Thursday morning" → weekday=thursday, part_of_day=morning); this module
computes. Keeping arithmetic out of the model is the same principle as pricing (ADR-6).
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from app.extraction.schema import DateExpr

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MAX_HORIZON_DAYS = 180


@dataclass(frozen=True)
class ResolvedDate:
    """A date expression resolved in code: the date if any, a note, whether it carries information, an error."""

    date: date | None  # a single requested day, when one can be determined
    note: str | None  # human-readable window when no single day ("October", "any weekday")
    has_info: bool  # the customer said *something* about timing
    error: str | None  # e.g. "requested date is in the past"


def _note(expr: DateExpr, base: str | None) -> str | None:
    parts = [p for p in [base, expr.part_of_day, expr.time] if p]
    return ", ".join(parts) if parts else None


def resolve(expr: DateExpr, received_at: datetime) -> ResolvedDate:
    """Turn a classified DateExpr into a concrete date relative to when the message was received."""
    today = received_at.date()
    kind = expr.kind

    if kind == "none":
        return ResolvedDate(None, None, False, None)

    if kind == "relative_days":
        if expr.relative_days is None or expr.relative_days < 0:
            return ResolvedDate(None, None, True, "relative_days missing or negative")
        if expr.relative_days > MAX_HORIZON_DAYS:
            return ResolvedDate(None, None, True, "requested date too far ahead")
        d = today + timedelta(days=expr.relative_days)
        return ResolvedDate(d, _note(expr, None), True, None)

    if kind == "weekday":
        if expr.weekday not in WEEKDAYS:
            return ResolvedDate(None, None, True, "weekday missing")
        target = WEEKDAYS.index(expr.weekday)
        delta = (target - today.weekday()) % 7
        if delta == 0:
            delta = 7  # "Tuesday" said on a Tuesday means next week's
        d = today + timedelta(days=delta)
        if expr.next_week:
            # If the next occurrence still falls inside the current Mon–Sun week, push a week.
            end_of_week = today + timedelta(days=6 - today.weekday())
            if d <= end_of_week:
                d += timedelta(days=7)
        return ResolvedDate(d, _note(expr, None), True, None)

    if kind == "absolute":
        if not expr.absolute_date:
            return ResolvedDate(None, None, True, "absolute_date missing")
        try:
            d = date.fromisoformat(expr.absolute_date)
        except ValueError:
            return ResolvedDate(None, None, True, f"unparseable date {expr.absolute_date!r}")
        if d < today:
            return ResolvedDate(None, None, True, "requested date is in the past")
        if d > today + timedelta(days=MAX_HORIZON_DAYS):
            return ResolvedDate(None, None, True, "requested date too far ahead")
        return ResolvedDate(d, _note(expr, None), True, None)

    if kind == "month":
        if expr.month is None or not 1 <= expr.month <= 12:
            return ResolvedDate(None, None, True, "month missing or out of range")
        year = today.year if expr.month >= today.month else today.year + 1
        label = f"{calendar.month_name[expr.month]} {year}"
        return ResolvedDate(None, _note(expr, label), True, None)

    # vague: "any day next week", "weekend", "any weekday". The model sometimes files a plain weekday or
    # "tomorrow" under vague; code recovers the single day from the text rather than losing it.
    recovered = _recover_from_text(expr)
    if recovered is not None:
        return resolve(recovered, received_at)
    return ResolvedDate(None, _note(expr, expr.text or "flexible"), True, None)


def _recover_from_text(expr: DateExpr) -> DateExpr | None:
    """A vague expression whose text is really a weekday, today, or tomorrow becomes that kind."""
    words = (expr.text or "").lower().replace(",", " ").split()
    if not words or len(words) > 3:
        return None
    if words == ["today"]:
        return expr.model_copy(update={"kind": "relative_days", "relative_days": 0})
    if words == ["tomorrow"]:
        return expr.model_copy(update={"kind": "relative_days", "relative_days": 1})
    days = [w for w in words if w in WEEKDAYS]
    rest = [w for w in words if w not in WEEKDAYS and w not in ("next", "this")]
    if len(days) == 1 and not rest:
        return expr.model_copy(update={"kind": "weekday", "weekday": days[0], "next_week": "next" in words})
    return None
