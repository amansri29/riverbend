from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.catalog import Catalog, load_catalog
from app.extraction.schema import DateExpr, Extraction, ServicePick

TZ = ZoneInfo("America/New_York")
RECEIVED = datetime(2026, 9, 22, 8, 2, tzinfo=TZ)  # Tuesday, as in the brief


@pytest.fixture(scope="session")
def catalog() -> Catalog:
    return load_catalog("catalog/catalog.json")


@pytest.fixture
def received_at() -> datetime:
    return RECEIVED


def date_expr(**kw) -> DateExpr:
    base = dict(
        kind="none",
        relative_days=None,
        weekday=None,
        next_week=False,
        absolute_date=None,
        month=None,
        part_of_day=None,
        time=None,
        text=None,
    )
    base.update(kw)
    return DateExpr(**base)


def make_extraction(**kw) -> Extraction:
    base = dict(
        outcome="work_order",
        flag_reason=None,
        flag_detail=None,
        language="en",
        customer_name=None,
        bike_type="road",
        bike_count=1,
        issues=["brakes squeal"],
        services=[ServicePick(code="BRAKE_ADJUST", quantity=2, evidence="brakes squeal")],
        urgency="normal",
        urgency_reason=None,
        date=date_expr(kind="weekday", weekday="saturday"),
        question=None,
        missing=[],
    )
    base.update(kw)
    return Extraction(**base)
