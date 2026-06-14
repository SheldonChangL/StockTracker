"""The ``tsic fetch`` command: fetch prices for symbols and summarize (Story 3.8).

This is the *vertical* entry point that turns ``tsic fetch 2330`` into a real
batch run: it resolves the symbols to fetch (positional args, a ``--file`` list,
or every symbol already tracked in the local cache via ``--all``), opens and
migrates the database, and drives the concurrent
:class:`~tsic.fetching.orchestrator.FetchOrchestrator` (Story 3.7) over the
configured sources, printing the human-readable summary at the end.

Two seams keep the command testable without touching the real network:

* :func:`_default_sources` builds the real, network-backed price sources and is
  the single place tests monkeypatch to inject an in-process loopback source.
* :data:`FetchOrchestrator` is imported at module scope so tests can substitute
  a spy to assert wiring (e.g. the clamped ``concurrency``).

Exit code follows the batch outcome: a run where *every* symbol failed exits
``1``; any success (even a partial one) exits ``0`` — partial failure is not a
whole-batch failure (AC-2/AC-3).
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from pathlib import Path

import typer

from tsic.fetching import FetchOrchestrator
from tsic.sources import TwseSource, YfinanceSource
from tsic.sources.base import BaseSource
from tsic.storage import database, migrations, summary
from tsic.storage.repository import PriceRepository

#: Default symbols fetched concurrently when ``--concurrency`` is not given.
_DEFAULT_CONCURRENCY = 3

#: Hard ceiling on concurrency; higher requests are clamped here (AC-5).
_MAX_CONCURRENCY = 10

#: Default lookback window (days) for a symbol with no stored history, used
#: when ``--start`` is omitted. The orchestrator otherwise resumes each symbol
#: from ``MAX(date) + 1``, so this only bounds a brand-new symbol's backfill.
_DEFAULT_HISTORY_DAYS = 365


def _default_sources() -> list[BaseSource]:
    """Build the real, network-backed price sources in priority order.

    Exposed as a module-level function so tests can monkeypatch it to inject an
    in-process loopback source (a ``FakeSource``) instead of hitting the network.
    """
    return [YfinanceSource(), TwseSource()]


def _clamp_concurrency(value: int) -> int:
    """Clamp requested concurrency into ``[1, _MAX_CONCURRENCY]`` (AC-5)."""
    return max(1, min(value, _MAX_CONCURRENCY))


def _read_symbols_file(path: Path) -> list[str]:
    """Read one symbol per non-empty line from ``path`` (AC-4)."""
    lines = path.read_text(encoding="utf-8").splitlines()
    return [stripped for line in lines if (stripped := line.strip())]


def _tracked_symbols(conn: sqlite3.Connection) -> list[str]:
    """Return every symbol the local cache already tracks (AC-4, ``--all``).

    "Tracked" mirrors ``tsic db status``: any symbol with stored data, derived
    from :func:`tsic.storage.summary.symbol_latest_dates`.
    """
    return [symbol for symbol, _ in summary.symbol_latest_dates(conn)]


def _resolve_symbols(
    symbols: list[str],
    file: Path | None,
    all_tracked: bool,
    conn: sqlite3.Connection,
) -> list[str]:
    """Merge positional args, a ``--file`` list, and ``--all`` into one set.

    Sources are combined and de-duplicated while preserving first-seen order so
    the run is deterministic regardless of how the symbols were supplied (AC-4).
    """
    collected: list[str] = list(symbols)
    if file is not None:
        collected.extend(_read_symbols_file(file))
    if all_tracked:
        collected.extend(_tracked_symbols(conn))

    seen: set[str] = set()
    ordered: list[str] = []
    for symbol in collected:
        if symbol not in seen:
            seen.add(symbol)
            ordered.append(symbol)
    return ordered


def fetch(
    symbols: list[str] = typer.Argument(
        None, help="股票代號，可指定多個（例如 2330 2317）。"
    ),
    db_path: Path | None = typer.Option(
        None,
        "--db",
        "--db-path",
        help="覆寫資料庫路徑（預設 ~/.tsic/data.db）。",
    ),
    file: Path | None = typer.Option(
        None, "--file", help="從檔案讀取代號，每行一個。"
    ),
    all_tracked: bool = typer.Option(
        False, "--all", help="抓取資料庫中所有已追蹤的代號。"
    ),
    concurrency: int = typer.Option(
        _DEFAULT_CONCURRENCY,
        "--concurrency",
        help=f"同時抓取的代號數，上限 {_MAX_CONCURRENCY}。",
    ),
    start: str | None = typer.Option(
        None, "--start", help="新代號回補的起始日（ISO YYYY-MM-DD）。"
    ),
    end: str | None = typer.Option(
        None, "--end", help="抓取的結束日（ISO YYYY-MM-DD，預設今天）。"
    ),
) -> None:
    """Fetch market data for the given symbols and print a summary."""
    conn = database.connect(db_path, check_same_thread=False)
    try:
        migrations.migrate(conn)
        resolved = _resolve_symbols(symbols or [], file, all_tracked, conn)
        if not resolved:
            typer.echo("未指定任何代號（提供代號、--file 或 --all）。")
            raise typer.Exit(code=1)

        end_date = end or date.today().isoformat()
        start_date = start or (
            date.today() - timedelta(days=_DEFAULT_HISTORY_DAYS)
        ).isoformat()

        orchestrator = FetchOrchestrator(
            _default_sources(),
            PriceRepository(conn),
            concurrency=_clamp_concurrency(concurrency),
        )
        result = orchestrator.fetch_prices(resolved, start_date, end_date)
    finally:
        conn.close()

    typer.echo(result.render())

    # Whole-batch failure (every symbol failed) exits 1; any success — including
    # a partial one — exits 0 (AC-2/AC-3).
    if result.results and result.failed_count == len(result.results):
        raise typer.Exit(code=1)
