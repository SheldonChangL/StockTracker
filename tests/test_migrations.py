"""Tests for versioned schema migrations (Story 2.2)."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

import pytest

from tsic.storage import migrations


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(":memory:")
    try:
        yield connection
    finally:
        connection.close()


def _tables(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    return {row[0] for row in rows}


def _meta(connection: sqlite3.Connection, key: str) -> str | None:
    row = connection.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def test_fresh_db_creates_all_tables(conn: sqlite3.Connection) -> None:
    """AC-1: a fresh migration creates all five tables."""
    migrations.migrate(conn)
    assert {
        "daily_prices",
        "chip_flows",
        "fundamentals",
        "watchlist",
        "meta",
    } <= _tables(conn)


def test_daily_prices_primary_key(conn: sqlite3.Connection) -> None:
    """AC-1: daily_prices PK is the composite (symbol, date)."""
    migrations.migrate(conn)
    cols = conn.execute("PRAGMA table_info(daily_prices)").fetchall()
    pk = {row[1]: row[5] for row in cols if row[5]}  # name -> pk position
    assert pk == {"symbol": 1, "date": 2}


def test_daily_prices_index_is_symbol_date_desc(conn: sqlite3.Connection) -> None:
    """AC-1: the daily_prices index covers (symbol, date DESC)."""
    migrations.migrate(conn)
    sql = conn.execute(
        "SELECT sql FROM sqlite_master "
        "WHERE type = 'index' AND name = 'idx_daily_prices_symbol_date'"
    ).fetchone()
    assert sql is not None
    normalized = " ".join(sql[0].split()).lower()
    assert "(symbol, date desc)" in normalized


def test_daily_prices_adjusted_column(conn: sqlite3.Connection) -> None:
    """AC-4: daily_prices has adjusted INTEGER NOT NULL DEFAULT 0."""
    migrations.migrate(conn)
    cols = {row[1]: row for row in conn.execute("PRAGMA table_info(daily_prices)")}
    adjusted = cols["adjusted"]
    assert adjusted[2] == "INTEGER"  # type
    assert adjusted[3] == 1  # notnull
    assert adjusted[4] == "0"  # default


def test_meta_seed_values(conn: sqlite3.Connection) -> None:
    """AC-2: meta holds schema_version='1' and adjust_policy='raw'."""
    migrations.migrate(conn)
    assert _meta(conn, "schema_version") == str(migrations.SCHEMA_VERSION)
    assert _meta(conn, "adjust_policy") == "raw"


def test_watchlist_has_added_at_column(conn: sqlite3.Connection) -> None:
    """Story 6.1: watchlist gains added_at (TEXT NOT NULL) in schema v2."""
    migrations.migrate(conn)
    cols = {row[1]: row for row in conn.execute("PRAGMA table_info(watchlist)")}
    assert "added_at" in cols
    assert cols["added_at"][2] == "TEXT"  # type
    assert cols["added_at"][3] == 1  # notnull


def test_v1_database_upgrades_watchlist_to_v2(conn: sqlite3.Connection) -> None:
    """An existing v1 watchlist gains added_at when migrated forward to v2."""
    # Simulate a database left at schema v1 (watchlist without added_at).
    conn.execute("CREATE TABLE watchlist (symbol TEXT PRIMARY KEY NOT NULL)")
    conn.execute(
        "CREATE TABLE meta (key TEXT PRIMARY KEY NOT NULL, value TEXT NOT NULL)"
    )
    conn.execute("INSERT INTO meta (key, value) VALUES ('schema_version', '1')")
    conn.commit()

    assert migrations.migrate(conn) == migrations.SCHEMA_VERSION
    cols = {row[1] for row in conn.execute("PRAGMA table_info(watchlist)")}
    assert "added_at" in cols


def test_migrate_returns_schema_version(conn: sqlite3.Connection) -> None:
    """migrate reports the resulting schema version."""
    assert migrations.migrate(conn) == migrations.SCHEMA_VERSION


def test_migration_is_idempotent(conn: sqlite3.Connection) -> None:
    """AC-3: re-running migration is a no-op (no error, version unchanged)."""
    migrations.migrate(conn)
    conn.execute(
        "INSERT INTO daily_prices "
        "(symbol, date, open, high, low, close, volume, source) "
        "VALUES ('2330', '2026-06-12', 1, 2, 0.5, 1.5, 100, 'test')"
    )
    conn.commit()
    tables_before = _tables(conn)

    assert migrations.migrate(conn) == migrations.SCHEMA_VERSION

    # Tables not rebuilt: the previously inserted row survives.
    assert _tables(conn) == tables_before
    assert _meta(conn, "schema_version") == str(migrations.SCHEMA_VERSION)
    rows = conn.execute("SELECT COUNT(*) FROM daily_prices").fetchone()[0]
    assert rows == 1


def test_adjust_policy_not_overwritten_on_rerun(conn: sqlite3.Connection) -> None:
    """A re-run must not clobber an operator-changed policy flag."""
    migrations.migrate(conn)
    conn.execute("UPDATE meta SET value = 'adjusted' WHERE key = 'adjust_policy'")
    conn.commit()

    migrations.migrate(conn)

    assert _meta(conn, "adjust_policy") == "adjusted"
