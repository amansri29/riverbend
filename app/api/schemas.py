from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class MessageIn(BaseModel):
    message_id: str = Field(min_length=1, max_length=200)
    channel: Literal["email", "web"]
    received_at: datetime | None = None  # naive values are shop-local
    body: str = Field(min_length=1, max_length=5000)
    in_reply_to: str | None = Field(default=None, max_length=200)


class MessageAccepted(BaseModel):
    message_id: str
    duplicate: bool
    status_url: str


class CustomerStatus(BaseModel):
    """What the customer (via the shop's channel) is allowed to see. No internals."""

    message_id: str
    received_at: datetime
    status: Literal[
        "received",
        "awaiting_your_reply",
        "confirmed",
        "in_review",
        "answered",
        "cancellation_received",
        "could_not_process",
        "expired",
    ]
    message: str
    question: str | None = None
    estimate: EstimateOut | None = None
    requested_date: date | None = None
    date_note: str | None = None


class LineItemOut(BaseModel):
    code: str
    name: str
    quantity: int
    unit_price: str
    line_total: str
    requires_inspection: bool


class EstimateOut(BaseModel):
    currency: str = "USD"
    line_items: list[LineItemOut]
    total: str
    requires_inspection: bool
    catalog_version: str


class WorkOrderOut(BaseModel):
    id: str
    message_id: str | None = None  # the sender's id of the source message
    status: str
    review_reason: str | None
    source_message_id: str
    customer_name: str | None
    language: str
    bike_type: str | None
    bike_count: int
    issues: list[str]
    urgency: str
    requested_date: date | None
    date_note: str | None
    estimate: EstimateOut
    clarification_question: str | None
    questions_asked: int
    amendments: list[dict]
    created_at: datetime
    updated_at: datetime


class BudgetOut(BaseModel):
    month: date
    cap_usd: str
    spent_usd: str
    reserved_usd: str
    exhausted: bool


class AiStatusOut(BaseModel):
    degraded: bool
    waiting: int
    parked_provider_outage: int
    parked_budget_cap: int
    recent_provider_failures: int


class LlmTotalsOut(BaseModel):
    calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: str
    ok: int
    invalid_output: int
    provider_failures: int


class WorkOrderList(BaseModel):
    shop_id: str
    status: str | None
    count: int
    estimated_total: str
    work_orders: list[WorkOrderOut]
    ai: AiStatusOut
    budget: BudgetOut
    llm: LlmTotalsOut
    order_counts: dict[str, int]
    message_outcomes: dict[str, int]


def money(cents: int | None) -> str:
    return f"{(cents or 0) / 100:.2f}"


def micros_to_usd(micros: int) -> str:
    return f"{micros / 1_000_000:.4f}"


def estimate_out(
    line_items: list[dict], total_cents: int | None, requires_inspection: bool, catalog_version: str
) -> EstimateOut:
    return EstimateOut(
        line_items=[
            LineItemOut(
                code=i["code"],
                name=i["name"],
                quantity=i["quantity"],
                unit_price=money(i["unit_price_cents"]),
                line_total=money(i["line_total_cents"]),
                requires_inspection=i["requires_inspection"],
            )
            for i in line_items
        ],
        total=money(total_cents),
        requires_inspection=requires_inspection,
        catalog_version=catalog_version,
    )
