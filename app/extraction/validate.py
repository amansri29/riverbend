"""Business-rule validation of a model output, after Pydantic has checked the shape.

Returns a list of human-readable errors. An empty list means the extraction may be acted on.
These errors are fed back to the model for exactly one corrective retry; if it still fails,
the output is recorded as invalid and nothing is saved (brief, requirement 4).
"""

from __future__ import annotations

import re
from datetime import datetime

from app.catalog import Catalog
from app.dates import resolve
from app.extraction.schema import Extraction
from app.pricing import MAX_QUANTITY

_LANG = re.compile(r"^[a-z]{2}$")
_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def validate_extraction(x: Extraction, catalog: Catalog, received_at: datetime) -> list[str]:
    errors: list[str] = []

    for pick in x.services:
        if catalog.get(pick.code) is None:
            errors.append(f"unknown service code {pick.code!r}; use only codes from the catalog")
        if not 1 <= pick.quantity <= MAX_QUANTITY:
            errors.append(f"quantity {pick.quantity} for {pick.code} must be between 1 and {MAX_QUANTITY}")

    if not 1 <= x.bike_count <= 4:
        errors.append("bike_count must be between 1 and 4")

    if not _LANG.match(x.language):
        errors.append("language must be a two-letter ISO 639-1 code")

    if x.urgency == "urgent" and not (x.urgency_reason or "").strip():
        errors.append("urgency 'urgent' requires urgency_reason quoting the customer's own words")

    if x.outcome == "ask_customer" and not (x.question or "").strip():
        errors.append("outcome 'ask_customer' requires a question")

    if x.outcome in ("flag_for_staff", "no_work_order") and x.flag_reason is None:
        errors.append(f"outcome {x.outcome!r} requires flag_reason")

    if x.date.time and not _TIME.match(x.date.time):
        errors.append("date.time must be HH:MM in 24h format")

    resolved = resolve(x.date, received_at)
    if resolved.error:
        errors.append(f"date: {resolved.error}")

    return errors
