"""The root Textual application for tsic (Story 8.1/8.3, FR-26/FR-27/FR-30).

:class:`TsicApp` is the interactive console's main screen: a header, a single
:class:`~textual.widgets.DataTable` (``id="watchlist-table"``) listing every
tracked symbol with its cached-data summary, a :class:`~textual.widgets.ProgressBar`
(``id="progress-bar"``) for background updates, and a footer. The table's columns
and rows come from an injected :class:`~tsic.tui.watchlist_view.WatchlistSource`
(the repository in production, a fake in tests), so the app holds no storage
logic of its own and stays trivially testable via ``run_test()`` (AC-3).

**Non-blocking updates (Story 8.3).** Triggering an update (the ``u`` binding or
:meth:`TsicApp.action_update`) runs the injected orchestrator on a *threaded*
worker via ``run_worker(thread=True)`` so the main event loop keeps handling
input while a long batch fetch runs (AC-1, AC-2). The worker reports progress
through the orchestrator's ``progress`` callback, posting a :class:`TsicApp.UpdateProgress`
message back onto the app thread; :meth:`TsicApp.on_tsic_app_update_progress`
advances the progress bar so its value is observable from a test (AC-3).

**Keyboard-driven operation (Story 8.4, FR-29).** Three bindings drive the whole
flow from one screen: ``f`` updates the *selected* watchlist row on the same
threaded worker as the batch ``u`` update (AC-1); ``a`` runs the injected
:class:`Analyzer` for the selected symbol on a worker and posts the result back
as an :class:`TsicApp.AnalysisReady` message (AC-2); ``q`` quits the app (AC-3).
Both the orchestrator and the analyzer are injected, so the key paths are real
yet driven against fakes in tests.

No bespoke colour system or theme is defined: the app relies on Textual's
default theme constants (AC-4).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.message import Message
from textual.widgets import DataTable, Footer, Header, ProgressBar

from tsic.fetching.orchestrator import FetchSummary
from tsic.tui.watchlist_view import COLUMNS, WatchlistSource

#: Stable ``id`` for the watchlist table, used by both the app and its tests.
WATCHLIST_TABLE_ID = "watchlist-table"

#: Stable ``id`` for the background-update progress bar (Story 8.3, AC-1).
PROGRESS_BAR_ID = "progress-bar"


class UpdateRunner(Protocol):
    """The slice of :class:`~tsic.fetching.orchestrator.FetchOrchestrator` the
    update worker needs: a batch fetch that reports per-symbol progress.

    Depending on a protocol (not the concrete orchestrator) keeps the app
    decoupled and lets tests inject a slow source through a real orchestrator.
    """

    def fetch_prices(
        self,
        symbols: Sequence[str],
        start: str,
        end: str,
        *,
        progress: object | None = ...,
    ) -> FetchSummary:
        """Fetch ``[start, end]`` for every symbol, calling ``progress(done, total)``."""
        ...


class Analyzer(Protocol):
    """Turns a symbol into an AI analysis string (Story 8.4, AC-2).

    Production wiring composes the cache read, the Markdown formatter, the
    default analysis prompt, and the AI-CLI pipe behind this single method (see
    :class:`tsic.tui.launcher.CacheAnalyzer`); tests inject a fake that records
    the call. Depending on this protocol keeps :class:`TsicApp` decoupled from
    the analysis pipeline while still exercising the ``a`` key end to end.
    """

    def analyze(self, symbol: str) -> str:
        """Return the AI analysis for ``symbol`` (blocking; run on a worker)."""
        ...


class TsicApp(App):
    """Interactive console main screen listing the watchlist (AC-1)."""

    TITLE = "tsic"
    SUB_TITLE = "觀察清單"

    #: Keyboard map (Story 8.3 ``u`` + Story 8.4 ``f``/``a``/``q``). ``f`` and
    #: ``a`` act on the row the watchlist cursor is on; ``u`` updates the whole
    #: injected batch; ``q`` quits (Textual's built-in ``action_quit``).
    BINDINGS = [
        Binding("f", "fetch_selected", "更新選取"),
        Binding("a", "analyze_selected", "分析"),
        Binding("u", "update", "全部更新"),
        Binding("q", "quit", "結束"),
    ]

    class UpdateProgress(Message):
        """Per-symbol progress posted from the threaded update worker (AC-3).

        Carries how many symbols have finished (``completed``) out of the batch
        ``total``. It is posted via :meth:`~textual.message_pump.MessagePump.post_message`
        so the worker thread never touches a widget directly.
        """

        def __init__(self, completed: int, total: int) -> None:
            super().__init__()
            self.completed = completed
            self.total = total

    class AnalysisReady(Message):
        """The AI analysis for a symbol, posted from the threaded ``a`` worker.

        Carries the analysed ``symbol`` and the AI CLI's ``output`` so the
        result reaches the app thread without the worker touching a widget; the
        latest one is stored on :attr:`TsicApp.last_analysis` (AC-2).
        """

        def __init__(self, symbol: str, output: str) -> None:
            super().__init__()
            self.symbol = symbol
            self.output = output

    def __init__(
        self,
        repo: WatchlistSource,
        *,
        orchestrator: UpdateRunner | None = None,
        symbols: Sequence[str] | None = None,
        date_range: tuple[str, str] | None = None,
        analyzer: Analyzer | None = None,
    ) -> None:
        """Build the app over a watchlist data source.

        Args:
            repo: Supplies the rows the table renders (see
                :class:`~tsic.tui.watchlist_view.WatchlistSource`).
            orchestrator: Optional batch fetcher run by the update worker. When
                ``None`` the update / fetch-selected actions are no-ops (Story
                8.1 keeps working without an orchestrator).
            symbols: Symbols the batch ``u`` update worker fetches.
            date_range: Inclusive ``(start, end)`` ISO dates for the fetch.
            analyzer: Optional analysis seam run by the ``a`` worker (Story 8.4,
                AC-2). When ``None`` the analyze action is a no-op.
        """
        super().__init__()
        self._repo = repo
        self._orchestrator = orchestrator
        self._symbols = list(symbols or [])
        self._date_range = date_range
        self._analyzer = analyzer
        #: The most recent :class:`AnalysisReady` message, or ``None`` until the
        #: first ``a`` run completes; lets a test assert the analysis arrived.
        self.last_analysis: TsicApp.AnalysisReady | None = None

    def compose(self) -> ComposeResult:
        """Lay out the header, the watchlist table, the progress bar, the footer."""
        yield Header()
        yield DataTable(id=WATCHLIST_TABLE_ID)
        yield ProgressBar(id=PROGRESS_BAR_ID, show_eta=False)
        yield Footer()

    def on_mount(self) -> None:
        """Populate the table's columns and rows from the data source."""
        table = self.query_one(f"#{WATCHLIST_TABLE_ID}", DataTable)
        table.add_columns(*COLUMNS)
        for row in self._repo.watchlist_rows():
            table.add_row(*row.cells())

    def action_update(self) -> None:
        """Update *every* injected symbol on a threaded worker (Story 8.3, ``u``).

        ``thread=True`` keeps the blocking batch fetch off the event loop so the
        UI stays responsive; ``exclusive`` collapses repeated triggers into one
        in-flight update. A no-op when no orchestrator/symbols were injected.
        """
        if not self._symbols:
            return
        self._start_fetch(self._symbols)

    def action_fetch_selected(self) -> None:
        """Update only the cursor-selected watchlist row (Story 8.4, ``f``, AC-1).

        Reads the symbol under the table cursor and runs the same threaded
        update worker as :meth:`action_update`, but for that one symbol. A no-op
        when no orchestrator was injected or the watchlist is empty.
        """
        symbol = self._selected_symbol()
        if symbol is None:
            return
        self._start_fetch([symbol])

    def _start_fetch(self, symbols: Sequence[str]) -> None:
        """Launch the threaded fetch worker for ``symbols`` (shared by ``u``/``f``).

        No-op unless an orchestrator and a date range were injected; ``exclusive``
        in the ``update`` group means a new trigger replaces any in-flight one.
        """
        if self._orchestrator is None or self._date_range is None:
            return
        fetch_symbols = list(symbols)
        self.run_worker(
            lambda: self._fetch(fetch_symbols),
            thread=True,
            exclusive=True,
            group="update",
        )

    def _fetch(self, symbols: Sequence[str]) -> FetchSummary:
        """Worker body (runs on a thread): drive the orchestrator with progress.

        The orchestrator's ``progress`` callback fires on this worker thread, so
        it must not mutate widgets directly; instead it posts an
        :class:`UpdateProgress` message back onto the app thread.
        """
        assert self._orchestrator is not None and self._date_range is not None
        start, end = self._date_range

        def report(completed: int, total: int) -> None:
            self.post_message(self.UpdateProgress(completed, total))

        return self._orchestrator.fetch_prices(symbols, start, end, progress=report)

    def action_analyze_selected(self) -> None:
        """Analyse the cursor-selected symbol on a worker (Story 8.4, ``a``, AC-2).

        Runs the injected :class:`Analyzer` (which uses the default analysis
        question) off the event loop and posts its output back as an
        :class:`AnalysisReady` message. A no-op when no analyzer was injected or
        the watchlist is empty.
        """
        if self._analyzer is None:
            return
        symbol = self._selected_symbol()
        if symbol is None:
            return
        self.run_worker(
            lambda: self._run_analyze(symbol),
            thread=True,
            exclusive=True,
            group="analyze",
        )

    def _run_analyze(self, symbol: str) -> str:
        """Worker body (runs on a thread): analyse ``symbol`` and post the result."""
        assert self._analyzer is not None
        output = self._analyzer.analyze(symbol)
        self.post_message(self.AnalysisReady(symbol, output))
        return output

    def _selected_symbol(self) -> str | None:
        """Return the symbol under the watchlist cursor, or ``None`` when empty.

        The symbol is the first cell (代號) of the cursor row; an empty watchlist
        has no selectable row, so ``f``/``a`` become no-ops.
        """
        table = self.query_one(f"#{WATCHLIST_TABLE_ID}", DataTable)
        if table.row_count == 0:
            return None
        return str(table.get_row_at(table.cursor_row)[0])

    def on_tsic_app_update_progress(self, message: TsicApp.UpdateProgress) -> None:
        """Advance the progress bar from a worker progress event (AC-3)."""
        bar = self.query_one(f"#{PROGRESS_BAR_ID}", ProgressBar)
        bar.update(total=message.total, progress=message.completed)

    def on_tsic_app_analysis_ready(self, message: TsicApp.AnalysisReady) -> None:
        """Store the latest AI analysis so it is observable from a test (AC-2)."""
        self.last_analysis = message
