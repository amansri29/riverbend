from __future__ import annotations

from datetime import datetime
from uuid import UUID

from psycopg import AsyncConnection

COLS = "shop_id, id, message_id, channel, received_at, body, in_reply_to, outcome, outcome_detail, created_at"


async def insert(
    conn: AsyncConnection,
    *,
    shop_id: str,
    message_id: str,
    channel: str,
    received_at: datetime,
    body: str,
    in_reply_to: UUID | None,
) -> tuple[dict, bool]:
    """Idempotent on (shop_id, message_id). Returns (row, created)."""
    cur = await conn.execute(
        f"""
        INSERT INTO inbound_messages (shop_id, message_id, channel, received_at, body, in_reply_to)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (shop_id, message_id) DO NOTHING
        RETURNING {COLS}
        """,
        (shop_id, message_id, channel, received_at, body, in_reply_to),
    )
    row = await cur.fetchone()
    if row:
        return row, True
    existing = await get_by_message_id(conn, shop_id, message_id)
    assert existing is not None
    return existing, False


async def get_by_message_id(conn: AsyncConnection, shop_id: str, message_id: str) -> dict | None:
    cur = await conn.execute(
        f"SELECT {COLS} FROM inbound_messages WHERE shop_id = %s AND message_id = %s", (shop_id, message_id)
    )
    return await cur.fetchone()


async def get(conn: AsyncConnection, shop_id: str, pk: UUID) -> dict | None:
    cur = await conn.execute(f"SELECT {COLS} FROM inbound_messages WHERE shop_id = %s AND id = %s", (shop_id, pk))
    return await cur.fetchone()


async def set_outcome(conn: AsyncConnection, shop_id: str, pk: UUID, outcome: str, detail: str | None) -> None:
    await conn.execute(
        "UPDATE inbound_messages SET outcome = %s, outcome_detail = %s WHERE shop_id = %s AND id = %s",
        (outcome, detail, shop_id, pk),
    )


async def outcome_counts(conn: AsyncConnection, shop_id: str) -> dict[str, int]:
    cur = await conn.execute(
        "SELECT coalesce(outcome, 'pending') AS outcome, count(*) AS n FROM inbound_messages "
        "WHERE shop_id = %s GROUP BY 1",
        (shop_id,),
    )
    return {r["outcome"]: int(r["n"]) for r in await cur.fetchall()}
