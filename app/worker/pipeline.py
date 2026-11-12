"""The worker pipeline: claim → scope to tenant → budget → model → validate → decide → price → write.

One function per stage, all inside tenant transactions. Everything the brief calls a hard part
meets here: idempotency (unique constraints make a second run a no-op), provider failure (return
RETRY to the broker, or park when the breaker is open), the spend cap (reserve before the call,
settle after, park at the cap), and prices computed in code.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID
from zoneinfo import ZoneInfo

from app.catalog import Catalog
from app.config import Settings
from app.dates import resolve
from app.db import Database
from app.decide import AskCustomer, CreateOrder, NeedsReview, NoOrder, OrderState, decide
from app.extraction.factory import build_provider
from app.extraction.prompt import Turn, build_system_prompt, build_turns
from app.extraction.provider import LLMProvider, ProviderError, ProviderResult, ProviderTimeoutError
from app.extraction.schema import Extraction
from app.extraction.validate import validate_extraction
from app.pricing import Estimate, estimate
from app.repo import budget, jobs, llm_calls, messages, outbound, shops, work_orders
from app.repo.budget import current_month
from app.worker.breaker import CircuitBreaker

log = logging.getLogger("pipeline")


def _ctx(job: dict, msg: dict | None = None) -> dict:
    """Correlation fields every pipeline log line carries, so one message can be followed by eye."""
    c = {"job_id": str(job["id"]), "shop_id": job["shop_id"], "kind": job["kind"], "attempt": job["attempts"]}
    if msg is not None:
        c["message_id"] = msg["message_id"]
    return c


def _ev(level: int, event: str, text: str, ctx: dict, **fields: object) -> None:
    log.log(level, text, extra={**ctx, **fields, "event": event})


class JobResult(StrEnum):
    """What a run tells the push handler: DONE and SKIPPED ack, PARKED acks and leaves the broker, RETRY is a 503."""

    DONE = "DONE"  # ack
    SKIPPED = "SKIPPED"  # ack: nothing to do (already processed, or someone else holds it)
    PARKED = "PARKED"  # ack: left the broker on purpose; the sweeper will republish
    RETRY = "RETRY"  # nack: let the broker redeliver with backoff


@dataclass
class Pipeline:
    """The per-job stages: claim, tenant tx, breaker, budget, model, validate, decide, price, write, settle."""

    db: Database
    provider: LLMProvider
    catalog: Catalog
    settings: Settings
    breaker: CircuitBreaker
    system_prompt: str

    # ------------------------------------------------------------------ entry points
    async def run_job_named(self, job_id: UUID) -> str:
        return (await self.run_job(job_id)).value

    async def dead_letter(self, job_id: UUID) -> None:
        """Broker gave up. Record a terminal failure so the shop sees it."""
        async with self.db.tx() as conn:
            job = await jobs.get(conn, job_id)
            if job is None or job["status"] in ("done",):
                return
            await jobs.fail(conn, job_id, "dead-lettered after max delivery attempts")
        async with self.db.tenant_tx(job["shop_id"]) as conn:
            await messages.set_outcome(
                conn, job["shop_id"], job["message_pk"], "failed", "AI provider unavailable after retries"
            )
        _ev(logging.ERROR, "job.dlq", "broker gave up after max attempts; message marked failed for staff", _ctx(job))

    async def run_job(self, job_id: UUID) -> JobResult:
        async with self.db.tx() as conn:
            job = await jobs.claim(conn, job_id)
        if job is None:
            _ev(
                logging.INFO,
                "job.skipped",
                "nothing to do: already done or held by another worker",
                {"job_id": str(job_id)},
            )
            return JobResult.SKIPPED
        ctx = _ctx(job)
        _ev(logging.INFO, "job.claimed", "job claimed, lease 120 s", ctx)
        try:
            result = await self._run(job)
        except Exception as e:  # noqa: BLE001 - an unexpected crash is retryable from the broker's view
            log.exception("pipeline crashed", extra=ctx)
            async with self.db.tx() as conn:
                await jobs.release_for_retry(conn, job_id, f"crash: {e!r}")
            return JobResult.RETRY
        log.info("job finished", extra={**ctx, "event": f"job.{result.value.lower()}"})
        return result

    # ------------------------------------------------------------------ stages
    async def _run(self, job: dict) -> JobResult:
        shop_id, job_id = job["shop_id"], job["id"]
        now = datetime.now(UTC)
        async with self.db.tx() as conn:
            shop = await shops.get(conn, shop_id)
        assert shop is not None

        # Stage 1: load the conversation inside the tenant. Decide if a model call is needed at all.
        async with self.db.tenant_tx(shop_id) as conn:
            msg = await messages.get(conn, shop_id, job["message_pk"])
            if msg is None:
                await jobs.fail(conn, job_id, "message row missing")
                return JobResult.DONE
            ctx = _ctx(job, msg)
            _ev(logging.INFO, "stage.load", f"{job['kind']} job for message via {msg['channel']}", ctx)
            if job["kind"] == "resume":
                prep = await self._prepare_resume(conn, job, msg, shop, now)
            else:
                prep = await self._prepare_extract(conn, job, msg, shop)
            if isinstance(prep, JobResult):
                return prep
        turns, state, order, root_msg = prep
        _ev(
            logging.INFO,
            "stage.transcript",
            f"{len(turns)} turn(s) for the model",
            ctx,
            questions_asked=state.questions_asked,
        )

        # Stage 2: breaker. An outage must not burn delivery attempts.
        if self.breaker.is_open():
            retry_after = self.breaker.retry_after_seconds() or 1
            await self._park(job_id, "provider_unavailable", now + timedelta(seconds=retry_after))
            _ev(
                logging.WARNING,
                "breaker.open",
                "provider breaker open; parked without a model call",
                ctx,
                retry_after_s=retry_after,
            )
            return JobResult.PARKED

        # Stage 3: reserve budget for the worst case (two calls), committed before the call.
        month = current_month(now, shop.timezone)
        prompt_chars = len(self.system_prompt) + sum(len(t.content) for t in turns)
        reserve_micros = self._worst_case_micros(prompt_chars, calls=2)
        async with self.db.tenant_tx(shop_id) as conn:
            ok = await budget.reserve(
                conn,
                shop_id=shop_id,
                month=month,
                cap_micros=shop.monthly_cap_micros,
                job_id=job_id,
                attempt=job["attempts"],
                micros=reserve_micros,
            )
        if not ok:
            next_month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
            run_after = datetime.combine(next_month, datetime.min.time(), tzinfo=ZoneInfo(shop.timezone))
            await self._park(job_id, "budget_exceeded", run_after)
            _ev(
                logging.WARNING,
                "budget.cap",
                "monthly cap reached; parked until the cap is raised or next month",
                ctx,
                cap_micros=shop.monthly_cap_micros,
                run_after=run_after.date(),
            )
            return JobResult.PARKED
        _ev(
            logging.INFO,
            "budget.reserved",
            "worst case reserved before the call",
            ctx,
            reserved_micros=reserve_micros,
            month=month,
        )

        # Stage 4: the model, with one corrective retry on validation failure.
        received_at = root_msg["received_at"]
        trace_id = f"{shop_id}/{root_msg['message_id']}" + ("/resume" if job["kind"] == "resume" else "")
        spent_micros = 0
        parsed: Extraction | None = None
        errors: list[str] = []
        for attempt_no in (1, 2):
            _ev(
                logging.INFO,
                "model.call",
                f"calling {self.provider.name} (attempt {attempt_no} of 2)",
                ctx,
                turns=len(turns),
            )
            try:
                result = await self.provider.extract(
                    system=self.system_prompt,
                    turns=turns,
                    timeout_s=self.settings.llm_timeout_seconds,
                    max_output_tokens=self.settings.llm_max_output_tokens,
                    trace_id=trace_id,
                )
            except ProviderError as e:
                self.breaker.record_failure()
                async with self.db.tenant_tx(shop_id) as conn:
                    await llm_calls.record(
                        conn,
                        shop_id=shop_id,
                        job_id=job_id,
                        message_pk=msg["id"],
                        provider=self.provider.name,
                        model="-",
                        input_tokens=0,
                        output_tokens=0,
                        cost_micros=0,
                        latency_ms=0,
                        outcome="timeout" if isinstance(e, ProviderTimeoutError) else "provider_error",
                        validation_errors=[str(e)],
                        raw_output=None,
                        attempt=job["attempts"],
                    )
                    await budget.release(conn, shop_id=shop_id, job_id=job_id, attempt=job["attempts"])
                if e.retryable:
                    async with self.db.tx() as conn:
                        await jobs.release_for_retry(conn, job_id, str(e))
                    _ev(
                        logging.WARNING,
                        "provider.retry",
                        f"provider failed ({type(e).__name__}); handing back to the broker",
                        ctx,
                        error=str(e)[:120],
                        breaker_failures=self.breaker.failures,
                    )
                    return JobResult.RETRY
                async with self.db.tx() as conn:
                    await jobs.fail(conn, job_id, str(e))
                async with self.db.tenant_tx(shop_id) as conn:
                    await messages.set_outcome(conn, shop_id, msg["id"], "failed", f"provider rejected: {e}")
                _ev(
                    logging.ERROR,
                    "provider.rejected",
                    "provider rejected the request; not retryable",
                    ctx,
                    error=str(e)[:120],
                )
                return JobResult.DONE

            self.breaker.record_success()
            cost = self._cost_micros(result)
            spent_micros += cost
            parsed = result.parsed
            if parsed is None:
                errors = [f"output did not match the schema ({result.refusal or 'unparseable'})"]
            else:
                errors = validate_extraction(parsed, self.catalog, received_at)
            _ev(
                logging.INFO,
                "model.response",
                f"{result.model} answered in {result.latency_ms} ms",
                ctx,
                input_tokens=result.usage.input_tokens,
                output_tokens=result.usage.output_tokens,
                cost_micros=cost,
                proposed=parsed.outcome if parsed else None,
                services=[f"{p.code}x{p.quantity}" for p in parsed.services] if parsed else None,
                date=parsed.date.kind if parsed else None,
            )
            if errors:
                _ev(
                    logging.WARNING,
                    "model.invalid",
                    "output failed validation" + ("; asking for a correction" if attempt_no == 1 else "; giving up"),
                    ctx,
                    errors=errors,
                )
            else:
                _ev(logging.INFO, "model.valid", "output passed schema and business rules", ctx)
            async with self.db.tenant_tx(shop_id) as conn:
                await llm_calls.record(
                    conn,
                    shop_id=shop_id,
                    job_id=job_id,
                    message_pk=msg["id"],
                    provider=self.provider.name,
                    model=result.model,
                    input_tokens=result.usage.input_tokens,
                    output_tokens=result.usage.output_tokens,
                    cost_micros=cost,
                    latency_ms=result.latency_ms,
                    outcome="ok" if not errors else "invalid_output",
                    validation_errors=errors or None,
                    raw_output=result.raw_text,
                    attempt=attempt_no,
                )
            if not errors:
                break
            if attempt_no == 1:
                turns = turns + [
                    Turn("assistant", result.raw_text or "{}"),
                    Turn(
                        "user",
                        "Your previous output failed validation:\n- "
                        + "\n- ".join(errors)
                        + "\nReturn a corrected object. Use only catalog codes.",
                    ),
                ]

        async with self.db.tenant_tx(shop_id) as conn:
            await budget.settle(
                conn, shop_id=shop_id, job_id=job_id, attempt=job["attempts"], actual_micros=spent_micros
            )
            _ev(logging.INFO, "budget.settled", "reservation settled to actual cost", ctx, spent_micros=spent_micros)
            if errors or parsed is None:
                # Requirement 4: output that fails validation is never saved as a work order.
                await messages.set_outcome(conn, shop_id, msg["id"], "rejected_invalid_output", "; ".join(errors))
                await jobs.fail(conn, job_id, "invalid model output after corrective retry")
                _ev(logging.WARNING, "extraction.rejected", "invalid after the corrective retry; nothing saved", ctx)
                return JobResult.DONE

            # Stage 5: decide and write.
            resolved = resolve(parsed.date, received_at)
            decision = decide(parsed, state, resolved)
            _ev(
                logging.INFO,
                "decide",
                f"code decided {type(decision).__name__} (model proposed {parsed.outcome})",
                ctx,
                requested_date=resolved.date,
                date_note=resolved.note,
                missing=getattr(decision, "missing", None),
                reason=getattr(decision, "reason", None),
            )
            await self._apply(conn, job, msg, root_msg, shop, parsed, resolved, decision, order, now)
            await jobs.complete(conn, job_id)
        return JobResult.DONE

    # ------------------------------------------------------------------ preparation
    async def _prepare_extract(self, conn, job, msg, shop):
        existing = await work_orders.get_by_source(conn, shop.id, msg["id"])
        if existing is not None or msg["outcome"] is not None:
            await jobs.complete(conn, job["id"])  # a job that ran twice: the effect already exists
            _ev(logging.INFO, "job.skipped", "message already processed (redelivery); no model call", _ctx(job, msg))
            return JobResult.SKIPPED
        turns = build_turns(
            shop_name=shop.name, channel=msg["channel"], received_at=msg["received_at"], body=msg["body"]
        )
        return turns, OrderState(0), None, msg

    async def _prepare_resume(self, conn, job, msg, shop, now):
        parent = await messages.get(conn, shop.id, msg["in_reply_to"])
        order = await work_orders.get_by_source(conn, shop.id, parent["id"]) if parent else None
        if msg["outcome"] is not None:
            await jobs.complete(conn, job["id"])
            return JobResult.SKIPPED
        if order is None:
            # The reply overtook the original. Defer, bounded.
            if job["attempts"] > self.settings.max_resume_deferrals:
                await messages.set_outcome(conn, shop.id, msg["id"], "failed", "original message never processed")
                await jobs.fail(conn, job["id"], "parent never processed")
                _ev(
                    logging.ERROR,
                    "resume.orphaned",
                    "original never processed after repeated deferrals",
                    _ctx(job, msg),
                )
                return JobResult.DONE
            await jobs.park(
                conn, job["id"], "parent_pending", now + timedelta(seconds=self.settings.resume_defer_seconds)
            )
            _ev(
                logging.INFO,
                "resume.deferred",
                "reply arrived before its original was processed; parked briefly",
                _ctx(job, msg),
                defer_s=self.settings.resume_defer_seconds,
            )
            return JobResult.PARKED
        if order["status"] != "awaiting_customer":
            # Nothing was asked (or it was already answered). Re-extracting could silently change
            # a price the shop has seen, so attach the text and let staff apply it.
            await work_orders.add_amendment(
                conn,
                shop.id,
                order["id"],
                {"message_id": msg["message_id"], "received_at": msg["received_at"], "body": msg["body"]},
            )
            await work_orders.update(
                conn, shop.id, order["id"], status="needs_review", review_reason="customer_sent_more_information"
            )
            await messages.set_outcome(conn, shop.id, msg["id"], "amendment", str(order["id"]))
            await jobs.complete(conn, job["id"])
            _ev(
                logging.INFO,
                "resume.amendment",
                "order no longer awaiting a reply; text attached, sent to staff review",
                _ctx(job, msg),
                order_id=str(order["id"]),
            )
            return JobResult.DONE
        turns = build_turns(
            shop_name=shop.name,
            channel=parent["channel"],
            received_at=parent["received_at"],
            body=parent["body"],
            question=order["clarification_question"],
            reply=msg["body"],
            reply_received_at=msg["received_at"],
        )
        return turns, OrderState(order["questions_asked"]), order, parent

    # ------------------------------------------------------------------ writing
    async def _apply(self, conn, job, msg, root_msg, shop, x: Extraction, resolved, decision, order, now):
        shop_id = job["shop_id"]
        picks = [(p.code, p.quantity) for p in x.services]
        est: Estimate = estimate(self.catalog, picks)  # validated codes: cannot raise here
        fields = dict(
            customer_name=x.customer_name,
            language=x.language,
            bike_type=x.bike_type,
            bike_count=x.bike_count,
            issues=x.issues,
            urgency=x.urgency,
            requested_date=resolved.date,
            date_note=resolved.note,
            line_items=[i.as_dict() for i in est.line_items],
            estimated_total_cents=est.total_cents,
            requires_inspection=est.requires_inspection,
            catalog_version=est.catalog_version,
        )
        is_resume = job["kind"] == "resume"

        if isinstance(decision, NoOrder):
            detail = (
                f"{decision.reason}: "
                + ", ".join(f"{i.code} x{i.quantity}" for i in est.line_items)
                + f" = {est.total_usd} USD"
            )
            await messages.set_outcome(conn, shop_id, msg["id"], "no_work_order", detail)
            _ev(logging.INFO, "outcome.no_order", f"no work order: {decision.reason}", _ctx(job, msg), detail=detail)
            return

        if isinstance(decision, NeedsReview):
            review = dict(status="needs_review", review_reason=decision.reason)
            if decision.reason == "cancellation" and x.customer_name:
                candidates = await work_orders.find_open_by_customer_name(
                    conn, shop_id, x.customer_name, now - timedelta(days=1)
                )
                if len(candidates) == 1:
                    await work_orders.update(
                        conn,
                        shop_id,
                        candidates[0]["id"],
                        status="needs_review",
                        review_reason="cancellation_requested",
                    )
                    await work_orders.add_amendment(
                        conn,
                        shop_id,
                        candidates[0]["id"],
                        {"message_id": msg["message_id"], "received_at": msg["received_at"], "body": msg["body"]},
                    )
                    await messages.set_outcome(
                        conn, shop_id, msg["id"], "cancellation_flagged", str(candidates[0]["id"])
                    )
                    _ev(
                        logging.INFO,
                        "outcome.cancellation",
                        "matched an open order by customer name; flagged for staff",
                        _ctx(job, msg),
                        order_id=str(candidates[0]["id"]),
                    )
                    return
            if is_resume and order is not None:
                await work_orders.update(
                    conn, shop_id, order["id"], resolved_by_message_id=msg["id"], **fields, **review
                )
            else:
                await work_orders.create(conn, shop_id=shop_id, source_message_id=msg["id"], **fields, **review)
            await messages.set_outcome(conn, shop_id, msg["id"], "needs_review", decision.reason)
            if is_resume:
                await messages.set_outcome(conn, shop_id, root_msg["id"], "needs_review", decision.reason)
            _ev(
                logging.INFO,
                "outcome.review",
                f"sent to staff review: {decision.reason}",
                _ctx(job, msg),
                detail=decision.detail,
                total_cents=est.total_cents,
            )
            return

        if isinstance(decision, AskCustomer):
            row, _ = await work_orders.create(
                conn,
                shop_id=shop_id,
                source_message_id=msg["id"],
                status="awaiting_customer",
                clarification_question=decision.question,
                questions_asked=1,
                asked_at=now,
                **fields,
            )
            await outbound.create(
                conn, shop_id=shop_id, work_order_id=row["id"], channel=msg["channel"], body=decision.question
            )
            await messages.set_outcome(conn, shop_id, msg["id"], "question_asked", ", ".join(decision.missing))
            _ev(
                logging.INFO,
                "outcome.question",
                "one question queued for the customer; order awaiting reply",
                _ctx(job, msg),
                order_id=str(row["id"]),
                missing=list(decision.missing),
                question=decision.question,
            )
            return

        assert isinstance(decision, CreateOrder)
        if decision.overrode_model:
            _ev(
                logging.INFO,
                "decide.override",
                "model wanted to ask, but service and date are present; creating the order",
                _ctx(job, msg),
            )
        if is_resume and order is not None:
            await work_orders.update(
                conn,
                shop_id,
                order["id"],
                status="open",
                review_reason=None,
                resolved_by_message_id=msg["id"],
                **fields,
            )
            await messages.set_outcome(conn, shop_id, msg["id"], "resumed", str(order["id"]))
            await messages.set_outcome(conn, shop_id, root_msg["id"], "work_order", str(order["id"]))
            _ev(
                logging.INFO,
                "outcome.resumed",
                f"order reopened from the reply, total {est.total_usd} USD",
                _ctx(job, msg),
                order_id=str(order["id"]),
                requested_date=resolved.date,
                services=[f"{i.code}x{i.quantity}" for i in est.line_items],
            )
        else:
            row, _ = await work_orders.create(
                conn, shop_id=shop_id, source_message_id=msg["id"], status="open", **fields
            )
            await messages.set_outcome(conn, shop_id, msg["id"], "work_order", str(row["id"]))
            _ev(
                logging.INFO,
                "outcome.order",
                f"work order open, total {est.total_usd} USD (priced in code)",
                _ctx(job, msg),
                order_id=str(row["id"]),
                requested_date=resolved.date,
                services=[f"{i.code}x{i.quantity}" for i in est.line_items],
            )

    # ------------------------------------------------------------------ helpers
    async def _park(self, job_id: UUID, reason: str, run_after: datetime) -> None:
        async with self.db.tx() as conn:
            await jobs.park(conn, job_id, reason, run_after)
        _ev(
            logging.INFO,
            "job.parked",
            f"left the broker: {reason}; the sweeper republishes when due",
            {"job_id": str(job_id)},
            run_after=run_after.isoformat(timespec="seconds"),
        )

    def _worst_case_micros(self, prompt_chars: int, *, calls: int) -> int:
        s = self.settings
        input_tokens = prompt_chars / 3  # conservative: ~3 chars per token
        per_call = (
            input_tokens * s.llm_price_input_micros_per_token
            + s.llm_max_output_tokens * s.llm_price_output_micros_per_token
        )
        return int(per_call * calls) + 1

    def _cost_micros(self, r: ProviderResult) -> int:
        s = self.settings
        return int(
            round(
                r.usage.input_tokens * s.llm_price_input_micros_per_token
                + r.usage.output_tokens * s.llm_price_output_micros_per_token
            )
        )


def build_pipeline(
    settings: Settings,
    db: Database,
    catalog: Catalog,
    *,
    provider: LLMProvider | None = None,
    breaker: CircuitBreaker | None = None,
) -> Pipeline:
    """Wire a Pipeline from settings with the real or an injected provider and breaker."""
    return Pipeline(
        db=db,
        provider=provider or build_provider(settings),
        catalog=catalog,
        settings=settings,
        breaker=breaker
        or CircuitBreaker(
            failure_threshold=settings.breaker_failure_threshold, open_seconds=settings.breaker_open_seconds
        ),
        system_prompt=build_system_prompt(catalog),
    )
