"""The same message twice must produce one work order, at every layer."""

import asyncio

import pytest

from app.dispatch import CollectingDispatcher, FailingDispatcher
from app.repo import jobs, work_orders
from app.worker.pipeline import JobResult
from app.worker.sweeper import sweep_once
from tests.conftest import make_extraction
from tests.helpers import ingest, owner_conn

pytestmark = pytest.mark.db


async def test_duplicate_message_id_is_idempotent(db):
    d = CollectingDispatcher()
    a = await ingest(db, "rb-lakeshore", "m-1003", "chain falls off. Saturday. Marcus", dispatcher=d)
    b = await ingest(db, "rb-lakeshore", "m-1003", "chain falls off. Saturday. Marcus", dispatcher=d)
    assert a.created and not b.created and b.job is None
    assert a.message["id"] == b.message["id"]
    assert len(d.published) == 1
    with owner_conn() as conn:
        assert conn.execute("SELECT count(*) FROM jobs").fetchone()[0] == 1


async def test_concurrent_duplicates_resolve_to_one(db):
    d = CollectingDispatcher()
    results = await asyncio.gather(
        *[ingest(db, "rb-downtown", "m-x", "Front flat. Today.", dispatcher=d) for _ in range(6)]
    )
    assert sum(r.created for r in results) == 1
    assert len(d.published) == 1


async def test_same_message_id_in_another_shop_is_a_different_message(db):
    a = await ingest(db, "rb-downtown", "m-1", "x")
    b = await ingest(db, "rb-northside", "m-1", "x")
    assert a.created and b.created and a.message["id"] != b.message["id"]


async def test_job_delivered_twice_creates_one_order(db, pipeline, provider):
    r = await ingest(db, "rb-downtown", "m-1", "brakes squeal, Saturday")
    provider.scripted["rb-downtown/m-1"] = make_extraction()
    assert await pipeline.run_job(r.job["id"]) is JobResult.DONE
    # Simulate the broker redelivering after an ack was lost.
    with owner_conn() as conn:
        conn.execute("UPDATE jobs SET status = 'published'")
    assert await pipeline.run_job(r.job["id"]) is JobResult.SKIPPED
    assert len(provider.calls) == 1  # no second model call, no second spend
    async with db.tenant_tx("rb-downtown") as conn:
        assert len(await work_orders.list_by_status(conn, "rb-downtown", None)) == 1


async def test_crashed_lease_is_reclaimable_but_live_lease_is_not(db):
    r = await ingest(db, "rb-downtown", "m-1", "x")
    async with db.tx() as conn:
        assert await jobs.claim(conn, r.job["id"]) is not None
        assert await jobs.claim(conn, r.job["id"]) is None  # someone holds it
    with owner_conn() as conn:
        conn.execute("UPDATE jobs SET updated_at = now() - interval '10 minutes'")
    async with db.tx() as conn:
        assert await jobs.claim(conn, r.job["id"]) is not None  # lease expired → reclaim


async def test_outbox_survives_a_broker_outage(db, settings):
    r = await ingest(db, "rb-downtown", "m-1", "x", dispatcher=FailingDispatcher())
    async with db.tx() as conn:
        assert (await jobs.get(conn, r.job["id"]))["status"] == "queued"  # committed, not published
    d = CollectingDispatcher()
    out = await sweep_once(db, d, settings)
    assert out["republished"] == 1 and d.published[0].job_id == str(r.job["id"])
    async with db.tx() as conn:
        assert (await jobs.get(conn, r.job["id"]))["status"] == "published"
