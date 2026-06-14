"""Tests for the TUI watchlist screen (Story 8.1, FR-26/FR-27, AC-1..AC-4).

AC-3 specifies the exact harness ``async with TsicApp(repo=fake_repo).run_test()
as pilot``. The project does not depend on pytest-asyncio, so each async body is
driven through :func:`asyncio.run` while keeping that literal usage intact.
"""

from __future__ import annotations

import asyncio
from datetime import date

from textual.widgets import DataTable

from tsic.tui.app import TsicApp
from tsic.tui.watchlist_view import (
    COLUMNS,
    STATUS_FRESH,
    STATUS_MISSING,
    STATUS_STALE,
    WatchlistRow,
    classify_freshness,
)


class FakeRepo:
    """A WatchlistSource returning a fixed set of rows."""

    def __init__(self, rows: list[WatchlistRow]) -> None:
        self._rows = rows

    def watchlist_rows(self) -> list[WatchlistRow]:
        return self._rows


# --- AC-2: freshness classification (pure rule) ---------------------------


def test_within_threshold_is_fresh() -> None:
    status = classify_freshness("2026-06-12", today=date(2026, 6, 14), fresh_within_days=3)
    assert status == STATUS_FRESH


def test_on_threshold_boundary_is_fresh() -> None:
    # Exactly fresh_within_days old still counts as fresh (inclusive).
    status = classify_freshness("2026-06-11", today=date(2026, 6, 14), fresh_within_days=3)
    assert status == STATUS_FRESH


def test_beyond_threshold_is_stale() -> None:
    status = classify_freshness("2026-06-01", today=date(2026, 6, 14), fresh_within_days=3)
    assert status == STATUS_STALE


def test_no_data_is_missing() -> None:
    assert classify_freshness(None, today=date(2026, 6, 14), fresh_within_days=3) == STATUS_MISSING
    assert classify_freshness("", today=date(2026, 6, 14), fresh_within_days=3) == STATUS_MISSING


# --- AC-1 / AC-3: the table widget --------------------------------------


def test_table_has_stable_id_and_columns() -> None:
    """AC-1: a DataTable with id=watchlist-table and the six required columns."""

    async def scenario() -> None:
        repo = FakeRepo([])
        async with TsicApp(repo=repo).run_test() as pilot:
            table = pilot.app.query_one("#watchlist-table", DataTable)
            headers = [str(col.label) for col in table.ordered_columns]
            assert headers == list(COLUMNS)

    asyncio.run(scenario())


def test_row_count_matches_watchlist_size() -> None:
    """AC-3: the table renders exactly one row per watchlist entry."""

    async def scenario() -> None:
        rows = [
            WatchlistRow("2330", "台積電", 1000.0, "2026-06-13", 250, STATUS_FRESH),
            WatchlistRow("2317", "鴻海", 200.0, "2026-05-01", 200, STATUS_STALE),
            WatchlistRow("9999", None, None, None, 0, STATUS_MISSING),
        ]
        repo = FakeRepo(rows)
        async with TsicApp(repo=repo).run_test() as pilot:
            table = pilot.app.query_one("#watchlist-table", DataTable)
            assert table.row_count == len(rows)

    asyncio.run(scenario())


def test_empty_watchlist_renders_zero_rows() -> None:
    async def scenario() -> None:
        async with TsicApp(repo=FakeRepo([])).run_test() as pilot:
            table = pilot.app.query_one("#watchlist-table", DataTable)
            assert table.row_count == 0

    asyncio.run(scenario())


def test_rows_render_status_and_missing_placeholder() -> None:
    """AC-2 (rendering side): statuses and missing values reach the cells."""

    async def scenario() -> None:
        rows = [
            WatchlistRow("2330", "台積電", 1000.0, "2026-06-13", 250, STATUS_FRESH),
            WatchlistRow("9999", None, None, None, 0, STATUS_MISSING),
        ]
        async with TsicApp(repo=FakeRepo(rows)).run_test() as pilot:
            table = pilot.app.query_one("#watchlist-table", DataTable)
            first = [str(c) for c in table.get_row_at(0)]
            second = [str(c) for c in table.get_row_at(1)]
            assert first[0] == "2330"
            assert first[-1] == STATUS_FRESH
            # A symbol with no cached data shows placeholders, not "None".
            assert second[-1] == STATUS_MISSING
            assert "None" not in second

    asyncio.run(scenario())


# --- AC-4: no bespoke theme / colour system -----------------------------


def test_uses_default_textual_theme_without_custom_css() -> None:
    """AC-4: the app defines no custom CSS colour system of its own."""
    assert not getattr(TsicApp, "CSS", "")
    assert not getattr(TsicApp, "CSS_PATH", None)
