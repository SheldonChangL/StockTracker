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


class TsicApp(App):
    """Interactive console main screen listing the watchlist (AC-1)."""

    TITLE = "tsic"
    SUB_TITLE = "觀察清單"

    #: ``u`` triggers a non-blocking background update (Story 8.3, AC-1/AC-2).
    BINDINGS = [Binding("u", "update", "更新")]

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

    def __init__(
        self,
        repo: WatchlistSource,
        *,
        orchestrator: UpdateRunner | None = None,
        symbols: Sequence[str] | None = None,
        date_range: tuple[str, str] | None = None,
    ) -> None:
        """Build the app over a watchlist data source.

        Args:
            repo: Supplies the rows the table renders (see
                :class:`~tsic.tui.watchlist_view.WatchlistSource`).
            orchestrator: Optional batch fetcher run by the update worker. When
                ``None`` the update action is a no-op (Story 8.1 keeps working
                without an orchestrator).
            symbols: Symbols the update worker fetches.
            date_range: Inclusive ``(start, end)`` ISO dates for the fetch.
        """
        super().__init__()
        self._repo = repo
        self._orchestrator = orchestrator
        self._symbols = list(symbols or [])
        self._date_range = date_range

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
        """Run the injected orchestrator on a threaded worker (AC-1, AC-2).

        ``thread=True`` keeps the blocking batch fetch off the event loop so the
        UI stays responsive; ``exclusive`` collapses repeated triggers into one
        in-flight update. A no-op when no orchestrator/symbols were injected.
        """
        if self._orchestrator is None or not self._symbols or self._date_range is None:
            return
        self.run_worker(self._run_update, thread=True, exclusive=True, group="update")

    def _run_update(self) -> FetchSummary:
        """Worker body (runs on a thread): drive the orchestrator with progress.

        The orchestrator's ``progress`` callback fires on this worker thread, so
        it must not mutate widgets directly; instead it posts an
        :class:`UpdateProgress` message back onto the app thread.
        """
        assert self._orchestrator is not None and self._date_range is not None
        start, end = self._date_range

        def report(completed: int, total: int) -> None:
            self.post_message(self.UpdateProgress(completed, total))

        return self._orchestrator.fetch_prices(
            self._symbols, start, end, progress=report
        )

    def on_tsic_app_update_progress(self, message: TsicApp.UpdateProgress) -> None:
        """Advance the progress bar from a worker progress event (AC-3)."""
        bar = self.query_one(f"#{PROGRESS_BAR_ID}", ProgressBar)
        bar.update(total=message.total, progress=message.completed)
