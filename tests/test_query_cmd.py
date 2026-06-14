"""Tests for query output formatting (Story 4.1) and the ``tsic query``
command wiring (Story 4.2, AC-1..AC-4, FR-19/NFR-4)."""

from __future__ import annotations

import csv
import io
import json
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tsic.commandline.app import app
from tsic.commandline.query_cmd import _COLUMNS, format_output
from tsic.models import DailyPrice
from tsic.storage import database, migrations

runner = CliRunner()


def _rows() -> list[DailyPrice]:
    """Two representative DailyPrice rows for the happy-path formats."""
    return [
        DailyPrice(
            symbol="2330",
            date="2026-06-01",
            open=1.0,
            high=2.0,
            low=0.5,
            close=1.5,
            volume=1000,
            source="twse",
            adjusted=0,
        ),
        DailyPrice(
            symbol="2330",
            date="2026-06-02",
            open=1.5,
            high=2.5,
            low=1.0,
            close=2.0,
            volume=2000,
            source="twse",
            adjusted=0,
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


# --- tsic query command (Story 4.2) ------------------------------------------


def _seed(path: Path, symbol: str = "2330", dates: tuple[str, ...] = ()) -> None:
    """Insert one raw daily-price row per date for ``symbol`` into ``path``."""
    conn = database.connect(path)
    try:
        migrations.migrate(conn)
        for day in dates:
            conn.execute(
                "INSERT INTO daily_prices "
                "(symbol, date, open, high, low, close, volume, source, adjusted) "
                "VALUES (?, ?, 1, 2, 0.5, 1.5, 1000, 'twse', 0)",
                (symbol, day),
            )
        conn.commit()
    finally:
        conn.close()


# AC-1: querying a populated symbol prints JSON and exits 0.
def test_query_json_outputs_rows_and_exits_zero(tmp_path: Path) -> None:
    db_path = tmp_path / "t.db"
    _seed(db_path, "2330", dates=("2026-06-01", "2026-06-02"))

    result = runner.invoke(
        app, ["query", "2330", "--format", "json", "--db", str(db_path)]
    )

    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert [row["date"] for row in parsed] == ["2026-06-01", "2026-06-02"]
    assert parsed[0]["symbol"] == "2330"


# AC-2: --start/--end restrict output to records inside the inclusive range.
def test_query_filters_by_date_range(tmp_path: Path) -> None:
    db_path = tmp_path / "t.db"
    _seed(
        db_path,
        "2330",
        dates=("2025-12-31", "2026-01-01", "2026-03-31", "2026-04-01"),
    )

    result = runner.invoke(
        app,
        [
            "query",
            "2330",
            "--format",
            "json",
            "--start",
            "2026-01-01",
            "--end",
            "2026-03-31",
            "--db",
            str(db_path),
        ],
    )

    assert result.exit_code == 0
    dates = [row["date"] for row in json.loads(result.stdout)]
    assert dates == ["2026-01-01", "2026-03-31"]


# AC-3: an unknown symbol prints a "no data" notice and exits 2.
def test_query_unknown_symbol_exits_two(tmp_path: Path) -> None:
    db_path = tmp_path / "t.db"
    _seed(db_path, "2330", dates=("2026-06-01",))

    result = runner.invoke(
        app, ["query", "9999", "--format", "json", "--db", str(db_path)]
    )

    assert result.exit_code == 2
    assert "無資料" in result.stdout


# AC-3: a symbol with rows but none inside the range is also "no data" (exit 2).
def test_query_empty_range_exits_two(tmp_path: Path) -> None:
    db_path = tmp_path / "t.db"
    _seed(db_path, "2330", dates=("2026-06-01",))

    result = runner.invoke(
        app,
        [
            "query",
            "2330",
            "--start",
            "2020-01-01",
            "--end",
            "2020-12-31",
            "--db",
            str(db_path),
        ],
    )

    assert result.exit_code == 2
    assert "無資料" in result.stdout


# AC-4: a cached query completes well within the 500ms budget (NFR-4).
def test_query_completes_within_budget(tmp_path: Path) -> None:
    db_path = tmp_path / "t.db"
    _seed(db_path, "2330", dates=tuple(f"2026-06-{d:02d}" for d in range(1, 29)))

    started = time.perf_counter()
    result = runner.invoke(
        app, ["query", "2330", "--format", "json", "--db", str(db_path)]
    )
    elapsed = time.perf_counter() - started

    assert result.exit_code == 0
    assert elapsed < 0.5


def test_query_invalid_format_is_rejected(tmp_path: Path) -> None:
    db_path = tmp_path / "t.db"
    _seed(db_path, "2330", dates=("2026-06-01",))

    result = runner.invoke(
        app, ["query", "2330", "--format", "xml", "--db", str(db_path)]
    )

    # Typer reports an invalid option value as a usage error (exit 2) and never
    # reaches the cache read, so no rows are printed.
    assert result.exit_code != 0
    assert "無資料" not in result.output
