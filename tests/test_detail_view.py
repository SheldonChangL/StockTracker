"""Tests for the TUI stock-detail screen (Story 8.2, FR-28, AC-1..AC-4).

The async bodies are driven through :func:`asyncio.run` (the project does not
depend on pytest-asyncio) while keeping the ``async with DetailApp(...).run_test()
as pilot`` harness Story 8.x specifies for Pilot-based assertions (AC-4).
"""

from __future__ import annotations

import asyncio

from textual.widgets import DataTable, Static

from tsic.models import ChipFlow, DailyPrice, Fundamental
from tsic.tui.detail_view import (
    CHIP_SUMMARY_ID,
    FUNDAMENTAL_SUMMARY_ID,
    MAX_OHLCV_ROWS,
    MISSING,
    NO_DATA,
    OHLCV_COLUMNS,
    OHLCV_TABLE_ID,
    DetailApp,
    StockDetail,
    chip_summary,
    fundamental_summary,
    ohlcv_rows,
)


def _price(date: str, close: float = 1.0) -> DailyPrice:
    return DailyPrice(
        symbol="2330",
        date=date,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=100,
        source="test",
    )


def _prices(n: int) -> list[DailyPrice]:
    """``n`` ascending-by-date price rows for 2330."""
    return [_price(f"2026-06-{d:02d}", close=float(d)) for d in range(1, n + 1)]


# --- AC-1 / AC-4: OHLCV projection (pure rule) ---------------------------


def test_ohlcv_rows_cap_at_thirty_newest_first() -> None:
    prices = _prices(40)
    rows = ohlcv_rows(prices)
    assert len(rows) == MAX_OHLCV_ROWS
    # Newest day first; only the most recent 30 days survive the cap.
    assert rows[0][0] == prices[-1].date
    assert rows[-1][0] == prices[-30].date


def test_ohlcv_rows_below_cap_keeps_all() -> None:
    rows = ohlcv_rows(_prices(5))
    assert len(rows) == 5
    assert rows[0][0] == "2026-06-05"  # newest first
    assert rows[-1][0] == "2026-06-01"


def test_ohlcv_rows_empty_is_empty() -> None:
    assert ohlcv_rows([]) == []


# --- AC-2: chip summary -------------------------------------------------


def test_chip_summary_uses_latest_record() -> None:
    chips = [
        ChipFlow("2330", "2026-06-01", 100, 10, -5, "test"),
        ChipFlow("2330", "2026-06-03", 200, 20, -7, "test"),
    ]
    summary = chip_summary(chips)
    assert "2026-06-03" in summary
    assert "外資 200" in summary
    assert "投信 20" in summary
    assert "自營商 -7" in summary


def test_chip_summary_no_data() -> None:
    assert chip_summary(None) == NO_DATA
    assert chip_summary([]) == NO_DATA


# --- AC-3: fundamental summary ------------------------------------------


def test_fundamental_summary_partial_marks_gaps() -> None:
    fundamental = Fundamental(symbol="2330", period="2026Q1", eps=8.5, revenue=None)
    rows = dict(fundamental_summary(fundamental))
    assert rows["季別"] == "2026Q1"
    assert rows["EPS"] == "8.5"
    # Optional fields the snapshot lacks render as the placeholder, not guesses.
    assert rows["營收"] == MISSING
    assert rows["本益比(季底)"] == MISSING


def test_fundamental_summary_none_all_missing() -> None:
    rows = fundamental_summary(None)
    assert len(rows) > 0
    assert all(value == MISSING for _, value in rows)


# --- AC-1 / AC-4: the detail widget via Pilot ---------------------------


def test_table_has_stable_id_and_columns() -> None:
    """AC-1: a DataTable with id=detail-ohlcv and the OHLCV columns."""

    async def scenario() -> None:
        detail = StockDetail(symbol="2330", prices=_prices(3))
        async with DetailApp(detail).run_test() as pilot:
            table = pilot.app.query_one(f"#{OHLCV_TABLE_ID}", DataTable)
            headers = [str(col.label) for col in table.ordered_columns]
            assert headers == list(OHLCV_COLUMNS)

    asyncio.run(scenario())


def test_ohlcv_row_count_capped_at_thirty() -> None:
    """AC-4: querying #detail-ohlcv yields a widget with row_count <= 30."""

    async def scenario() -> None:
        detail = StockDetail(symbol="2330", prices=_prices(45))
        async with DetailApp(detail).run_test() as pilot:
            table = pilot.app.query_one(f"#{OHLCV_TABLE_ID}", DataTable)
            assert table.row_count <= MAX_OHLCV_ROWS
            assert table.row_count == MAX_OHLCV_ROWS

    asyncio.run(scenario())


def test_chip_panel_shows_no_data_without_chips() -> None:
    """AC-2: no chip data renders the notice, never an error."""

    async def scenario() -> None:
        detail = StockDetail(symbol="2330", prices=_prices(3))
        async with DetailApp(detail).run_test() as pilot:
            panel = pilot.app.query_one(f"#{CHIP_SUMMARY_ID}", Static)
            assert NO_DATA in str(panel.render())

    asyncio.run(scenario())


def test_fundamental_panel_marks_missing_fields() -> None:
    """AC-3: partial fundamentals show available values and placeholders."""

    async def scenario() -> None:
        fundamental = Fundamental(symbol="2330", period="2026Q1", eps=8.5)
        detail = StockDetail(symbol="2330", prices=_prices(3), fundamental=fundamental)
        async with DetailApp(detail).run_test() as pilot:
            panel = pilot.app.query_one(f"#{FUNDAMENTAL_SUMMARY_ID}", Static)
            text = str(panel.render())
            assert "2026Q1" in text
            assert MISSING in text  # a gap is marked, not omitted

    asyncio.run(scenario())
