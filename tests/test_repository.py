"""Tests for the daily_prices repository layer (Story 2.4)."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

import pytest

from tsic.models import DailyPrice
from tsic.storage import migrations
from tsic.storage.repository import DataPollutionError, PriceRepository


@pytest.fixture
def repo() -> Iterator[PriceRepository]:
    conn = sqlite3.connect(":memory:")
    migrations.migrate(conn)
    try:
        yield PriceRepository(conn)
    finally:
        conn.close()


def _price(
    symbol: str = "2330",
    date: str = "2026-06-10",
    close: float = 100.0,
    adjusted: int = 0,
) -> DailyPrice:
    return DailyPrice(
        symbol=symbol,
        date=date,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=1000,
        source="test",
        adjusted=adjusted,
    )


# AC-1: duplicate (symbol, date) writes keep the first value and add no row.
def test_duplicate_key_is_ignored_first_write_wins(repo: PriceRepository) -> None:
    assert repo.upsert_prices([_price(close=100.0)]) == 1
    # Second write of the same key with a different value is silently skipped.
    assert repo.upsert_prices([_price(close=999.0)]) == 0

    rows = repo.query_prices("2330", "2026-06-10", "2026-06-10")
    assert len(rows) == 1
    assert rows[0].close == 100.0


def test_upsert_returns_inserted_count_and_skips_existing(
    repo: PriceRepository,
) -> None:
    inserted = repo.upsert_prices(
        [_price(date="2026-06-10"), _price(date="2026-06-11")]
    )
    assert inserted == 2

    # One existing key + one new key -> only the new row counts.
    inserted = repo.upsert_prices(
        [_price(date="2026-06-11"), _price(date="2026-06-12")]
    )
    assert inserted == 1


def test_empty_batch_is_a_noop(repo: PriceRepository) -> None:
    assert repo.upsert_prices([]) == 0


# AC-2: latest_date returns MAX(date), or None when the symbol has no rows.
def test_latest_date_returns_max(repo: PriceRepository) -> None:
    repo.upsert_prices(
        [
            _price(date="2026-06-08"),
            _price(date="2026-06-10"),
            _price(date="2026-06-09"),
        ]
    )
    assert repo.latest_date("2330") == "2026-06-10"


def test_latest_date_none_when_no_rows(repo: PriceRepository) -> None:
    assert repo.latest_date("2330") is None
    # Another symbol's rows must not leak into the lookup.
    repo.upsert_prices([_price(symbol="2454")])
    assert repo.latest_date("2330") is None


# AC-3: a symbol must not mix adjusted (1) and raw (0) prices.
def test_mixing_adjusted_with_existing_raw_is_rejected(
    repo: PriceRepository,
) -> None:
    repo.upsert_prices([_price(date="2026-06-10", adjusted=0)])

    with pytest.raises(DataPollutionError):
        repo.upsert_prices([_price(date="2026-06-11", adjusted=1)])


def test_mixing_adjusted_within_batch_is_rejected(repo: PriceRepository) -> None:
    with pytest.raises(DataPollutionError):
        repo.upsert_prices(
            [
                _price(date="2026-06-10", adjusted=0),
                _price(date="2026-06-11", adjusted=1),
            ]
        )


def test_rejected_write_persists_nothing(repo: PriceRepository) -> None:
    with pytest.raises(DataPollutionError):
        repo.upsert_prices(
            [
                _price(date="2026-06-10", adjusted=0),
                _price(date="2026-06-11", adjusted=1),
            ]
        )
    assert repo.latest_date("2330") is None


def test_same_basis_is_allowed_across_writes(repo: PriceRepository) -> None:
    assert repo.upsert_prices([_price(date="2026-06-10", adjusted=1)]) == 1
    assert repo.upsert_prices([_price(date="2026-06-11", adjusted=1)]) == 1


def test_invariant_is_per_symbol(repo: PriceRepository) -> None:
    # Different symbols may independently use different bases.
    repo.upsert_prices([_price(symbol="2330", adjusted=0)])
    assert repo.upsert_prices([_price(symbol="2454", adjusted=1)]) == 1


# AC-4: range query is inclusive and ordered ascending by date.
def test_query_prices_ordered_and_inclusive(repo: PriceRepository) -> None:
    repo.upsert_prices(
        [
            _price(date="2026-06-12"),
            _price(date="2026-06-10"),
            _price(date="2026-06-11"),
            _price(date="2026-06-13"),
        ]
    )

    rows = repo.query_prices("2330", "2026-06-10", "2026-06-12")
    assert [r.date for r in rows] == ["2026-06-10", "2026-06-11", "2026-06-12"]


def test_query_prices_excludes_other_symbols(repo: PriceRepository) -> None:
    repo.upsert_prices([_price(symbol="2330", date="2026-06-10")])
    repo.upsert_prices([_price(symbol="2454", date="2026-06-10")])

    rows = repo.query_prices("2330", "2026-06-01", "2026-06-30")
    assert len(rows) == 1
    assert rows[0].symbol == "2330"


def test_query_prices_empty_when_no_match(repo: PriceRepository) -> None:
    repo.upsert_prices([_price(date="2026-06-10")])
    assert repo.query_prices("2330", "2026-07-01", "2026-07-31") == []


def test_query_prices_round_trips_all_columns(repo: PriceRepository) -> None:
    original = DailyPrice(
        symbol="2330",
        date="2026-06-10",
        open=1.5,
        high=2.5,
        low=1.0,
        close=2.0,
        volume=4242,
        source="twse",
        adjusted=1,
    )
    repo.upsert_prices([original])

    (restored,) = repo.query_prices("2330", "2026-06-10", "2026-06-10")
    assert restored == original
