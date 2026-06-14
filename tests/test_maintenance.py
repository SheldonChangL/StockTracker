"""Tests for per-symbol data maintenance helpers (Story 2.5)."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

import pytest

from tsic.storage import maintenance, migrations


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(":memory:")
    migrations.migrate(connection)
    try:
        yield connection
    finally:
        connection.close()


def _seed_price(conn: sqlite3.Connection, symbol: str, date: str) -> None:
    conn.execute(
        "INSERT INTO daily_prices "
        "(symbol, date, open, high, low, close, volume, source, adjusted) "
        "VALUES (?, ?, 1, 1, 1, 1, 1, 'test', 0)",
        (symbol, date),
    )


def _seed_chip(conn: sqlite3.Connection, symbol: str, date: str) -> None:
    conn.execute(
        "INSERT INTO chip_flows "
        "(symbol, date, foreign_net, trust_net, dealer_net, source) "
        "VALUES (?, ?, 0, 0, 0, 'test')",
        (symbol, date),
    )


def _seed_fundamental(conn: sqlite3.Connection, symbol: str, date: str) -> None:
    conn.execute(
        "INSERT INTO fundamentals "
        "(symbol, date, eps, pe, pb, dividend_yield, source) "
        "VALUES (?, ?, 0, 0, 0, 0, 'test')",
        (symbol, date),
    )


def test_count_sums_across_all_data_tables(conn: sqlite3.Connection) -> None:
    _seed_price(conn, "2330", "2026-06-10")
    _seed_price(conn, "2330", "2026-06-11")
    _seed_chip(conn, "2330", "2026-06-10")
    _seed_fundamental(conn, "2330", "2026-06-10")
    conn.commit()

    assert maintenance.count_symbol_records(conn, "2330") == 4


def test_count_zero_when_symbol_absent(conn: sqlite3.Connection) -> None:
    assert maintenance.count_symbol_records(conn, "2330") == 0


def test_delete_removes_all_rows_and_returns_count(conn: sqlite3.Connection) -> None:
    _seed_price(conn, "2330", "2026-06-10")
    _seed_chip(conn, "2330", "2026-06-10")
    _seed_fundamental(conn, "2330", "2026-06-10")
    conn.commit()

    assert maintenance.delete_symbol(conn, "2330") == 3
    assert maintenance.count_symbol_records(conn, "2330") == 0


def test_delete_only_targets_given_symbol(conn: sqlite3.Connection) -> None:
    _seed_price(conn, "2330", "2026-06-10")
    _seed_price(conn, "2454", "2026-06-10")
    conn.commit()

    assert maintenance.delete_symbol(conn, "2330") == 1
    assert maintenance.count_symbol_records(conn, "2454") == 1


def test_delete_absent_symbol_is_noop(conn: sqlite3.Connection) -> None:
    assert maintenance.delete_symbol(conn, "2330") == 0
