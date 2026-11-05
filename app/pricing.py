"""Price estimate computed in code from the catalog. The model never sees a price and never
does arithmetic (ADR-6). Pure, deterministic, unit-tested."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass

from app.catalog import Catalog

MAX_QUANTITY = 4


class PricingError(ValueError):
    """A pick the catalog cannot price: unknown code or quantity out of bounds."""

    pass


@dataclass(frozen=True)
class LineItem:
    """One priced catalog line: code, name, unit price, quantity, line total, inspection flag."""

    code: str
    name: str
    quantity: int
    unit_price_cents: int
    line_total_cents: int
    requires_inspection: bool

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Estimate:
    """The priced result of a set of picks; totals are integer cents computed here, never by the model."""

    line_items: tuple[LineItem, ...]
    total_cents: int
    requires_inspection: bool
    catalog_version: str

    @property
    def total_usd(self) -> str:
        return f"{self.total_cents / 100:.2f}"


def estimate(catalog: Catalog, picks: Iterable[tuple[str, int]]) -> Estimate:
    """picks: (service code, quantity). Duplicate codes are merged by summing quantities."""
    merged: dict[str, int] = {}
    for code, qty in picks:
        merged[code] = merged.get(code, 0) + int(qty)

    items: list[LineItem] = []
    for code, qty in merged.items():
        svc = catalog.get(code)
        if svc is None:
            raise PricingError(f"unknown service code {code!r}")
        if qty < 1 or qty > MAX_QUANTITY:
            raise PricingError(f"quantity {qty} for {code} outside 1..{MAX_QUANTITY}")
        items.append(
            LineItem(
                code=svc.code,
                name=svc.name,
                quantity=qty,
                unit_price_cents=svc.price_cents,
                line_total_cents=svc.price_cents * qty,
                requires_inspection=svc.requires_inspection,
            )
        )
    return Estimate(
        line_items=tuple(items),
        total_cents=sum(i.line_total_cents for i in items),
        requires_inspection=any(i.requires_inspection for i in items),
        catalog_version=catalog.version,
    )
