from __future__ import annotations

from uuid import UUID

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb


async def record(
    conn: AsyncConnection,
    *,
    shop_id: str,
    job_id: UUID | None,
    message_pk: UUID,
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cost_micros: int,
    latency_ms: int,
    outcome: str,
    validation_errors: list[str] | None,
    raw_output: str | None,
    attempt: int,
) -> None:
    await conn.execute(
        """
        INSERT INTO llm_calls (shop_id, job_id, message_pk, provider, model, input_tokens, output_tokens,
                               cost_micros, latency_ms, outcome, validation_errors, raw_output, attempt)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            shop_id, job_id, message_pk, provider, model, input_tokens, output_tokens, cost_micros,
            latency_ms, outcome, Jsonb(validation_errors) if validation_errors is not None else None,
            raw_output, attempt,
        ),
    )


async def totals(conn: AsyncConnection, shop_id: str) -> dict:
    cur = await conn.execute(
        """
        SELECT count(*) AS calls,
               coalesce(sum(input_tokens), 0) AS input_tokens,
               coalesce(sum(output_tokens), 0) AS output_tokens,
               coalesce(sum(cost_micros), 0) AS cost_micros,
               count(*) FILTER (WHERE outcome = 'ok') AS ok,
               count(*) FILTER (WHERE outcome = 'invalid_output') AS invalid_output,
               count(*) FILTER (WHERE outcome IN ('provider_error', 'timeout')) AS provider_failures
        FROM llm_calls WHERE shop_id = %s
        """,
        (shop_id,),
    )
    r = await cur.fetchone()
    return {k: int(v) for k, v in r.items()}
