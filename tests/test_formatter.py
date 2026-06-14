"""Tests for the AI Markdown formatter and default prompt (Story 5.2, AC-1..AC-4)."""

from __future__ import annotations

from tsic.ai.formatter import (
    DEFAULT_PROMPT_TEMPLATE,
    build_prompt,
    to_markdown,
)
from tsic.models import ChipFlow, DailyPrice


def _prices() -> list[DailyPrice]:
    """Two representative daily-price rows for 2330."""
    return [
        DailyPrice(
            symbol="2330",
            date="2026-06-01",
            open=1000.0,
            high=1010.0,
            low=995.0,
            close=1005.0,
            volume=12000,
            source="twse",
        ),
        DailyPrice(
            symbol="2330",
            date="2026-06-02",
            open=1005.0,
            high=1020.0,
            low=1000.0,
            close=1018.0,
            volume=15000,
            source="twse",
        ),
    ]


def _chips() -> list[ChipFlow]:
    """Chip (籌碼面) rows matching the price dates above."""
    return [
        ChipFlow(
            symbol="2330",
            date="2026-06-01",
            foreign_net=5000,
            trust_net=-200,
            dealer_net=100,
            source="twse",
        ),
        ChipFlow(
            symbol="2330",
            date="2026-06-02",
            foreign_net=-3000,
            trust_net=400,
            dealer_net=-50,
            source="twse",
        ),
    ]


# AC-1: header carries the symbol and query range, plus a date/OHLCV/籌碼面 table.
def test_to_markdown_has_header_and_table() -> None:
    md = to_markdown("2330", _prices(), _chips())

    # Header: symbol and inclusive query range derived from the data.
    assert "2330" in md
    assert "查詢區間：2026-06-01 ~ 2026-06-02" in md

    # Table header carries OHLCV and 籌碼面 columns.
    for col in ("日期", "開盤", "最高", "最低", "收盤", "成交量"):
        assert col in md
    for col in ("外資", "投信", "自營商"):
        assert col in md

    # Markdown table separator row and one row per trading day are present.
    assert "| --- |" in md
    assert "| 2026-06-01 |" in md
    assert "| 2026-06-02 |" in md
    # Chip values rendered in their row.
    assert "5000" in md
    assert "-3000" in md


# AC-1: explicit --start/--end override the data-derived range in the header.
def test_to_markdown_uses_explicit_range() -> None:
    md = to_markdown("2330", _prices(), _chips(), start="2026-05-01", end="2026-06-30")

    assert "查詢區間：2026-05-01 ~ 2026-06-30" in md


# AC-2: default prompt substitutes {代號} with the real symbol.
def test_build_prompt_default_substitutes_symbol() -> None:
    prompt = build_prompt("2330")

    assert prompt == (
        "請分析以下台灣股票 2330 近期走勢，包含技術面觀察與籌碼面變化，並給出簡要看法。"
    )
    assert "{代號}" not in prompt
    # The template itself still carries the placeholder.
    assert "{代號}" in DEFAULT_PROMPT_TEMPLATE


# AC-3: an override prompt is used verbatim instead of the default.
def test_build_prompt_override_wins() -> None:
    override = "只看技術面，給三個關鍵價位。"

    prompt = build_prompt("2330", override=override)

    assert prompt == override
    assert "近期走勢" not in prompt


# AC-4: with no chip data the 籌碼面 columns are omitted and no error is raised.
def test_to_markdown_without_chips_skips_chip_columns() -> None:
    md = to_markdown("2330", _prices())

    for col in ("日期", "開盤", "收盤", "成交量"):
        assert col in md
    for col in ("外資", "投信", "自營商"):
        assert col not in md
    assert "| 2026-06-01 |" in md


# AC-4 corollary: passing an empty chip list behaves like no chips.
def test_to_markdown_empty_chip_list_skips_chip_columns() -> None:
    md = to_markdown("2330", _prices(), [])

    assert "外資" not in md


# AC-4 corollary: a partial chip set leaves a missing-data marker, not an error.
def test_to_markdown_partial_chips_marks_missing_rows() -> None:
    md = to_markdown("2330", _prices(), _chips()[:1])

    # Chip columns appear (chip data present) but the second day has no chip row.
    assert "外資" in md
    assert "—" in md


def test_to_markdown_empty_prices_renders_header_only() -> None:
    md = to_markdown("2330", [])

    assert "台灣股票 2330" in md
    assert "查詢區間： ~ " in md
    # Header row of the table is present; no data rows.
    assert "| 日期 |" in md
