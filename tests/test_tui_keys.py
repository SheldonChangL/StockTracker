"""Tests for the keyboard-driven TUI flow (Story 8.4, FR-26/FR-29, AC-1..AC-4).

The story's harness is ``async with TsicApp(...).run_test() as pilot`` driving
``await pilot.press(...)``. The project does not depend on pytest-asyncio, so each
async body is run through :func:`asyncio.run`, matching the rest of Story 8.x.

* AC-1 (``f``): the *selected* watchlist row is updated on a threaded worker.
* AC-2 (``a``): the default analysis question reaches the injected agent.
* AC-3 (``q``): the app quits.
* AC-4: the fully-wired app launches headless without raising.
"""

from __future__ import annotations

import asyncio
import threading

from tsic.ai.formatter import build_prompt
from tsic.fetching.orchestrator import FetchOrchestrator
from tsic.models import ChipFlow, DailyPrice, Fundamental
from tsic.sources.base import BaseSource
from tsic.storage import database, migrations
from tsic.storage.repository import PriceRepository, WatchlistRepository
from tsic.tui.app import TsicApp
from tsic.tui.launcher import CacheAnalyzer, build_app
from tsic.tui.watchlist_view import STATUS_FRESH, WatchlistRow


class FakeRepo:
    """A WatchlistSource returning a fixed set of rows."""

    def __init__(self, rows: list[WatchlistRow]) -> None:
        self._rows = rows

    def watchlist_rows(self) -> list[WatchlistRow]:
        return self._rows


class _RecordingSource(BaseSource):
    """In-memory price source recording which symbols it fetched.

    When ``gate`` is set each fetch blocks on the event after recording, letting
    a test hold the worker mid-fetch to prove it runs off the event loop.
    """

    concurrency = 1
    rate_limit = 1.0

    def __init__(
        self,
        *,
        gate: threading.Event | None = None,
        entered: threading.Event | None = None,
    ) -> None:
        self._gate = gate
        self._entered = entered
        self.fetched: list[str] = []

    name = property(lambda self: "fake")  # type: ignore[assignment]
    priority = property(lambda self: 1)  # type: ignore[assignment]

    @property
    def available(self) -> bool:
        return True

    def fetch_prices(self, symbol: str, start: str, end: str) -> list[DailyPrice]:
        self.fetched.append(symbol)
        if self._entered is not None:
            self._entered.set()
        if self._gate is not None:
            self._gate.wait(timeout=5.0)
        return [
            DailyPrice(
                symbol=symbol,
                date="2026-06-10",
                open=1.0,
                high=1.0,
                low=1.0,
                close=1.0,
                volume=1,
                source="fake",
            )
        ]

    def fetch_chips(self, symbol: str, start: str, end: str) -> list[ChipFlow]:
        raise NotImplementedError

    def fetch_fundamentals(
        self, symbol: str, start: str, end: str
    ) -> list[Fundamental]:
        raise NotImplementedError


class FakeRepoStore:
    """Thread-safe in-memory PriceRepository stand-in (first-write-wins)."""

    def __init__(self) -> None:
        self._rows: dict[tuple[str, str], DailyPrice] = {}
        self._lock = threading.Lock()

    def latest_date(self, symbol: str) -> str | None:
        with self._lock:
            dates = [d for (s, d) in self._rows if s == symbol]
        return max(dates) if dates else None

    def upsert_prices(self, prices: list[DailyPrice]) -> int:
        written = 0
        with self._lock:
            for price in prices:
                key = (price.symbol, price.date)
                if key not in self._rows:
                    self._rows[key] = price
                    written += 1
        return written


def _two_row_repo() -> FakeRepo:
    return FakeRepo(
        [
            WatchlistRow("2330", "台積電", 1000.0, "2026-06-13", 250, STATUS_FRESH),
            WatchlistRow("2317", "鴻海", 200.0, "2026-06-13", 200, STATUS_FRESH),
        ]
    )


# --- AC-1: "f" updates only the selected row, on a threaded worker ----------


def test_press_f_runs_selected_update_on_worker() -> None:
    """AC-1: ``f`` starts a background worker that fetches only the cursor row."""

    async def scenario() -> None:
        gate = threading.Event()
        entered = threading.Event()
        source = _RecordingSource(gate=gate, entered=entered)
        orch = FetchOrchestrator([source], FakeRepoStore(), concurrency=1)
        app = TsicApp(
            repo=_two_row_repo(),
            orchestrator=orch,
            symbols=["2330", "2317"],
            date_range=("2026-06-01", "2026-06-30"),
        )
        try:
            async with app.run_test() as pilot:
                await pilot.press("f")
                await pilot.pause()
                # The fetch is held in the source, so the update is observably
                # in-flight on exactly one worker (not run inline on the loop).
                assert entered.wait(timeout=2.0)
                assert len(list(pilot.app.workers)) == 1
                gate.set()
                await pilot.app.workers.wait_for_complete()
                # Only the cursor-selected symbol was fetched, not the batch.
                assert source.fetched == ["2330"]
        finally:
            gate.set()

    asyncio.run(scenario())


def test_press_f_is_noop_on_empty_watchlist() -> None:
    """An empty watchlist has no selectable row, so ``f`` starts no worker."""

    async def scenario() -> None:
        source = _RecordingSource()
        orch = FetchOrchestrator([source], FakeRepoStore(), concurrency=1)
        app = TsicApp(
            repo=FakeRepo([]),
            orchestrator=orch,
            symbols=["2330"],
            date_range=("2026-06-01", "2026-06-30"),
        )
        async with app.run_test() as pilot:
            await pilot.press("f")
            await pilot.pause()
            assert not list(pilot.app.workers)
            assert source.fetched == []

    asyncio.run(scenario())


# --- AC-2: "a" runs the analysis path with the default question -------------


class _RecordingAnalyzer:
    """A fake :class:`~tsic.tui.app.Analyzer` recording the analysed symbol."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def analyze(self, symbol: str) -> str:
        self.calls.append(symbol)
        return f"分析：{symbol}"


def test_press_a_analyzes_selected_symbol() -> None:
    """AC-2: ``a`` runs the analyzer for the cursor row and stores its output."""

    async def scenario() -> None:
        analyzer = _RecordingAnalyzer()
        app = TsicApp(repo=_two_row_repo(), analyzer=analyzer)
        async with app.run_test() as pilot:
            await pilot.press("a")
            await pilot.app.workers.wait_for_complete()
            await pilot.pause()
            assert analyzer.calls == ["2330"]
            assert pilot.app.last_analysis is not None
            assert pilot.app.last_analysis.symbol == "2330"
            assert pilot.app.last_analysis.output == "分析：2330"

    asyncio.run(scenario())


def test_press_a_pipes_default_question_to_agent() -> None:
    """AC-2 (vertical): the real CacheAnalyzer pipes the default prompt to the AI CLI.

    The subprocess runner is faked so no process is spawned, but the rest of the
    analysis path (cache read → Markdown → default ``build_prompt`` question →
    pipe) is the production one.
    """

    async def scenario() -> None:
        captured: dict[str, object] = {}

        def fake_runner(argv: list[str], payload: str) -> str:
            captured["argv"] = argv
            captured["payload"] = payload
            return "AI 回應"

        # The analyzer reads on a worker thread, so share the connection across
        # threads exactly as ``launch()`` does in production.
        conn = database.connect(":memory:", check_same_thread=False)
        migrations.migrate(conn)
        prices = PriceRepository(conn)
        prices.upsert_prices(
            [
                DailyPrice(
                    symbol="2330",
                    date="2026-06-13",
                    open=1000.0,
                    high=1010.0,
                    low=990.0,
                    close=1005.0,
                    volume=12345,
                    source="fake",
                )
            ]
        )
        analyzer = CacheAnalyzer(prices, "cat", runner=fake_runner)
        app = TsicApp(repo=_two_row_repo(), analyzer=analyzer)
        try:
            async with app.run_test() as pilot:
                await pilot.press("a")
                await pilot.app.workers.wait_for_complete()
                await pilot.pause()
                assert captured["argv"] == ["cat"]
                payload = captured["payload"]
                assert isinstance(payload, str)
                # The default analysis question (no override) drove the prompt.
                assert build_prompt("2330") in payload
                assert "2330" in payload
                assert pilot.app.last_analysis is not None
                assert pilot.app.last_analysis.output == "AI 回應"
        finally:
            conn.close()

    asyncio.run(scenario())


def test_press_a_is_noop_without_analyzer() -> None:
    """No analyzer injected means ``a`` does nothing (no worker, no output)."""

    async def scenario() -> None:
        async with TsicApp(repo=_two_row_repo()).run_test() as pilot:
            await pilot.press("a")
            await pilot.pause()
            assert not list(pilot.app.workers)
            assert pilot.app.last_analysis is None

    asyncio.run(scenario())


# --- TUI watchlist editing: "n" adds, "d" removes ---------------------------


class FakeWatchlist:
    """A WatchlistSource that is also a WatchlistEditor, backed by a symbol list."""

    def __init__(self, symbols: tuple[str, ...] = ()) -> None:
        self.symbols = list(symbols)
        self.added: list[str] = []
        self.removed: list[str] = []

    def watchlist_rows(self) -> list[WatchlistRow]:
        return [WatchlistRow(symbol) for symbol in self.symbols]

    def add(self, symbol: str) -> None:
        self.added.append(symbol)
        if symbol not in self.symbols:
            self.symbols.append(symbol)

    def remove(self, symbol: str) -> None:
        self.removed.append(symbol)
        if symbol in self.symbols:
            self.symbols.remove(symbol)


def test_press_n_adds_symbol_from_tui() -> None:
    """``n`` opens the prompt; submitting a symbol persists it and shows the row."""

    async def scenario() -> None:
        from textual.widgets import DataTable

        store = FakeWatchlist()
        app = TsicApp(repo=store, watchlist_editor=store)
        async with app.run_test() as pilot:
            await pilot.press("n")
            await pilot.pause()
            await pilot.press("2", "3", "3", "0", "enter")
            await pilot.pause()
            assert store.added == ["2330"]
            table = pilot.app.query_one("#watchlist-table", DataTable)
            assert table.row_count == 1

    asyncio.run(scenario())


def test_press_d_removes_selected_symbol() -> None:
    """``d`` removes the cursor-selected symbol and redraws the table."""

    async def scenario() -> None:
        from textual.widgets import DataTable

        store = FakeWatchlist(("2330", "2317"))
        app = TsicApp(repo=store, watchlist_editor=store)
        async with app.run_test() as pilot:
            await pilot.press("d")
            await pilot.pause()
            assert store.removed == ["2330"]
            table = pilot.app.query_one("#watchlist-table", DataTable)
            assert table.row_count == 1

    asyncio.run(scenario())


def test_add_remove_are_noop_without_editor() -> None:
    """No editor injected: ``n`` opens no prompt and ``d`` removes nothing."""

    async def scenario() -> None:
        from textual.widgets import DataTable

        async with TsicApp(repo=_two_row_repo()).run_test() as pilot:
            await pilot.press("n")
            await pilot.pause()
            # No prompt screen was pushed over the watchlist.
            assert len(pilot.app.screen_stack) == 1
            await pilot.press("d")
            await pilot.pause()
            table = pilot.app.query_one("#watchlist-table", DataTable)
            assert table.row_count == 2

    asyncio.run(scenario())


# --- AC-3: "q" quits the app ------------------------------------------------


def test_press_q_quits_app() -> None:
    """AC-3: pressing ``q`` exits the app."""

    async def scenario() -> None:
        async with TsicApp(repo=FakeRepo([])).run_test() as pilot:
            await pilot.press("q")
            await pilot.pause()
            assert not pilot.app.is_running

    asyncio.run(scenario())


# --- AC-4: the fully-wired app launches headless without raising ------------


def test_build_app_launches_headless() -> None:
    """AC-4: ``build_app`` over a migrated DB runs under ``run_test()`` cleanly.

    Mirrors what ``tsic tui`` wires (StorageWatchlistSource + orchestrator +
    analyzer) but headless, since CI has no TTY. A tracked symbol with cached
    prices also exercises the storage-backed watchlist source.
    """

    async def scenario() -> None:
        conn = database.connect(":memory:")
        migrations.migrate(conn)
        WatchlistRepository(conn).add("2330")
        PriceRepository(conn).upsert_prices(
            [
                DailyPrice(
                    symbol="2330",
                    date="2026-06-13",
                    open=1000.0,
                    high=1010.0,
                    low=990.0,
                    close=1005.0,
                    volume=42,
                    source="fake",
                )
            ]
        )
        try:
            from datetime import date

            from textual.widgets import DataTable

            app = build_app(
                conn,
                today=date(2026, 6, 14),
                agent_command="cat",
                date_range=("2026-06-01", "2026-06-30"),
            )
            async with app.run_test() as pilot:
                table = pilot.app.query_one("#watchlist-table", DataTable)
                assert table.row_count == 1
        finally:
            conn.close()

    asyncio.run(scenario())
