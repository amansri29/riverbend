"""Tenants and API-key resolution."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from psycopg import AsyncConnection


@dataclass(frozen=True)
class Shop:
    """A tenant: id, name, time zone, monthly cap."""

    id: str
    name: str
    timezone: str
    monthly_cap_micros: int


def hash_key(key: str) -> str:
    """SHA-256 of an API key; only the hash is stored."""
    return hashlib.sha256(key.encode()).hexdigest()


def _row(r) -> Shop:
    return Shop(r["id"], r["name"], r["timezone"], int(r["monthly_cap_micros"]))


async def get_by_api_key(conn: AsyncConnection, api_key: str) -> Shop | None:
    """Resolve a shop from a raw API key, or None."""
    cur = await conn.execute(
        "SELECT id, name, timezone, monthly_cap_micros FROM shops WHERE api_key_hash = %s",
        (hash_key(api_key),),
    )
    r = await cur.fetchone()
    return _row(r) if r else None


async def get(conn: AsyncConnection, shop_id: str) -> Shop | None:
    """Fetch a shop by id."""
    cur = await conn.execute("SELECT id, name, timezone, monthly_cap_micros FROM shops WHERE id = %s", (shop_id,))
    r = await cur.fetchone()
    return _row(r) if r else None


async def list_ids(conn: AsyncConnection) -> list[str]:
    """All shop ids (used by the sweeper)."""
    cur = await conn.execute("SELECT id FROM shops ORDER BY id")
    return [r["id"] for r in await cur.fetchall()]
