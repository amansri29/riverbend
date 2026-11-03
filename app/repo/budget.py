"""Monthly LLM spend cap per shop (ADR-9). All amounts in micro-USD.

reserve() is one conditional UPDATE, so two workers cannot both squeeze under the cap.
A reservation row per (job, attempt) lets a crash between reserve and settle be reconciled.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from psycopg import AsyncConnection


@dataclass(frozen=True)
class BudgetStatus:
    month: date
    cap_micros: int
    spent_micros: int
    reserved_micros: int

    @property
    def exhausted(self) -> bool:
        return self.spent_micros + self.reserved_micros >= self.cap_micros

    @property
    def remaining_micros(self) -> int:
        return max(0, self.cap_micros - self.spent_micros - self.reserved_micros)


def current_month(now: datetime, timezone: str) -> date:
    local = now.astimezone(ZoneInfo(timezone))
    return local.date().replace(day=1)


async def ensure_row(conn: AsyncConnection, shop_id: str, month: date, cap_micros: int) -> None:
    await conn.execute(
        "INSERT INTO shop_budgets (shop_id, month, cap_micros) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
        (shop_id, month, cap_micros),
    )


async def reserve(
    conn: AsyncConnection, *, shop_id: str, month: date, cap_micros: int, job_id: UUID, attempt: int, micros: int
) -> bool:
    await ensure_row(conn, shop_id, month, cap_micros)
    # cap_micros comes from the shops table on every call: raising a shop's cap takes effect at once.
    cur = await conn.execute(
        """
        UPDATE shop_budgets SET reserved_micros = reserved_micros + %s, cap_micros = %s
        WHERE shop_id = %s AND month = %s AND spent_micros + reserved_micros + %s <= %s
        RETURNING cap_micros
        """,
        (micros, cap_micros, shop_id, month, micros, cap_micros),
    )
    if await cur.fetchone() is None:
        return False
    await conn.execute(
        "INSERT INTO budget_reservations (shop_id, job_id, attempt, month, micros) VALUES (%s, %s, %s, %s, %s) "
        "ON CONFLICT (shop_id, job_id, attempt) DO UPDATE SET micros = EXCLUDED.micros, status = 'reserved'",
        (shop_id, job_id, attempt, month, micros),
    )
    return True


async def _take_reservation(
    conn: AsyncConnection, shop_id: str, job_id: UUID, attempt: int, new_status: str
) -> dict | None:
    cur = await conn.execute(
        "UPDATE budget_reservations SET status = %s WHERE shop_id = %s AND job_id = %s AND attempt = %s "
        "AND status = 'reserved' RETURNING month, micros",
        (new_status, shop_id, job_id, attempt),
    )
    return await cur.fetchone()


async def settle(conn: AsyncConnection, *, shop_id: str, job_id: UUID, attempt: int, actual_micros: int) -> None:
    r = await _take_reservation(conn, shop_id, job_id, attempt, "settled")
    if r is None:
        return
    await conn.execute(
        "UPDATE shop_budgets SET reserved_micros = greatest(0, reserved_micros - %s), spent_micros = spent_micros + %s "
        "WHERE shop_id = %s AND month = %s",
        (int(r["micros"]), actual_micros, shop_id, r["month"]),
    )


async def release(conn: AsyncConnection, *, shop_id: str, job_id: UUID, attempt: int) -> None:
    r = await _take_reservation(conn, shop_id, job_id, attempt, "released")
    if r is None:
        return
    await conn.execute(
        "UPDATE shop_budgets SET reserved_micros = greatest(0, reserved_micros - %s) WHERE shop_id = %s AND month = %s",
        (int(r["micros"]), shop_id, r["month"]),
    )


async def status(conn: AsyncConnection, shop_id: str, month: date, cap_micros: int) -> BudgetStatus:
    """cap_micros is the shop's current cap (shops table); the row only tracks spend."""
    cur = await conn.execute(
        "SELECT spent_micros, reserved_micros FROM shop_budgets WHERE shop_id = %s AND month = %s",
        (shop_id, month),
    )
    r = await cur.fetchone()
    if r is None:
        return BudgetStatus(month, cap_micros, 0, 0)
    return BudgetStatus(month, cap_micros, int(r["spent_micros"]), int(r["reserved_micros"]))
