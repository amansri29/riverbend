"""The model-facing schema. This is exactly what Azure OpenAI structured outputs must return.

Strict-mode rules: every field is required (nullable where optional), no defaults, no extra
properties. Which fields are required *for which outcome* is business logic in
`validate.py` and `decide.py`, not here.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

Weekday = Literal["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
PartOfDay = Literal["morning", "afternoon", "evening"]
Outcome = Literal["work_order", "ask_customer", "flag_for_staff", "no_work_order"]
FlagReason = Literal["wrong_shop", "cancellation", "price_inquiry", "out_of_scope", "other"]
MissingField = Literal["requested_date", "service", "bike_type"]
Urgency = Literal["normal", "urgent"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DateExpr(StrictModel):
    """A classified date phrase. The model never computes a calendar date; code does."""

    kind: Literal["none", "relative_days", "weekday", "absolute", "month", "vague"]
    relative_days: int | None  # 0 = today, 1 = tomorrow
    weekday: Weekday | None
    next_week: bool  # "next Tuesday" as opposed to "Tuesday"
    absolute_date: str | None  # YYYY-MM-DD
    month: int | None  # 1..12, for "sometime in October"
    part_of_day: PartOfDay | None
    time: str | None  # HH:MM, 24h
    text: str | None  # the verbatim phrase, e.g. "any day next week"


class ServicePick(StrictModel):
    code: str  # must be a catalog code; validated in code
    quantity: int  # per-wheel services: number of wheels
    evidence: str  # the words in the message that justify this pick


class Extraction(StrictModel):
    outcome: Outcome
    flag_reason: FlagReason | None
    flag_detail: str | None
    language: str  # ISO 639-1, e.g. "en", "es"
    customer_name: str | None
    bike_type: str | None
    bike_count: int
    issues: list[str]
    services: list[ServicePick]
    urgency: Urgency
    urgency_reason: str | None  # the customer's own words, required when urgent
    date: DateExpr
    question: str | None  # one follow-up question, in the customer's language
    missing: list[MissingField]
