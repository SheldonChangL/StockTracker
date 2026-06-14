"""Read-only database overview for ``tsic db status`` (Story 2.6).

Aggregates the local cache into a small, presentation-agnostic summary: how
many distinct symbols are tracked and, for each, the most recent stored data
date. "Tracked" spans every per-symbol data table in
:data:`tsic.storage.maintenance.DATA_TABLES`, so a symbol with only chip or
fundamental rows still counts; the latest date is the newest ``date`` across
all of those tables. The helper is read-only and operates over an already
migrated connection (conn-injection, matching the rest of the storage layer).
"""

from __future__ import annotations

import sqlite3

from tsic.storage.maintenance import DATA_TABLES

#: One ``SELECT symbol, date`` per data table, unioned into a single stream.
_SYMBOL_DATES_SQL = " UNION ALL ".join(
    f"SELECT symbol, date FROM {table}" for table in DATA_TABLES
)


def symbol_latest_dates(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    """Return ``(symbol, latest_date)`` pairs, ordered by symbol.

    A symbol's latest date is the maximum ``date`` across every data table.
    Symbols are sorted ascending so the output order is deterministic.

    Args:
        conn: An open, migrated SQLite connection.

    Returns:
        A list of ``(symbol, latest_date)`` tuples (empty if no data exists).
    """
    rows = conn.execute(
        f"SELECT symbol, MAX(date) FROM ({_SYMBOL_DATES_SQL}) "
        "GROUP BY symbol ORDER BY symbol ASC"
    ).fetchall()
    return [(row[0], row[1]) for row in rows]
