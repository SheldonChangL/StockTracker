"""The root Textual application for tsic (Story 8.1, FR-26/FR-27).

:class:`TsicApp` is the interactive console's main screen: a header, a single
:class:`~textual.widgets.DataTable` (``id="watchlist-table"``) listing every
tracked symbol with its cached-data summary, and a footer. The table's columns
and rows come from an injected :class:`~tsic.tui.watchlist_view.WatchlistSource`
(the repository in production, a fake in tests), so the app holds no storage
logic of its own and stays trivially testable via ``run_test()`` (AC-3).

No bespoke colour system or theme is defined: the app relies on Textual's
default theme constants (AC-4).
"""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import DataTable, Footer, Header

from tsic.tui.watchlist_view import COLUMNS, WatchlistSource

#: Stable ``id`` for the watchlist table, used by both the app and its tests.
WATCHLIST_TABLE_ID = "watchlist-table"


class TsicApp(App):
    """Interactive console main screen listing the watchlist (AC-1)."""

    TITLE = "tsic"
    SUB_TITLE = "觀察清單"

    def __init__(self, repo: WatchlistSource) -> None:
        """Build the app over a watchlist data source.

        Args:
            repo: Supplies the rows the table renders (see
                :class:`~tsic.tui.watchlist_view.WatchlistSource`).
        """
        super().__init__()
        self._repo = repo

    def compose(self) -> ComposeResult:
        """Lay out the header, the watchlist table, and the footer."""
        yield Header()
        yield DataTable(id=WATCHLIST_TABLE_ID)
        yield Footer()

    def on_mount(self) -> None:
        """Populate the table's columns and rows from the data source."""
        table = self.query_one(f"#{WATCHLIST_TABLE_ID}", DataTable)
        table.add_columns(*COLUMNS)
        for row in self._repo.watchlist_rows():
            table.add_row(*row.cells())
