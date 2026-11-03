from __future__ import annotations

import json
from datetime import date, datetime
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

COLS = (
    "shop_id, id, source_message_id, status, review_reason, customer_name, language, bike_type, "
    "bike_count, issues, urgency, requested_date, date_note, line_items, estimated_total_cents, "
    "requires_inspection, catalog_version, clarification_question, questions_asked, asked_at, "
    "resolved_by_message_id, amendments, created_at, updated_at"
)


async def create(conn: AsyncConnection, *, shop_id: str, source_message_id: UUID, **fields) -> tuple[dict, bool]:
    """Idempotent on (shop_id, source_message_id): a job that runs twice cannot create two orders."""
    cols = ["shop_id", "source_message_id", *fields]
    vals = [shop_id, source_message_id, *(_pg(v) for v in fields.values())]
    placeholders = ", ".join(["%s"] * len(vals))
    cur = await conn.execute(
        f"INSERT INTO work_orders ({', '.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT (shop_id, source_message_id) DO NOTHING RETURNING {COLS}",
        vals,
    )
    row = await cur.fetchone()
    if row:
        return row, True
    existing = await get_by_source(conn, shop_id, source_message_id)
    assert existing is not None
    return existing, False


async def update(conn: AsyncConnection, shop_id: str, order_id: UUID, **fields) -> dict:
    sets = ", ".join(f"{k} = %s" for k in fields) + ", updated_at = now()"
    cur = await conn.execute(
        f"UPDATE work_orders SET {sets} WHERE shop_id = %s AND id = %s RETURNING {COLS}",
        [*(_pg(v) for v in fields.values()), shop_id, order_id],
    )
    row = await cur.fetchone()
    assert row is not None, "work order vanished under RLS?"
    return row


async def get(conn: AsyncConnection, shop_id: str, order_id: UUID) -> dict | None:
    cur = await conn.execute(f"SELECT {COLS} FROM work_orders WHERE shop_id = %s AND id = %s", (shop_id, order_id))
    return await cur.fetchone()


async def get_by_source(conn: AsyncConnection, shop_id: str, message_pk: UUID) -> dict | None:
    cur = await conn.execute(
        f"SELECT {COLS} FROM work_orders WHERE shop_id = %s AND source_message_id = %s", (shop_id, message_pk)
    )
    return await cur.fetchone()


async def list_by_status(conn: AsyncConnection, shop_id: str, status: str | None) -> list[dict]:
    if status:
        cur = await conn.execute(
            f"SELECT {COLS} FROM work_orders WHERE shop_id = %s AND status = %s ORDER BY created_at",
            (shop_id, status),
        )
    else:
        cur = await conn.execute(f"SELECT {COLS} FROM work_orders WHERE shop_id = %s ORDER BY created_at", (shop_id,))
    return await cur.fetchall()


async def status_counts(conn: AsyncConnection, shop_id: str) -> dict[str, int]:
    cur = await conn.execute(
        "SELECT status, count(*) AS n FROM work_orders WHERE shop_id = %s GROUP BY status", (shop_id,)
    )
    return {r["status"]: int(r["n"]) for r in await cur.fetchall()}


async def add_amendment(conn: AsyncConnection, shop_id: str, order_id: UUID, amendment: dict) -> dict:
    cur = await conn.execute(
        f"UPDATE work_orders SET amendments = amendments || %s::jsonb, updated_at = now() "
        f"WHERE shop_id = %s AND id = %s RETURNING {COLS}",
        (json.dumps([amendment], default=str), shop_id, order_id),
    )
    return await cur.fetchone()


async def find_open_by_customer_name(
    conn: AsyncConnection, shop_id: str, name: str, since: datetime
) -> list[dict]:
    cur = await conn.execute(
        f"SELECT {COLS} FROM work_orders WHERE shop_id = %s AND status IN ('open', 'awaiting_customer') "
        f"AND lower(customer_name) = lower(%s) AND created_at >= %s ORDER BY created_at",
        (shop_id, name, since),
    )
    return await cur.fetchall()


async def expire_stale(conn: AsyncConnection, shop_id: str, *, older_than_days: int) -> int:
    cur = await conn.execute(
        "UPDATE work_orders SET status = 'expired', updated_at = now() "
        "WHERE shop_id = %s AND status = 'awaiting_customer' "
        "AND asked_at < now() - make_interval(days => %s)",
        (shop_id, older_than_days),
    )
    return cur.rowcount


def _pg(v):
    if isinstance(v, (list, dict)):
        return Jsonb(v)
    if isinstance(v, (date, datetime)) or v is None:
        return v
    return v
