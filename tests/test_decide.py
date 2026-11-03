from app.dates import resolve
from app.decide import AskCustomer, CreateOrder, NeedsReview, NoOrder, OrderState, decide
from app.extraction.schema import ServicePick
from tests.conftest import date_expr, make_extraction


def _decide(x, questions_asked=0, received_at=None):
    return decide(x, OrderState(questions_asked), resolve(x.date, received_at))


def test_complete_request_creates_order(received_at):
    assert _decide(make_extraction(), received_at=received_at) == CreateOrder(overrode_model=False)


def test_model_wants_to_ask_but_order_is_complete(received_at):
    x = make_extraction(outcome="ask_customer", question="Which bike?", missing=["bike_type"])
    assert _decide(x, received_at=received_at) == CreateOrder(overrode_model=True)


def test_missing_date_asks_with_model_question(received_at):
    x = make_extraction(outcome="ask_customer", question="When suits you?", date=date_expr(kind="none"))
    d = _decide(x, received_at=received_at)
    assert d == AskCustomer(question="When suits you?", missing=("requested_date",))


def test_missing_date_without_model_question_uses_template(received_at):
    x = make_extraction(date=date_expr(kind="none"))
    d = _decide(x, received_at=received_at)
    assert isinstance(d, AskCustomer) and "When would you like" in d.question


def test_missing_both_uses_combined_template_in_customer_language(received_at):
    x = make_extraction(services=[], date=date_expr(kind="none"), language="es")
    d = _decide(x, received_at=received_at)
    assert isinstance(d, AskCustomer)
    assert d.missing == ("service", "requested_date")
    assert d.question.startswith("¿Podría")


def test_past_date_counts_as_missing(received_at):
    x = make_extraction(date=date_expr(kind="absolute", absolute_date="2026-01-01"))
    assert isinstance(_decide(x, received_at=received_at), AskCustomer)


def test_second_question_is_unreachable(received_at):
    x = make_extraction(outcome="ask_customer", question="Again?", services=[])
    d = _decide(x, questions_asked=1, received_at=received_at)
    assert d == NeedsReview("still_ambiguous_after_question", "service")


def test_flag_for_staff(received_at):
    x = make_extraction(outcome="flag_for_staff", flag_reason="wrong_shop", flag_detail="Lakeshore")
    assert _decide(x, received_at=received_at) == NeedsReview("wrong_shop", "Lakeshore")


def test_price_inquiry_is_no_order(received_at):
    x = make_extraction(
        outcome="no_work_order",
        flag_reason="price_inquiry",
        services=[ServicePick(code="TUNE_FULL", quantity=1, evidence="full overhaul")],
    )
    assert _decide(x, received_at=received_at) == NoOrder("price_inquiry", None)
