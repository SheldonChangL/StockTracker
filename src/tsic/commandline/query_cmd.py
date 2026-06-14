"""Query-result output formatting for the ``tsic query`` command (Story 4.1).

This module is the *prerequisite* presentation layer for querying stored market
data: it turns a list of :class:`~tsic.models.DailyPrice` rows into one of three
textual representations so the result can be piped to other tools or read
directly (FR-19).

* ``json`` — a valid JSON array of objects (``[]`` when empty), each object
  carrying every OHLCV field plus ``date``/``symbol`` (AC-1/AC-4).
* ``csv``  — a header row followed by one line per record, columns in a fixed
  order; an empty result yields the header alone (AC-2/AC-4).
* ``table`` — a Rich table rendered to a string; an empty result renders the
  header with no body rows rather than raising (AC-3/AC-4).

The column order is the single source of truth derived from the
:class:`~tsic.models.DailyPrice` dataclass field order, so every format agrees
on which columns appear and in what sequence.

Wiring this formatter into the ``tsic query`` command (argument parsing, the
``--format`` flag, db access) is delivered by a later story; here we expose only
:func:`format_output` so it can be unit-tested in isolation.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import asdict, fields

from rich.console import Console
from rich.table import Table

from tsic.models import DailyPrice

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
