"""Presentation model for the watchlist table (Story 8.1, FR-26/FR-27).

This module owns the *data contract* the TUI renders, kept deliberately free of
any Textual widget so it can be unit-tested without a running app:

* :data:`COLUMNS` — the table's column headers, in display order. The
  :class:`~tsic.tui.app.TsicApp` and its tests both read this single source of
  truth so the header set never drifts from what is rendered (AC-1).
* :class:`WatchlistRow` — one display-ready row: a tracked symbol plus its
  cached-data summary. :meth:`WatchlistRow.cells` projects the row to the cell
  strings in :data:`COLUMNS` order, so the widget stays a dumb renderer.
* :func:`classify_freshness` — the pure rule mapping a symbol's latest stored
  date to a data-status label (AC-2). The freshness window is an explicit
  argument rather than a baked-in constant: the caller (a later wiring story)
  decides the policy; this prereq only defines the mapping.

A symbol's row is supplied by a :class:`WatchlistSource` (the repository in
production, a fake in tests), matching the conn/repo-injection style used across
the storage layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol, runtime_checkable

#: Status shown when the latest stored date is within the freshness window.
STATUS_FRESH = "新鮮"

#: Status shown when the latest stored date is older than the freshness window.
STATUS_STALE = "過期"

#: Status shown when the symbol has no stored data at all.
STATUS_MISSING = "缺失"

#: Placeholder cell for a value the symbol does not have yet (no cached data).
EMPTY_CELL = "—"

#: Column headers in display order (AC-1). Read by both the widget and tests.
COLUMNS: tuple[str, ...] = (
    "代號",
    "名稱",
    "最新收盤價",
    "最新日期",
    "資料筆數",
    "資料狀態",
)


def classify_freshness(
    latest_date: str | None,
    today: date,
    fresh_within_days: int,
) -> str:
    """Map a symbol's latest stored date to a data-status label (AC-2).

    Args:
        latest_date: The most recent stored ISO ``date`` for the symbol, or
            ``None``/empty when the symbol has no cached data.
        today: The reference "now" date the age is measured against (injected
            so the rule is deterministic and testable).
        fresh_within_days: Inclusive age, in days, still considered fresh. A
            symbol whose latest date is this many days old or fewer is fresh.

    Returns:
        :data:`STATUS_MISSING` when there is no data, :data:`STATUS_FRESH` when
        the latest date is within ``fresh_within_days`` of ``today``, otherwise
        :data:`STATUS_STALE`.
    """
    if not latest_date:
        return STATUS_MISSING

    age_days = (today - date.fromisoformat(latest_date)).days
    return STATUS_FRESH if age_days <= fresh_within_days else STATUS_STALE


@dataclass(frozen=True)
class WatchlistRow:
    """A display-ready watchlist row: a symbol plus its cached-data summary.

    Fields hold already-resolved display values so the widget only formats
    ``None`` into a placeholder; it never reaches back into storage.
    """

    symbol: str
    name: str | None = None
    latest_close: float | None = None
    latest_date: str | None = None
    row_count: int = 0
    status: str = STATUS_MISSING

    def cells(self) -> tuple[str, ...]:
        """Return this row's cell strings in :data:`COLUMNS` order.

        ``None`` values (a symbol with no cached data) render as
        :data:`EMPTY_CELL` rather than the literal text ``"None"``.
        """
        return (
            self.symbol,
            self.name or EMPTY_CELL,
            EMPTY_CELL if self.latest_close is None else f"{self.latest_close:g}",
            self.latest_date or EMPTY_CELL,
            str(self.row_count),
            self.status,
        )


@runtime_checkable
class WatchlistSource(Protocol):
    """Supplies the rows the watchlist table renders.

    Implemented by the storage repository in production and by a fake in tests;
    :class:`~tsic.tui.app.TsicApp` depends only on this method (AC-3).
    """

    def watchlist_rows(self) -> list[WatchlistRow]:
        """Return one :class:`WatchlistRow` per tracked symbol."""
        ...
