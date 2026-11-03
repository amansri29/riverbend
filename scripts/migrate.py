"""Apply SQL migrations and seed the shops. Runs as the owner role (MIGRATION_DATABASE_URL).

Usage: python scripts/migrate.py [--no-seed]
Idempotent: re-running applies only new migrations and upserts the shops.
"""

from __future__ import annotations

import hashlib
import secrets
import sys
from pathlib import Path

import psycopg
from psycopg import sql

from app.catalog import load_catalog
from app.config import get_settings

MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"


def ensure_app_role(conn: psycopg.Connection, password: str) -> None:
    exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = 'riverbend_app'").fetchone()
    if not exists:
        conn.execute(sql.SQL("CREATE ROLE riverbend_app LOGIN PASSWORD {}").format(sql.Literal(password)))
    else:
        conn.execute(sql.SQL("ALTER ROLE riverbend_app PASSWORD {}").format(sql.Literal(password)))


def apply_migrations(conn: psycopg.Connection) -> list[str]:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
    )
    applied = {r[0] for r in conn.execute("SELECT version FROM schema_migrations").fetchall()}
    done = []
    for path in sorted(MIGRATIONS.glob("*.sql")):
        version = path.stem
        if version in applied:
            continue
        with conn.transaction():
            conn.execute(path.read_text())
            conn.execute("INSERT INTO schema_migrations(version) VALUES (%s)", (version,))
        done.append(version)
    return done


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def seed_shops(conn: psycopg.Connection, *, dev_keys: bool, cap_usd: float, catalog_path: str) -> dict[str, str]:
    catalog = load_catalog(catalog_path)
    keys: dict[str, str] = {}
    for shop in catalog.shops:
        row = conn.execute("SELECT 1 FROM shops WHERE id = %s", (shop.id,)).fetchone()
        if row and not dev_keys:
            continue  # keep the existing production key
        key = f"dev-key-{shop.id}" if dev_keys else f"rb_{secrets.token_urlsafe(24)}"
        keys[shop.id] = key
        conn.execute(
            """
            INSERT INTO shops (id, name, api_key_hash, monthly_cap_micros)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, api_key_hash = EXCLUDED.api_key_hash
            """,
            (shop.id, shop.name, hash_key(key), int(cap_usd * 1_000_000)),
        )
    return keys


def main(argv: list[str]) -> int:
    s = get_settings()
    seed = "--no-seed" not in argv
    with psycopg.connect(s.migration_database_url, autocommit=True) as conn:
        ensure_app_role(conn, s.app_db_password)
        done = apply_migrations(conn)
        print(f"migrations applied: {done or 'none (up to date)'}")
        if seed:
            keys = seed_shops(
                conn, dev_keys=s.dev_api_keys, cap_usd=s.default_monthly_cap_usd, catalog_path=s.catalog_path
            )
            if keys:
                print("shop API keys (dev):" if s.dev_api_keys else "shop API keys (store these, shown once):")
                for shop_id, key in keys.items():
                    print(f"  {shop_id}: {key}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
