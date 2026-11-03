"""ADR-3: the database refuses cross-tenant rows even when application code is wrong."""

import psycopg
import pytest

from app.repo import messages, work_orders
from tests.conftest import make_extraction
from tests.helpers import RECEIVED, ingest, owner_conn

pytestmark = pytest.mark.db


async def test_rls_isolates_reads_and_writes(db):
    async with db.tenant_tx("rb-downtown") as conn:
        await messages.insert(
            conn,
            shop_id="rb-downtown",
            message_id="m-1",
            channel="web",
            received_at=RECEIVED,
            body="downtown",
            in_reply_to=None,
        )
    async with db.tenant_tx("rb-lakeshore") as conn:
        assert await messages.get_by_message_id(conn, "rb-downtown", "m-1") is None  # invisible
        cur = await conn.execute("SELECT count(*) AS n FROM inbound_messages")  # even without a WHERE
        assert (await cur.fetchone())["n"] == 0
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        async with db.tenant_tx("rb-lakeshore") as conn:
            await messages.insert(
                conn,
                shop_id="rb-downtown",
                message_id="m-2",
                channel="web",
                received_at=RECEIVED,
                body="smuggled",
                in_reply_to=None,
            )


async def test_no_tenant_setting_fails_closed(db):
    await ingest(db, "rb-downtown", "m-1", "hello")
    async with db.tx() as conn:  # a code path that forgot set_tenant
        cur = await conn.execute("SELECT count(*) AS n FROM inbound_messages")
        assert (await cur.fetchone())["n"] == 0
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        async with db.tx() as conn:
            await conn.execute(
                "INSERT INTO inbound_messages (shop_id, message_id, channel, received_at, body) "
                "VALUES ('rb-downtown', 'm-9', 'web', now(), 'x')"
            )


async def test_composite_fk_makes_cross_shop_reference_unrepresentable(db):
    r = await ingest(db, "rb-downtown", "m-1", "hello")
    with owner_conn() as conn, pytest.raises(psycopg.errors.ForeignKeyViolation):  # owner bypasses RLS on purpose
        conn.execute(
            "INSERT INTO work_orders (shop_id, source_message_id, status, catalog_version) "
            "VALUES ('rb-lakeshore', %s, 'open', 'v')",
            (r.message["id"],),
        )


async def test_worker_prompt_can_only_contain_its_own_shop(db, pipeline, provider):
    await ingest(db, "rb-lakeshore", "m-L", "LAKESHORE SECRET: chain fell off, Saturday")
    r = await ingest(db, "rb-downtown", "m-D", "downtown brakes squeal, Saturday")
    provider.scripted["rb-downtown/m-D"] = make_extraction()
    await pipeline.run_job(r.job["id"])
    assert len(provider.calls) == 1
    text = " ".join(t.content for t in provider.calls[0]["turns"])
    assert "downtown brakes squeal" in text and "LAKESHORE SECRET" not in text


async def test_order_write_scoped_to_tenant(db):
    r = await ingest(db, "rb-downtown", "m-1", "hello")
    async with db.tenant_tx("rb-downtown") as conn:
        row, created = await work_orders.create(
            conn, shop_id="rb-downtown", source_message_id=r.message["id"], status="open", catalog_version="v"
        )
        assert created
    async with db.tenant_tx("rb-northside") as conn:
        assert await work_orders.list_by_status(conn, "rb-downtown", None) == []
        assert await work_orders.get(conn, "rb-downtown", row["id"]) is None
