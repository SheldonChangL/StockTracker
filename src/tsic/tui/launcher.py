"""Production wiring that turns ``tsic tui`` into a running app (Story 8.4).

Story 8.1–8.3 left :class:`~tsic.tui.app.TsicApp` deliberately storage-agnostic:
it renders an injected :class:`~tsic.tui.watchlist_view.WatchlistSource`, fetches
through an injected orchestrator, and analyses through an injected
:class:`~tsic.tui.app.Analyzer`. This module supplies the real implementations of
those seams and assembles them over a migrated SQLite connection, so the CLI's
``tui`` command launches the interactive console while the key paths stay the
same ones the tests drive against fakes (AC-1/AC-2/AC-4).

* :class:`StorageWatchlistSource` projects the tracked watchlist plus each
  symbol's cached-price summary into the :class:`~tsic.tui.watchlist_view.WatchlistRow`
  the table renders.
* :class:`CacheAnalyzer` reuses the Story 5.x analysis path — cache read →
  :func:`~tsic.ai.formatter.to_markdown` → default
  :func:`~tsic.ai.formatter.build_prompt` question → :func:`tsic.ai.pipe.run` —
  behind the one-method :class:`~tsic.tui.app.Analyzer` protocol.
* :func:`build_app` wires both over an open connection (easy to drive headless
  via ``run_test()``), and :func:`launch` opens/migrates the database, resolves
  the AI CLI, builds the app, and runs it on a real terminal.
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from pathlib import Path

from tsic.ai.formatter import build_prompt, to_markdown
from tsic.ai.pipe import Runner, resolve_agent_command, run
from tsic.fetching.orchestrator import FetchOrchestrator
from tsic.sources import TwseSource, YfinanceSource
from tsic.storage import database, migrations
from tsic.storage.repository import PriceRepository, WatchlistRepository
from tsic.tui.app import TsicApp
from tsic.tui.watchlist_view import (
    STATUS_MISSING,
    WatchlistRow,
    classify_freshness,
)

#: Sentinels selecting *every* stored row when reading the cache for a symbol.
#: ISO date strings compare lexically, so these bound the full history.
_MIN_DATE = "0001-01-01"
_MAX_DATE = "9999-12-31"

#: A symbol whose latest stored date is within this many days counts as fresh
#: in the watchlist status column (Story 8.1's freshness rule).
_FRESH_WITHIN_DAYS = 3

#: Lookback window (days) used as the fetch start when updating a brand-new
#: symbol; the orchestrator otherwise resumes from ``MAX(date) + 1``.
_DEFAULT_HISTORY_DAYS = 365


class StorageWatchlistSource:
    """A :class:`~tsic.tui.watchlist_view.WatchlistSource` backed by storage.

    Reads the tracked symbols from :class:`~tsic.storage.repository.WatchlistRepository`
    and summarises each one's cached prices via
    :class:`~tsic.storage.repository.PriceRepository`, mapping the pair into the
    display-ready :class:`~tsic.tui.watchlist_view.WatchlistRow` the table renders.
    """

    def __init__(
        self,
        watchlist: WatchlistRepository,
        prices: PriceRepository,
        *,
        today: date,
        fresh_within_days: int = _FRESH_WITHIN_DAYS,
    ) -> None:
        self._watchlist = watchlist
        self._prices = prices
        self._today = today
        self._fresh_within_days = fresh_within_days

    def watchlist_rows(self) -> list[WatchlistRow]:
        """Return one row per tracked symbol with its cached-price summary."""
        rows: list[WatchlistRow] = []
        for entry in self._watchlist.list():
            symbol = entry.symbol
            prices = self._prices.query_prices(symbol, _MIN_DATE, _MAX_DATE)
            if not prices:
                rows.append(WatchlistRow(symbol, status=STATUS_MISSING))
                continue
            latest = prices[-1]
            status = classify_freshness(
                latest.date, today=self._today, fresh_within_days=self._fresh_within_days
            )
            rows.append(
                WatchlistRow(
                    symbol=symbol,
                    latest_close=latest.close,
                    latest_date=latest.date,
                    row_count=len(prices),
                    status=status,
                )
            )
        return rows


class CacheAnalyzer:
    """An :class:`~tsic.tui.app.Analyzer` over the cache and an AI CLI (AC-2).

    Reads a symbol's cached prices, renders them to Markdown, prepends the
    *default* analysis question (:func:`~tsic.ai.formatter.build_prompt` with no
    override), and pipes the payload to the resolved AI CLI, returning its stdout
    verbatim — the same vertical path as ``tsic analyze`` (Story 5.4). The
    subprocess ``runner`` is injectable so a test can assert the agent was called
    without spawning a process.
    """

    def __init__(
        self,
        prices: PriceRepository,
        agent_command: str,
        *,
        runner: Runner | None = None,
    ) -> None:
        self._prices = prices
        self._agent_command = agent_command
        self._runner = runner

    def analyze(self, symbol: str) -> str:
        """Analyse ``symbol`` with the default question and return the AI output."""
        prices = self._prices.query_prices(symbol, _MIN_DATE, _MAX_DATE)
        markdown = to_markdown(symbol, prices)
        instruction = build_prompt(symbol)
        payload = f"{instruction}\n\n{markdown}"
        if self._runner is not None:
            return run(self._agent_command, payload, runner=self._runner)
        return run(self._agent_command, payload)


def build_app(
    conn: sqlite3.Connection,
    *,
    today: date,
    agent_command: str | None,
    date_range: tuple[str, str],
) -> TsicApp:
    """Assemble a :class:`~tsic.tui.app.TsicApp` over an open, migrated connection.

    Kept separate from :func:`launch` so a test can drive the fully-wired app
    headless via ``run_test()`` (AC-4). The analyzer is wired only when an AI CLI
    was resolved; otherwise the ``a`` key is a no-op rather than an error.
    """
    prices = PriceRepository(conn)
    watchlist = WatchlistRepository(conn)
    repo = StorageWatchlistSource(watchlist, prices, today=today)
    orchestrator = FetchOrchestrator([YfinanceSource(), TwseSource()], prices)
    symbols = [entry.symbol for entry in watchlist.list()]
    analyzer = CacheAnalyzer(prices, agent_command) if agent_command else None
    return TsicApp(
        repo=repo,
        orchestrator=orchestrator,
        symbols=symbols,
        date_range=date_range,
        analyzer=analyzer,
    )


def launch(db_path: Path | None = None) -> None:
    """Open/migrate the database, build the app, and run it (``tsic tui``).

    A shared connection backs the watchlist render, the fetch worker, and the
    analysis worker, so it is opened with ``check_same_thread=False`` (the
    orchestrator serialises writes behind its own lock under WAL).
    """
    conn = database.connect(db_path, check_same_thread=False)
    try:
        migrations.migrate(conn)
        today = date.today()
        date_range = (
            (today - timedelta(days=_DEFAULT_HISTORY_DAYS)).isoformat(),
            today.isoformat(),
        )
        agent_command = resolve_agent_command(None)
        app = build_app(
            conn, today=today, agent_command=agent_command, date_range=date_range
        )
        app.run()
    finally:
        conn.close()
