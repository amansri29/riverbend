"""Shared fixtures for tests that need Postgres. Skips cleanly when no database is reachable."""

from __future__ import annotations

import os
from datetime import datetime
from zoneinfo import ZoneInfo

import psycopg
import pytest

from app.catalog import load_catalog
from app.config import Settings
from app.db import Database
from app.dispatch import CollectingDispatcher
from app.extraction.fake import FakeProvider
from app.ingest import accept_message
from app.repo import shops
from app.worker.breaker import CircuitBreaker
from app.worker.pipeline import Pipeline, build_pipeline
from scripts.migrate import apply_migrations, ensure_app_role, seed_shops

OWNER_URL = os.environ.get("TEST_MIGRATION_DATABASE_URL", "postgresql://localhost:5432/riverbend_test")
APP_URL = os.environ.get("TEST_DATABASE_URL", "postgresql://riverbend_app:riverbend_app@localhost:5432/riverbend_test")
RECEIVED = datetime(2026, 9, 22, 8, 2, tzinfo=ZoneInfo("America/New_York"))
TENANT_TABLES = "inbound_messages, work_orders, jobs, llm_calls, shop_budgets, budget_reservations, outbound_messages"
KEYS = {
    "rb-downtown": "dev-key-rb-downtown",
    "rb-northside": "dev-key-rb-northside",
    "rb-lakeshore": "dev-key-rb-lakeshore",
}


def test_settings(**overrides) -> Settings:
    base = dict(
        database_url=APP_URL,
        migration_database_url=OWNER_URL,
        dispatcher="inline",
        llm_provider="fake",
        llm_record_dir="",
        sweep_interval_seconds=0,
        outbox_republish_after_seconds=0,
        breaker_failure_threshold=3,
        breaker_open_seconds=60,
        llm_max_output_tokens=500,
    )
    base.update(overrides)
    return Settings(_env_file=None, **base)


def owner_conn() -> psycopg.Connection:
    """Owner connection: bypasses RLS. Only for setup/assertions in tests."""
    return psycopg.connect(OWNER_URL, autocommit=True)


@pytest.fixture(scope="session")
def migrated():
    try:
        conn = owner_conn()
    except psycopg.OperationalError as e:  # pragma: no cover
        pytest.skip(f"no test database: {e}")
    with conn:
        ensure_app_role(conn, "riverbend_app")
        apply_migrations(conn)
        seed_shops(conn, dev_keys=True, cap_usd=25, catalog_path="catalog/catalog.json")
    return True


@pytest.fixture
async def db(migrated):
    with owner_conn() as conn:
        conn.execute(f"TRUNCATE {TENANT_TABLES} CASCADE")
        conn.execute("UPDATE shops SET monthly_cap_micros = 25000000")
    d = Database(APP_URL, max_size=8)
    await d.open()
    try:
        yield d
    finally:
        await d.close()


@pytest.fixture
def settings() -> Settings:
    return test_settings()


@pytest.fixture
def provider() -> FakeProvider:
    return FakeProvider()


@pytest.fixture
def pipeline(db, settings, provider) -> Pipeline:
    return make_pipeline(db, settings, provider)


def make_pipeline(
    db: Database, settings: Settings, provider: FakeProvider, breaker: CircuitBreaker | None = None
) -> Pipeline:
    return build_pipeline(settings, db, load_catalog(settings.catalog_path), provider=provider, breaker=breaker)


async def shop(db: Database, shop_id: str):
    async with db.tx() as conn:
        s = await shops.get(conn, shop_id)
    assert s is not None
    return s


async def ingest(
    db: Database,
    shop_id: str,
    message_id: str,
    body: str,
    *,
    channel="web",
    received_at=RECEIVED,
    in_reply_to=None,
    dispatcher=None,
):
    s = await shop(db, shop_id)
    return await accept_message(
        db,
        dispatcher or CollectingDispatcher(),
        shop=s,
        message_id=message_id,
        channel=channel,
        received_at=received_at,
        body=body,
        in_reply_to=in_reply_to,
    )


def set_cap(shop_id: str, usd: float) -> None:
    with owner_conn() as conn:
        conn.execute("UPDATE shops SET monthly_cap_micros = %s WHERE id = %s", (int(usd * 1_000_000), shop_id))
