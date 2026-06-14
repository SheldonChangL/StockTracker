"""Per-symbol data maintenance over the tsic database (Story 2.5).

The ``tsic db clean <symbol>`` workflow removes *all* of a symbol's stored
records so a user can wipe a polluted or unwanted series. A symbol's data is
spread across the three data tables defined in ``schema.sql``
(:data:`DATA_TABLES`); ``meta`` and ``watchlist`` are not per-symbol price data
and are deliberately left untouched.

Both helpers operate over an already-migrated :class:`sqlite3.Connection`
(conn-injection, matching :mod:`tsic.storage.repository`): the caller owns the
connection's lifecycle and schema setup.
"""

from __future__ import annotations

import sqlite3

#: Data tables keyed by ``symbol`` that ``db clean`` counts and clears.
DATA_TABLES = ("daily_prices", "chip_flows", "fundamentals")


def count_symbol_records(conn: sqlite3.Connection, symbol: str) -> int:
    """Return the total number of stored rows for ``symbol``.

    The count sums matching rows across every table in :data:`DATA_TABLES`, so
    it reflects exactly how many rows :func:`delete_symbol` would remove.

    Args:
        conn: An open, migrated SQLite connection.
        symbol: The symbol to count.

    Returns:
        The combined row count across all data tables (``0`` if none).
    """
    total = 0
    for table in DATA_TABLES:
        row = conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE symbol = ?", (symbol,)
        ).fetchone()
        total += row[0]
    return total


def delete_symbol(conn: sqlite3.Connection, symbol: str) -> int:
    """Delete every stored row for ``symbol`` and return how many were removed.

    Rows are deleted from all tables in :data:`DATA_TABLES` within a single
    committed transaction, so the wipe is atomic.

    Args:
        conn: An open, migrated SQLite connection.
        symbol: The symbol whose rows should be removed.

    Returns:
        The total number of rows deleted across all data tables.
    """
    deleted = 0
    for table in DATA_TABLES:
        cursor = conn.execute(
            f"DELETE FROM {table} WHERE symbol = ?", (symbol,)
        )
        deleted += cursor.rowcount
    conn.commit()
    return deleted
