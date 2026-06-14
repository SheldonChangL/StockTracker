"""Tests for the watchlist repository layer (Story 6.1, FR-22)."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import datetime

import pytest

from tsic.storage import migrations
from tsic.storage.repository import WatchlistRepository


@pytest.fixture
def repo() -> Iterator[WatchlistRepository]:
    conn = sqlite3.connect(":memory:")
    migrations.migrate(conn)
    try:
        yield WatchlistRepository(conn)
    finally:
        conn.close()


# AC-1: add then list returns the symbol with an ISO added_at timestamp.
def test_add_then_list_contains_symbol_with_iso_added_at(
    repo: WatchlistRepository,
) -> None:
    repo.add("2330")

    entries = repo.list()
    assert [e.symbol for e in entries] == ["2330"]
    # added_at must be a parseable ISO-8601 timestamp.
    parsed = datetime.fromisoformat(entries[0].added_at)
    assert parsed.tzinfo is not None


def test_list_is_empty_before_any_add(repo: WatchlistRepository) -> None:
    assert repo.list() == []


# AC-2: re-adding the same symbol does not create a duplicate row.
def test_duplicate_add_keeps_single_entry(repo: WatchlistRepository) -> None:
    repo.add("2330")
    repo.add("2330")

    entries = repo.list()
    assert len(entries) == 1
    assert entries[0].symbol == "2330"


def test_duplicate_add_preserves_original_added_at(
    repo: WatchlistRepository,
) -> None:
    repo.add("2330")
    first = repo.list()[0].added_at

    repo.add("2330")
    assert repo.list()[0].added_at == first


# AC-3: removing a tracked symbol drops it from the list.
def test_remove_drops_symbol(repo: WatchlistRepository) -> None:
    repo.add("2330")
    repo.remove("2330")

    assert repo.list() == []


def test_remove_only_targets_named_symbol(repo: WatchlistRepository) -> None:
    repo.add("2330")
    repo.add("2317")

    repo.remove("2330")

    assert [e.symbol for e in repo.list()] == ["2317"]


# AC-4: removing a symbol that is not tracked is a harmless no-op.
def test_remove_missing_symbol_is_a_noop(repo: WatchlistRepository) -> None:
    repo.add("2330")

    repo.remove("9999")  # not present -> no error, no effect

    assert [e.symbol for e in repo.list()] == ["2330"]


def test_remove_from_empty_watchlist_is_a_noop(repo: WatchlistRepository) -> None:
    repo.remove("2330")  # must not raise
    assert repo.list() == []
