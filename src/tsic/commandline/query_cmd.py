"""The ``tsic query`` command: read cached prices and render a range (Story 4.2).

This module is the *vertical* entry point that turns ``tsic query 2330`` into a
real cache read: it opens and migrates the local database, runs an inclusive
date-range query through :class:`~tsic.storage.repository.PriceRepository`
(Story 2.4), and renders the result in the requested format (FR-19, NFR-4).

The presentation layer (the prerequisite from Story 4.1) turns a list of
:class:`~tsic.models.DailyPrice` rows into one of three textual representations
so the result can be piped to other tools or read directly:

* ``json`` — a valid JSON array of objects (``[]`` when empty), each object
  carrying every OHLCV field plus ``date``/``symbol`` (AC-1).
* ``csv``  — a header row followed by one line per record, columns in a fixed
  order; an empty result yields the header alone (AC-2).
* ``table`` — a Rich table rendered to a string; an empty result renders the
  header with no body rows rather than raising.

The column order is the single source of truth derived from the
:class:`~tsic.models.DailyPrice` dataclass field order, so every format agrees
on which columns appear and in what sequence.

Exit code follows the query outcome: a query that matches at least one row
prints the formatted result and exits ``0`` (AC-1); a query that matches no
rows — an unknown symbol or an empty range — prints a "no data" notice and
exits ``2`` (AC-3).
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import asdict, fields
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from tsic.models import DailyPrice
from tsic.storage import database, migrations
from tsic.storage.repository import PriceRepository

#: Default inclusive range bounds used when ``--start`` / ``--end`` are omitted.
#: ISO date strings compare lexically, so these sentinels select every stored
#: row regardless of its date.
_MIN_DATE = "0001-01-01"
_MAX_DATE = "9999-12-31"

#: Output columns in fixed order, derived from the ``DailyPrice`` field order so
#: every format (json/csv/table) shares one column contract (AC-1/AC-2).
_COLUMNS: tuple[str, ...] = tuple(f.name for f in fields(DailyPrice))

#: Supported output formats, used to validate the ``fmt`` argument.
_FORMATS = ("csv", "json", "table")


def format_output(rows: list[DailyPrice], fmt: str) -> str:
    """Render ``rows`` as ``csv``, ``json``, or ``table`` (FR-19).

    Args:
        rows: The query result; an empty list is valid and never raises (AC-4).
        fmt: One of ``"csv"``, ``"json"``, or ``"table"``.

    Returns:
        The formatted result as a string.

    Raises:
        ValueError: If ``fmt`` is not a supported format.
    """
    if fmt == "json":
        return _to_json(rows)
    if fmt == "csv":
        return _to_csv(rows)
    if fmt == "table":
        return _to_table(rows)
    raise ValueError(f"unsupported format {fmt!r}; expected one of {_FORMATS}")


def _to_json(rows: list[DailyPrice]) -> str:
    """Serialize ``rows`` to a JSON array (``[]`` when empty) (AC-1/AC-4)."""
    payload = [{col: getattr(row, col) for col in _COLUMNS} for row in rows]
    return json.dumps(payload, ensure_ascii=False)


def _to_csv(rows: list[DailyPrice]) -> str:
    """Serialize ``rows`` to CSV: header first, one line per record (AC-2/AC-4).

    The header is always emitted, so an empty result yields header-only output.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(asdict(row))
    return buffer.getvalue()


def _to_table(rows: list[DailyPrice]) -> str:
    """Render ``rows`` as a Rich table string; empty shows header only (AC-3/AC-4)."""
    table = Table()
    for col in _COLUMNS:
        table.add_column(col)
    for row in rows:
        table.add_row(*(str(getattr(row, col)) for col in _COLUMNS))

    console = Console()
    with console.capture() as capture:
        console.print(table)
    return capture.get()


def query(
    symbol: str = typer.Argument(..., help="股票代號（例如 2330）。"),
    db_path: Path | None = typer.Option(
        None,
        "--db",
        "--db-path",
        help="覆寫資料庫路徑（預設 ~/.tsic/data.db）。",
    ),
    start: str = typer.Option(
        _MIN_DATE, "--start", help="查詢區間起始日（ISO YYYY-MM-DD，含當日）。"
    ),
    end: str = typer.Option(
        _MAX_DATE, "--end", help="查詢區間結束日（ISO YYYY-MM-DD，含當日）。"
    ),
    fmt: str = typer.Option(
        "table", "--format", help=f"輸出格式：{'/'.join(_FORMATS)}。"
    ),
) -> None:
    """Query cached prices for SYMBOL and print the matching range (FR-19).

    Reads from the local cache only — no network access — so a cached query
    returns well within the NFR-4 budget (AC-4). Matching rows are printed in
    the requested format and the command exits ``0`` (AC-1/AC-2); a query that
    matches nothing prints a notice and exits ``2`` (AC-3).
    """
    if fmt not in _FORMATS:
        raise typer.BadParameter(
            f"unsupported format {fmt!r}; expected one of {_FORMATS}",
            param_hint="--format",
        )

    conn = database.connect(db_path)
    try:
        migrations.migrate(conn)
        rows = PriceRepository(conn).query_prices(symbol, start, end)
    finally:
        conn.close()

    if not rows:
        typer.echo(f"無資料：{symbol} 在指定區間內沒有任何記錄。")
        raise typer.Exit(code=2)

    typer.echo(format_output(rows, fmt))
