"""Tests for query output formatting (Story 4.1, AC-1..AC-4, FR-19)."""

from __future__ import annotations

import csv
import io
import json

import pytest

from tsic.commandline.query_cmd import _COLUMNS, format_output
from tsic.models import DailyPrice


def _rows() -> list[DailyPrice]:
    """Two representative DailyPrice rows for the happy-path formats."""
    return [
        DailyPrice(
            symbol="2330", date="2026-06-01", open=1.0, high=2.0, low=0.5,
            close=1.5, volume=1000, source="twse", adjusted=0,
        ),
        DailyPrice(
            symbol="2330", date="2026-06-02", open=1.5, high=2.5, low=1.0,
            close=2.0, volume=2000, source="twse", adjusted=0,
        ),
    ]


# AC-1: json produces a valid JSON array carrying OHLCV/date/symbol per row.
def test_json_is_valid_array_with_expected_fields() -> None:
    parsed = json.loads(format_output(_rows(), "json"))

    assert isinstance(parsed, list)
    assert len(parsed) == 2
    for col in ("symbol", "date", "open", "high", "low", "close", "volume"):
        assert col in parsed[0]
    assert parsed[0]["symbol"] == "2330"
    assert parsed[0]["close"] == 1.5
    assert parsed[1]["date"] == "2026-06-02"


# AC-2: csv has a header row first, one row per record, fixed column order.
def test_csv_has_header_and_one_row_per_record() -> None:
    rendered = format_output(_rows(), "csv")
    reader = list(csv.reader(io.StringIO(rendered)))

    assert reader[0] == list(_COLUMNS)  # header, fixed order
    assert len(reader) == 3  # header + 2 records
    assert reader[1][0] == "2330"
    assert reader[1][1] == "2026-06-01"


# AC-3: table renders to a Rich table string containing headers and values.
def test_table_renders_rich_string() -> None:
    rendered = format_output(_rows(), "table")

    assert isinstance(rendered, str)
    for col in _COLUMNS:
        assert col in rendered
    assert "2330" in rendered
    assert "2026-06-01" in rendered


# AC-4: empty result — csv header only, json "[]", table header w/o body, no error.
def test_empty_json_is_empty_array() -> None:
    assert json.loads(format_output([], "json")) == []


def test_empty_csv_is_header_only() -> None:
    rendered = format_output([], "csv")
    reader = list(csv.reader(io.StringIO(rendered)))

    assert reader == [list(_COLUMNS)]  # header only, no data rows


def test_empty_table_renders_without_error() -> None:
    rendered = format_output([], "table")

    assert isinstance(rendered, str)
    for col in _COLUMNS:
        assert col in rendered  # header still present


def test_unsupported_format_raises_value_error() -> None:
    with pytest.raises(ValueError):
        format_output([], "xml")
