"""Questions queued for the customer; a row, not a delivery."""

from __future__ import annotations

from uuid import UUID

from psycopg import AsyncConnection


async def create(conn: AsyncConnection, *, shop_id: str, work_order_id: UUID, channel: str, body: str) -> None:
    """Record a question to send to the customer (delivery itself is not built)."""
    await conn.execute(
        "INSERT INTO outbound_messages (shop_id, work_order_id, channel, body) VALUES (%s, %s, %s, %s)",
        (shop_id, work_order_id, channel, body),
    )
