"""The shared service catalog. Loaded once from JSON; its content hash is pinned on every
work order so a later price change never rewrites history."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class Service:
    code: str
    name: str
    price_cents: int
    minutes: int
    requires_inspection: bool


@dataclass(frozen=True)
class ShopInfo:
    id: str
    name: str


@dataclass(frozen=True)
class Catalog:
    version: str
    currency: str
    services: dict[str, Service]
    shops: tuple[ShopInfo, ...]

    def get(self, code: str) -> Service | None:
        return self.services.get(code)

    @property
    def codes(self) -> list[str]:
        return list(self.services)


def load_catalog(path: str | Path) -> Catalog:
    raw = Path(path).read_bytes()
    data = json.loads(raw)
    services = {
        s["code"]: Service(
            code=s["code"],
            name=s["name"],
            price_cents=round(float(s["price"]) * 100),
            minutes=int(s["minutes"]),
            requires_inspection=bool(s["requires_inspection"]),
        )
        for s in data["services"]
    }
    shops = tuple(ShopInfo(id=s["id"], name=s["name"]) for s in data["shops"])
    return Catalog(
        version=hashlib.sha256(raw).hexdigest()[:12],
        currency=data.get("currency", "USD"),
        services=services,
        shops=shops,
    )


@lru_cache
def default_catalog(path: str = "catalog/catalog.json") -> Catalog:
    return load_catalog(path)
