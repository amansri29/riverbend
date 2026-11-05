"""Policy: what to do with a validated extraction. Pure, unit-tested, and the only place
that decides whether to ask the customer a question (ADR-7).

The model proposes; this function disposes. The one-question invariant is the integer
`questions_asked` on the persisted order, so the prompt cannot override it.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.dates import ResolvedDate
from app.extraction.schema import Extraction, MissingField


@dataclass(frozen=True)
class OrderState:
    """The persisted facts decide() needs about the order so far (how many questions were asked)."""

    questions_asked: int = 0


@dataclass(frozen=True)
class CreateOrder:
    """Decision: enough information; price it and open the work order."""

    overrode_model: bool = False  # model wanted to ask, but the order was complete


@dataclass(frozen=True)
class AskCustomer:
    """Decision: ask the customer exactly one question covering the listed missing fields."""

    question: str
    missing: tuple[MissingField, ...]


@dataclass(frozen=True)
class NeedsReview:
    """Decision: hand to staff with a reason instead of acting automatically."""

    reason: str
    detail: str | None = None


@dataclass(frozen=True)
class NoOrder:
    """Decision: no work order (price inquiry, out of scope); the reason is recorded on the message."""

    reason: str
    detail: str | None = None


Decision = CreateOrder | AskCustomer | NeedsReview | NoOrder

_TEMPLATES: dict[str, dict[str, str]] = {
    "en": {
        "requested_date": "When would you like to bring the bike in?",
        "service": "Could you tell us a bit more about what the bike needs?",
        "both": "Could you tell us a bit more about what the bike needs, and when you'd like to bring it in?",
    },
    "es": {
        "requested_date": "¿Qué día le gustaría traer la bicicleta?",
        "service": "¿Podría contarnos un poco más sobre lo que necesita la bicicleta?",
        "both": "¿Podría contarnos un poco más sobre lo que necesita la bicicleta y qué día le gustaría traerla?",
    },
}


def template_question(missing: tuple[MissingField, ...], language: str) -> str:
    """Fallback question in the customer's language when the model offered none."""
    t = _TEMPLATES.get(language, _TEMPLATES["en"])
    needs_date = "requested_date" in missing
    needs_service = "service" in missing
    if needs_date and needs_service:
        return t["both"]
    if needs_service:
        return t["service"]
    return t["requested_date"]


def decide(x: Extraction, state: OrderState, resolved: ResolvedDate) -> Decision:
    """Pure policy: from a validated extraction and the order state, choose order, question, review, or nothing."""
    if x.outcome == "flag_for_staff":
        return NeedsReview(x.flag_reason or "other", x.flag_detail)
    if x.outcome == "no_work_order":
        return NoOrder(x.flag_reason or "other", x.flag_detail)

    missing: list[MissingField] = []
    if not x.services:
        missing.append("service")
    if not resolved.has_info or resolved.error:
        missing.append("requested_date")

    if not missing:
        return CreateOrder(overrode_model=(x.outcome == "ask_customer"))

    if state.questions_asked >= 1:
        return NeedsReview("still_ambiguous_after_question", ", ".join(missing))

    question = (x.question or "").strip() if x.outcome == "ask_customer" else ""
    if not question:
        question = template_question(tuple(missing), x.language)
    return AskCustomer(question=question, missing=tuple(missing))
