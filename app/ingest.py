"""Accepting a message (brief, requirement 1). One tenant transaction inserts the message and
its job (transactional outbox); the id is published after commit. Never touches the model."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from app.db import Database
from app.dispatch import Dispatcher, JobEnvelope
from app.repo import jobs, messages
from app.repo.shops import Shop

log = logging.getLogger("ingest")


class UnknownReference(Exception):
    pass


@dataclass(frozen=True)
class AcceptResult:
    message: dict
    created: bool
    job: dict | None


def normalise_received_at(received_at: datetime | None, shop: Shop, now: datetime) -> datetime:
    if received_at is None:
        return now
    if received_at.tzinfo is None:
        return received_at.replace(tzinfo=ZoneInfo(shop.timezone))
    return received_at


async def accept_message(
    db: Database,
    dispatcher: Dispatcher,
    *,
    shop: Shop,
    message_id: str,
    channel: str,
    received_at: datetime,
    body: str,
    in_reply_to: str | None,
) -> AcceptResult:
    async with db.tenant_tx(shop.id) as conn:
        parent_pk = None
        if in_reply_to:
            parent = await messages.get_by_message_id(conn, shop.id, in_reply_to)
            if parent is None:  # under RLS, another shop's message is simply not there
                raise UnknownReference(in_reply_to)
            parent_pk = parent["id"]
        row, created = await messages.insert(
            conn,
            shop_id=shop.id,
            message_id=message_id,
            channel=channel,
            received_at=received_at,
            body=body,
            in_reply_to=parent_pk,
        )
        job = None
        if created:
            job = await jobs.enqueue(
                conn, shop_id=shop.id, kind="resume" if parent_pk else "extract", message_pk=row["id"]
            )
    if job is not None:
        await publish_job(db, dispatcher, job)
    log.info(
        "message accepted" if created else "duplicate message",
        extra={
            "shop_id": shop.id,
            "message_id": message_id,
            "job_id": str(job["id"]) if job else None,
            "event": "ingest.accepted" if created else "ingest.duplicate",
        },
    )
    return AcceptResult(row, created, job)


async def publish_job(db: Database, dispatcher: Dispatcher, job: dict) -> bool:
    """Publish after commit. On failure the row stays 'queued' and the sweeper retries it."""
    env = JobEnvelope(job_id=str(job["id"]), shop_id=job["shop_id"], kind=job["kind"])
    try:
        await dispatcher.publish(env)
    except Exception:  # noqa: BLE001
        log.exception("publish failed; outbox will retry", extra={"job_id": env.job_id, "shop_id": env.shop_id})
        return False
    async with db.tx() as conn:
        await jobs.mark_published(conn, job["id"])
    return True
