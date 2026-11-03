"""Outbox + processing record (ADR-4). Not under row-level security: ids only."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from psycopg import AsyncConnection

COLS = (
    "id, shop_id, kind, message_pk, status, attempts, published_at, run_after, park_reason, "
    "last_error, created_at, updated_at"
)
LEASE_SECONDS = 120  # a 'processing' job older than this is considered crashed and reclaimable


async def enqueue(conn: AsyncConnection, *, shop_id: str, kind: str, message_pk: UUID) -> dict:
    cur = await conn.execute(
        f"""
        INSERT INTO jobs (shop_id, kind, message_pk) VALUES (%s, %s, %s)
        ON CONFLICT (shop_id, message_pk, kind) DO NOTHING
        RETURNING {COLS}
        """,
        (shop_id, kind, message_pk),
    )
    row = await cur.fetchone()
    if row:
        return row
    cur = await conn.execute(
        f"SELECT {COLS} FROM jobs WHERE shop_id = %s AND message_pk = %s AND kind = %s",
        (shop_id, message_pk, kind),
    )
    return await cur.fetchone()


async def get(conn: AsyncConnection, job_id: UUID) -> dict | None:
    cur = await conn.execute(f"SELECT {COLS} FROM jobs WHERE id = %s", (job_id,))
    return await cur.fetchone()


async def mark_published(conn: AsyncConnection, job_id: UUID) -> None:
    await conn.execute(
        "UPDATE jobs SET status = 'published', published_at = now(), updated_at = now() "
        "WHERE id = %s AND status IN ('queued', 'parked')",
        (job_id,),
    )


async def claim(conn: AsyncConnection, job_id: UUID) -> dict | None:
    """Move a deliverable job to 'processing'. Returns None when there is nothing to do
    (already done/failed, or someone else holds a live lease) — the caller then acks."""
    cur = await conn.execute(
        f"""
        UPDATE jobs SET status = 'processing', attempts = attempts + 1, updated_at = now()
        WHERE id = %s AND (
              status IN ('queued', 'published')
           OR (status = 'parked' AND run_after <= now())
           OR (status = 'processing' AND updated_at < now() - interval '{LEASE_SECONDS} seconds'))
        RETURNING {COLS}
        """,
        (job_id,),
    )
    return await cur.fetchone()


async def complete(conn: AsyncConnection, job_id: UUID) -> None:
    await conn.execute("UPDATE jobs SET status = 'done', updated_at = now() WHERE id = %s", (job_id,))


async def fail(conn: AsyncConnection, job_id: UUID, error: str) -> None:
    await conn.execute(
        "UPDATE jobs SET status = 'failed', last_error = %s, updated_at = now() WHERE id = %s",
        (error[:2000], job_id),
    )


async def release_for_retry(conn: AsyncConnection, job_id: UUID, error: str) -> None:
    """Hand the job back to the broker's retry policy (we return non-2xx to the push)."""
    await conn.execute(
        "UPDATE jobs SET status = 'published', last_error = %s, updated_at = now() WHERE id = %s",
        (error[:2000], job_id),
    )


async def park(conn: AsyncConnection, job_id: UUID, reason: str, run_after: datetime | None) -> None:
    """Leave the broker (we ack) and wait for the sweeper. run_after=None means 'until released'."""
    await conn.execute(
        "UPDATE jobs SET status = 'parked', park_reason = %s, run_after = %s, updated_at = now() "
        "WHERE id = %s",
        (reason, run_after, job_id),
    )


async def due_for_publish(conn: AsyncConnection, *, unpublished_after_seconds: int) -> list[dict]:
    """Sweeper input: queued rows that never got published, and parked rows whose time has come."""
    cur = await conn.execute(
        f"""
        SELECT {COLS} FROM jobs
        WHERE (status = 'queued' AND created_at < now() - make_interval(secs => %s))
           OR (status = 'parked' AND run_after IS NOT NULL AND run_after <= now())
        ORDER BY created_at
        LIMIT 500
        """,
        (unpublished_after_seconds,),
    )
    return await cur.fetchall()


async def release_parked(conn: AsyncConnection, *, shop_id: str, reason: str) -> int:
    """Used when a cap is raised: parked-for-budget jobs become due immediately."""
    cur = await conn.execute(
        "UPDATE jobs SET run_after = now(), updated_at = now() "
        "WHERE shop_id = %s AND status = 'parked' AND park_reason = %s",
        (shop_id, reason),
    )
    return cur.rowcount


async def waiting_count(conn: AsyncConnection, shop_id: str) -> dict[str, int]:
    cur = await conn.execute(
        "SELECT status, count(*) AS n FROM jobs WHERE shop_id = %s AND status NOT IN ('done', 'failed') "
        "GROUP BY status",
        (shop_id,),
    )
    return {r["status"]: int(r["n"]) for r in await cur.fetchall()}
