from app.extraction.schema import ServicePick
from app.extraction.validate import validate_extraction
from tests.conftest import date_expr, make_extraction


def test_valid_extraction_has_no_errors(catalog, received_at):
    assert validate_extraction(make_extraction(), catalog, received_at) == []


def test_unknown_code(catalog, received_at):
    x = make_extraction(services=[ServicePick(code="FREE_VIP", quantity=1, evidence="x")])
    errs = validate_extraction(x, catalog, received_at)
    assert any("unknown service code" in e for e in errs)


def test_quantity_bounds(catalog, received_at):
    x = make_extraction(services=[ServicePick(code="FLAT_FIX", quantity=9, evidence="x")])
    assert any("between 1 and 4" in e for e in validate_extraction(x, catalog, received_at))


def test_urgent_needs_reason(catalog, received_at):
    x = make_extraction(urgency="urgent", urgency_reason=None)
    assert any("urgency_reason" in e for e in validate_extraction(x, catalog, received_at))


def test_ask_needs_question(catalog, received_at):
    x = make_extraction(outcome="ask_customer", question="  ")
    assert any("requires a question" in e for e in validate_extraction(x, catalog, received_at))


def test_flag_needs_reason(catalog, received_at):
    x = make_extraction(outcome="flag_for_staff", flag_reason=None)
    assert any("flag_reason" in e for e in validate_extraction(x, catalog, received_at))


def test_past_date_is_error(catalog, received_at):
    x = make_extraction(date=date_expr(kind="absolute", absolute_date="2026-01-01"))
    assert any("past" in e for e in validate_extraction(x, catalog, received_at))


def test_bad_time_and_language(catalog, received_at):
    x = make_extraction(language="EN", date=date_expr(kind="weekday", weekday="friday", time="4pm"))
    errs = validate_extraction(x, catalog, received_at)
    assert any("language" in e for e in errs) and any("HH:MM" in e for e in errs)
