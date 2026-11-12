"""Periodic housekeeping: republish outbox rows that never reached the broker, release parked
jobs whose time has come, and expire unanswered follow-ups. Locally runs on a timer inside the
worker; on GCP, Cloud Scheduler calls POST /sweep so the worker can scale to zero."""

from __future__ import annotations

import logging

from app.config import Settings
from app.db import Database
from app.dispatch import Dispatcher
from app.ingest import publish_job
from app.repo import jobs, shops, work_orders

log = logging.getLogger("sweeper")


async def sweep_once(db: Database, dispatcher: Dispatcher, settings: Settings) -> dict[str, int]:
    """One sweep: republish unpublished outbox rows, release due parked jobs, expire stale questions."""
    async with db.tx() as conn:
        due = await jobs.due_for_publish(conn, unpublished_after_seconds=settings.outbox_republish_after_seconds)
    republished = 0
    for job in due:
        if await publish_job(db, dispatcher, job):
            republished += 1
    async with db.tx() as conn:
        shop_ids = await shops.list_ids(conn)
    expired = 0
    for shop_id in shop_ids:
        async with db.tenant_tx(shop_id) as conn:
            expired += await work_orders.expire_stale(conn, shop_id, older_than_days=settings.followup_expiry_days)
    if republished or expired:
        log.info(
            f"sweep: republished {republished}, expired {expired}",
            extra={"event": "sweep", "republished": republished, "expired": expired},
        )
    return {"republished": republished, "expired": expired, "due": len(due)}
