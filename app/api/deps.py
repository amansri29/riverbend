"""Tenant resolution (ADR-3, layer 1). The API key is the only source of tenant identity."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Path, Request

from app.db import Database
from app.repo import shops
from app.repo.shops import Shop


@dataclass(frozen=True)
class Tenant:
    """The resolved shop for a request, available to handlers as a dependency."""

    shop: Shop


def get_db(request: Request) -> Database:
    """Fetch the database pool from app state."""
    return request.app.state.db


async def tenant(
    request: Request,
    shop_id: str = Path(),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    db: Database = Depends(get_db),
) -> Tenant:
    """Resolve the shop from X-API-Key and require it to match the path: 401 if missing, 404 otherwise."""
    if not x_api_key:
        raise HTTPException(status_code=401, detail="missing X-API-Key")
    async with db.tx() as conn:
        shop = await shops.get_by_api_key(conn, x_api_key)
    # Wrong key, or a valid key for another shop: both are 404 so shops cannot be enumerated.
    if shop is None or shop.id != shop_id:
        raise HTTPException(status_code=404, detail="shop not found")
    return Tenant(shop=shop)
