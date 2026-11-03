"""Connection pool and the tenant transaction (ADR-3).

`tenant_tx(shop_id)` opens a transaction and sets `app.shop_id` as a transaction-local
setting. Every row-level security policy keys on it. Code that touches tenant tables must
run inside it; code that does not (shops lookup, job claims) uses `tx()`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool


class Database:
    def __init__(self, url: str, *, min_size: int = 1, max_size: int = 10) -> None:
        self.pool = AsyncConnectionPool(
            url, open=False, min_size=min_size, max_size=max_size, kwargs={"row_factory": dict_row}
        )

    async def open(self) -> None:
        await self.pool.open()
        await self.pool.wait()

    async def close(self) -> None:
        await self.pool.close()

    @asynccontextmanager
    async def tx(self) -> AsyncIterator[AsyncConnection]:
        async with self.pool.connection() as conn, conn.transaction():
            yield conn

    @asynccontextmanager
    async def tenant_tx(self, shop_id: str) -> AsyncIterator[AsyncConnection]:
        async with self.pool.connection() as conn, conn.transaction():
            await set_tenant(conn, shop_id)
            yield conn


async def set_tenant(conn: AsyncConnection, shop_id: str) -> None:
    # set_config(..., true) is transaction-local: it cannot leak to the next pooled user.
    await conn.execute("SELECT set_config('app.shop_id', %s, true)", (shop_id,))
