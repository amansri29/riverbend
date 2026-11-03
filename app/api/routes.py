from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from app.api.deps import Tenant, get_db, tenant
from app.api.schemas import (
    AiStatusOut,
    BudgetOut,
    CustomerStatus,
    LlmTotalsOut,
    MessageAccepted,
    MessageIn,
    WorkOrderList,
    WorkOrderOut,
    estimate_out,
    micros_to_usd,
    money,
)
from app.db import Database
from app.ingest import UnknownReference, accept_message, normalise_received_at
from app.repo import budget, jobs, llm_calls, messages, work_orders
from app.repo.budget import current_month

router = APIRouter()


@router.get("/healthz")
async def healthz(db: Database = Depends(get_db)) -> dict:
    async with db.tx() as conn:
        await conn.execute("SELECT 1")
    return {"ok": True}


@router.post("/shops/{shop_id}/messages", response_model=MessageAccepted, status_code=202)
async def post_message(request: Request, payload: MessageIn, t: Tenant = Depends(tenant)) -> MessageAccepted:
    db: Database = request.app.state.db
    received_at = normalise_received_at(payload.received_at, t.shop, datetime.now(UTC))
    try:
        result = await accept_message(
            db,
            request.app.state.dispatcher,
            shop=t.shop,
            message_id=payload.message_id,
            channel=payload.channel,
            received_at=received_at,
            body=payload.body,
            in_reply_to=payload.in_reply_to,
        )
    except UnknownReference as e:
        raise HTTPException(status_code=422, detail=f"unknown in_reply_to {e}") from e
    status_url = str(request.url_for("get_message_status", shop_id=t.shop.id, message_id=payload.message_id))
    if not result.created:
        # Idempotent: the same message again is not an error, and it is not a second work order.
        body = MessageAccepted(message_id=payload.message_id, duplicate=True, status_url=status_url)
        return JSONResponse(status_code=200, content=body.model_dump())
    return MessageAccepted(message_id=payload.message_id, duplicate=False, status_url=status_url)


@router.get("/shops/{shop_id}/messages/{message_id}", response_model=CustomerStatus, name="get_message_status")
async def get_message_status(message_id: str, request: Request, t: Tenant = Depends(tenant)) -> CustomerStatus:
    db: Database = request.app.state.db
    async with db.tenant_tx(t.shop.id) as conn:
        msg = await messages.get_by_message_id(conn, t.shop.id, message_id)
        if msg is None:
            raise HTTPException(status_code=404, detail="message not found")
        # A reply reports on the order it belongs to.
        root = msg
        if msg["in_reply_to"]:
            root = await messages.get(conn, t.shop.id, msg["in_reply_to"]) or msg
        order = await work_orders.get_by_source(conn, t.shop.id, root["id"])
    return _customer_status(msg, root, order)


def _customer_status(msg: dict, root: dict, order: dict | None) -> CustomerStatus:
    base = dict(message_id=msg["message_id"], received_at=msg["received_at"])
    outcome = msg["outcome"]
    if outcome in ("rejected_invalid_output", "failed"):
        return CustomerStatus(
            **base,
            status="could_not_process",
            message="We couldn't process this automatically. A staff member will follow up.",
        )
    if outcome == "no_work_order" and msg.get("outcome_detail", "").startswith("price_inquiry"):
        return CustomerStatus(**base, status="answered", message=msg["outcome_detail"])
    if outcome in ("cancellation_flagged",):
        return CustomerStatus(
            **base,
            status="cancellation_received",
            message="We received your cancellation request. A staff member will confirm.",
        )
    if order is None:
        return CustomerStatus(**base, status="received", message="We received your message and will confirm shortly.")
    st = order["status"]
    est = estimate_out(
        order["line_items"], order["estimated_total_cents"], order["requires_inspection"], order["catalog_version"]
    )
    if st == "awaiting_customer":
        return CustomerStatus(
            **base,
            status="awaiting_your_reply",
            message="We have one question before we can confirm.",
            question=order["clarification_question"],
        )
    if st == "open":
        note = " Final price confirmed after inspection." if order["requires_inspection"] else ""
        return CustomerStatus(
            **base,
            status="confirmed",
            message=f"Your request is booked as an estimate.{note}",
            estimate=est,
            requested_date=order["requested_date"],
            date_note=order["date_note"],
        )
    if st == "expired":
        return CustomerStatus(**base, status="expired", message="We didn't hear back; please send a new message.")
    return CustomerStatus(**base, status="in_review", message="A staff member will follow up with you.")


@router.get("/shops/{shop_id}/work-orders", response_model=WorkOrderList)
async def list_work_orders(
    request: Request,
    t: Tenant = Depends(tenant),
    status: str | None = Query(default="open"),
) -> WorkOrderList:
    db: Database = request.app.state.db
    settings = request.app.state.settings
    now = datetime.now(UTC)
    month = current_month(now, t.shop.timezone)
    status_filter = None if status in (None, "", "all") else status
    async with db.tenant_tx(t.shop.id) as conn:
        rows = await work_orders.list_by_status(conn, t.shop.id, status_filter)
        counts = await work_orders.status_counts(conn, t.shop.id)
        outcomes = await messages.outcome_counts(conn, t.shop.id)
        b = await budget.status(conn, t.shop.id, month, t.shop.monthly_cap_micros)
        llm = await llm_calls.totals(conn, t.shop.id)
        cur = await conn.execute(
            "SELECT count(*) AS n FROM llm_calls WHERE shop_id = %s AND outcome IN ('provider_error','timeout') "
            "AND created_at > %s",
            (t.shop.id, now - timedelta(minutes=5)),
        )
        recent_failures = int((await cur.fetchone())["n"])
    async with db.tx() as conn:
        waiting = await jobs.waiting_count(conn, t.shop.id)
        cur = await conn.execute(
            "SELECT park_reason, count(*) AS n FROM jobs WHERE shop_id = %s AND status = 'parked' GROUP BY 1",
            (t.shop.id,),
        )
        parked = {r["park_reason"]: int(r["n"]) for r in await cur.fetchall()}
    orders = [_order_out(r) for r in rows]
    parked_provider = parked.get("provider_unavailable", 0)
    return WorkOrderList(
        shop_id=t.shop.id,
        status=status_filter,
        count=len(orders),
        estimated_total=money(sum(r["estimated_total_cents"] or 0 for r in rows)),
        work_orders=orders,
        ai=AiStatusOut(
            degraded=parked_provider > 0 or recent_failures >= settings.breaker_failure_threshold,
            waiting=sum(waiting.values()),
            parked_provider_outage=parked_provider,
            parked_budget_cap=parked.get("budget_exceeded", 0),
            recent_provider_failures=recent_failures,
        ),
        budget=BudgetOut(
            month=b.month,
            cap_usd=micros_to_usd(b.cap_micros),
            spent_usd=micros_to_usd(b.spent_micros),
            reserved_usd=micros_to_usd(b.reserved_micros),
            exhausted=b.exhausted,
        ),
        llm=LlmTotalsOut(
            calls=llm["calls"],
            input_tokens=llm["input_tokens"],
            output_tokens=llm["output_tokens"],
            cost_usd=micros_to_usd(llm["cost_micros"]),
            ok=llm["ok"],
            invalid_output=llm["invalid_output"],
            provider_failures=llm["provider_failures"],
        ),
        order_counts=counts,
        message_outcomes=outcomes,
    )


@router.get("/shops/{shop_id}/work-orders/{order_id}", response_model=WorkOrderOut)
async def get_work_order(order_id: str, request: Request, t: Tenant = Depends(tenant)) -> WorkOrderOut:
    db: Database = request.app.state.db
    async with db.tenant_tx(t.shop.id) as conn:
        row = await work_orders.get(conn, t.shop.id, order_id)
    if row is None:
        raise HTTPException(status_code=404, detail="work order not found")
    return _order_out(row)


def _order_out(r: dict) -> WorkOrderOut:
    return WorkOrderOut(
        id=str(r["id"]),
        message_id=r.get("message_id"),
        status=r["status"],
        review_reason=r["review_reason"],
        source_message_id=str(r["source_message_id"]),
        customer_name=r["customer_name"],
        language=r["language"],
        bike_type=r["bike_type"],
        bike_count=r["bike_count"],
        issues=r["issues"],
        urgency=r["urgency"],
        requested_date=r["requested_date"],
        date_note=r["date_note"],
        estimate=estimate_out(
            r["line_items"], r["estimated_total_cents"], r["requires_inspection"], r["catalog_version"]
        ),
        clarification_question=r["clarification_question"],
        questions_asked=r["questions_asked"],
        amendments=r["amendments"],
        created_at=r["created_at"],
        updated_at=r["updated_at"],
    )
