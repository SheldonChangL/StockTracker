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
from textual.containers import VerticalScroll
from textual.message import Message
from textual.screen import Screen
from textual.widgets import (
    DataTable,
    Footer,
    Header,
    Input,
    Markdown,
    ProgressBar,
    Static,
)
from textual.worker import WorkerState

from tsic.fetching.orchestrator import FetchSummary
from tsic.tui.watchlist_view import COLUMNS, WatchlistSource

#: Stable ``id`` for the watchlist table, used by both the app and its tests.
WATCHLIST_TABLE_ID = "watchlist-table"

#: Stable ``id`` for the background-update progress bar (Story 8.3, AC-1).
PROGRESS_BAR_ID = "progress-bar"

#: Stable ``id`` for the one-line status banner under the table. It is the app's
#: single feedback surface: idle hint, empty-watchlist guidance, in-flight update
#: progress, and post-action results all render here so no action looks like a no-op.
STATUS_LABEL_ID = "status-line"

#: Shown when the watchlist is empty so the screen is never a blank, silent table.
EMPTY_WATCHLIST_HINT = "觀察清單是空的 — 先按 q 離開，執行 `tsic watch add <代號>` 加入股票後再回來。"


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


class WatchlistEditor(Protocol):
    """The write side of the watchlist, so symbols can be managed inside the TUI.

    Production wiring injects :class:`~tsic.storage.repository.WatchlistRepository`;
    tests inject a fake. Depending on this protocol (not the concrete repository)
    keeps :class:`TsicApp` decoupled from storage, matching the read-side
    :class:`~tsic.tui.watchlist_view.WatchlistSource` seam. When no editor is
    injected the ``n``/``d`` keys become no-ops.
    """

    def add(self, symbol: str) -> None:
        """Track ``symbol`` (idempotent)."""
        ...

    def remove(self, symbol: str) -> None:
        """Stop tracking ``symbol`` (a no-op when not tracked)."""
        ...


class AddSymbolScreen(Screen):
    """A modal prompt for a new watchlist symbol (the ``n`` key).

    Submitting the input dismisses the screen with the typed symbol; ``escape``
    cancels with no result. Keeping the prompt on its own screen means the main
    screen needs no always-present input widget and no custom CSS.
    """

    BINDINGS = [Binding("escape", "cancel", "取消")]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Input(placeholder="輸入股票代號，例如 2330", id="symbol-input")
        yield Footer()

    def on_mount(self) -> None:
        """Focus the input so the user can type immediately."""
        self.query_one("#symbol-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Dismiss with the trimmed symbol (or cancel when the field is blank)."""
        symbol = event.value.strip()
        self.dismiss(symbol or None)

    def action_cancel(self) -> None:
        """Close the prompt without adding anything."""
        self.dismiss(None)


class AnalysisScreen(Screen):
    """A full-screen, scrollable view of one symbol's AI analysis.

    Pressing ``a`` runs a blocking AI CLI whose output is otherwise invisible to
    the user; this screen renders that output as Markdown so the result of the
    action is actually seen. ``escape``/``q`` returns to the watchlist.
    """

    BINDINGS = [
        Binding("escape", "back", "返回"),
        Binding("q", "back", "返回"),
    ]

    def __init__(self, symbol: str, output: str) -> None:
        super().__init__()
        self._symbol = symbol
        self._output = output

    def compose(self) -> ComposeResult:
        yield Header()
        yield VerticalScroll(Markdown(f"# {self._symbol} 分析\n\n{self._output}"))
        yield Footer()

    def action_back(self) -> None:
        """Return to the watchlist screen."""
        self.app.pop_screen()


class TsicApp(App):
    """Interactive console main screen listing the watchlist (AC-1)."""

    TITLE = "tsic"
    SUB_TITLE = "觀察清單"

    #: Keyboard map (Story 8.3 ``u`` + Story 8.4 ``f``/``a``/``q``). ``f`` and
    #: ``a`` act on the row the watchlist cursor is on; ``u`` updates the whole
    #: injected batch; ``q`` quits (Textual's built-in ``action_quit``).
    BINDINGS = [
        Binding("n", "add_symbol", "新增"),
        Binding("d", "remove_symbol", "刪除"),
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
        watchlist_editor: WatchlistEditor | None = None,
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
        self._watchlist_editor = watchlist_editor
        #: The most recent :class:`AnalysisReady` message, or ``None`` until the
        #: first ``a`` run completes; lets a test assert the analysis arrived.
        self.last_analysis: TsicApp.AnalysisReady | None = None

    def compose(self) -> ComposeResult:
        """Lay out the header, the watchlist table, the status line, the bar, the footer."""
        yield Header()
        yield DataTable(id=WATCHLIST_TABLE_ID)
        yield Static(id=STATUS_LABEL_ID)
        yield ProgressBar(id=PROGRESS_BAR_ID, show_eta=False)
        yield Footer()

    def on_mount(self) -> None:
        """Populate the table and start in a clean, idle state (no fake loading).

        The progress bar is hidden until an update actually runs — left visible
        with no ``total`` it pulses indefinitely and reads as a stuck spinner.
        """
        self._populate_rows()
        self.query_one(f"#{PROGRESS_BAR_ID}", ProgressBar).display = False
        self._set_idle_status()

    def _populate_rows(self) -> None:
        """Fill the table's columns (once) and rows from the data source."""
        table = self.query_one(f"#{WATCHLIST_TABLE_ID}", DataTable)
        if not table.columns:
            table.add_columns(*COLUMNS)
        for row in self._repo.watchlist_rows():
            table.add_row(*row.cells())

    def _refresh_rows(self) -> None:
        """Re-read the data source and redraw the rows (after an update lands)."""
        self.query_one(f"#{WATCHLIST_TABLE_ID}", DataTable).clear()
        self._populate_rows()

    def _set_status(self, text: str) -> None:
        """Write the one-line status banner under the table."""
        self.query_one(f"#{STATUS_LABEL_ID}", Static).update(text)

    def _set_idle_status(self) -> None:
        """Show the empty-watchlist hint, or a brief ready line when there are rows."""
        table = self.query_one(f"#{WATCHLIST_TABLE_ID}", DataTable)
        if table.row_count == 0:
            self._set_status(EMPTY_WATCHLIST_HINT)
        else:
            self._set_status(f"追蹤 {table.row_count} 檔　·　a 分析　u 全部更新　f 更新選取")

    def action_update(self) -> None:
        """Update *every* injected symbol on a threaded worker (Story 8.3, ``u``).

        ``thread=True`` keeps the blocking batch fetch off the event loop so the
        UI stays responsive; ``exclusive`` collapses repeated triggers into one
        in-flight update. A no-op when no orchestrator/symbols were injected.
        """
        if not self._symbols:
            self._set_status(EMPTY_WATCHLIST_HINT)
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
        bar = self.query_one(f"#{PROGRESS_BAR_ID}", ProgressBar)
        bar.update(total=len(fetch_symbols), progress=0)
        bar.display = True
        self._set_status(f"更新中… 0/{len(fetch_symbols)}")
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
            self._set_status("找不到 AI CLI，無法分析（需安裝可用的 AI 指令）。")
            return
        symbol = self._selected_symbol()
        if symbol is None:
            return
        self._set_status(f"分析 {symbol} 中…")
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

    def action_add_symbol(self) -> None:
        """Prompt for a symbol and add it to the watchlist (the ``n`` key).

        Opens :class:`AddSymbolScreen`; :meth:`_on_symbol_entered` handles the
        result. A no-op (with a hint) when no watchlist editor was injected.
        """
        if self._watchlist_editor is None:
            self._set_status("此畫面未連接 watchlist 寫入，無法新增。")
            return
        self.push_screen(AddSymbolScreen(), self._on_symbol_entered)

    def _on_symbol_entered(self, symbol: str | None) -> None:
        """Persist the entered symbol, redraw, then fetch its data (Story: TUI add).

        The new symbol joins the batch ``u`` set and is fetched immediately so it
        does not linger as a 缺失 row the user would have to update by hand.
        """
        if symbol is None or self._watchlist_editor is None:
            return
        self._watchlist_editor.add(symbol)
        if symbol not in self._symbols:
            self._symbols.append(symbol)
        self._refresh_rows()
        self._set_status(f"已新增 {symbol}，抓取資料中…")
        self._start_fetch([symbol])

    def action_remove_symbol(self) -> None:
        """Remove the cursor-selected symbol from the watchlist (the ``d`` key).

        A no-op when no editor was injected or the watchlist is empty.
        """
        if self._watchlist_editor is None:
            self._set_status("此畫面未連接 watchlist 寫入，無法刪除。")
            return
        symbol = self._selected_symbol()
        if symbol is None:
            return
        self._watchlist_editor.remove(symbol)
        if symbol in self._symbols:
            self._symbols.remove(symbol)
        self._refresh_rows()
        self._set_status(f"已刪除 {symbol}")

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
        """Advance the progress bar and status line from a worker event (AC-3)."""
        bar = self.query_one(f"#{PROGRESS_BAR_ID}", ProgressBar)
        bar.update(total=message.total, progress=message.completed)
        self._set_status(f"更新中… {message.completed}/{message.total}")

    def on_tsic_app_analysis_ready(self, message: TsicApp.AnalysisReady) -> None:
        """Store the latest AI analysis (AC-2) and show it on a scrollable screen."""
        self.last_analysis = message
        self._set_status(f"{message.symbol} 分析完成")
        self.push_screen(AnalysisScreen(message.symbol, message.output))

    def on_worker_state_changed(self, event: object) -> None:
        """When a background update finishes, redraw the table with the new data.

        Without this the table keeps showing pre-fetch values and ``u``/``f`` look
        like no-ops. The analyze worker reports its result via a message instead,
        so only the ``update`` group refreshes rows here.
        """
        worker = getattr(event, "worker", None)
        state = getattr(event, "state", None)
        if worker is None or state is not WorkerState.SUCCESS:
            return
        if worker.group == "update":
            self._refresh_rows()
            self._set_status("更新完成 ✓")
