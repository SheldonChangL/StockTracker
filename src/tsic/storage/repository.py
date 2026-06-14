"""Repository over ``daily_prices`` for incremental, invariant-safe writes.

This layer sits on top of an open :class:`sqlite3.Connection` (produced by
:func:`tsic.storage.database.connect`) and owns the read/write access patterns
for OHLCV records (Story 2.4, FR-11/FR-12):

* **Incremental upsert** — re-running a fetch must never duplicate a row.
  Writes use ``INSERT OR IGNORE`` keyed on the ``(symbol, date)`` primary key,
  so the *first* write for a key wins and later writes are silently skipped
  rather than overwriting (AC-1).
* **Latest date** — :meth:`PriceRepository.latest_date` returns ``MAX(date)``
  for a symbol, or ``None`` when the symbol has no rows, so callers know where
  to resume an incremental fetch (AC-2).
* **adjusted/raw invariant** — a single symbol must never mix adjusted (1) and
  raw (0) prices, or its price basis becomes meaningless. Writes that would mix
  bases for a symbol are rejected with :class:`DataPollutionError` (AC-3).
* **Range query** — :meth:`PriceRepository.query_prices` returns rows for a
  symbol within an inclusive date range, ordered by ``date`` and served by the
  ``(symbol, date)`` index (AC-4).
"""

from __future__ import annotations

import sqlite3

from tsic.models import DailyPrice

#: Columns of ``daily_prices`` in DDL order (see ``schema.sql``).
_COLUMNS = (
    "symbol",
    "date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "source",
    "adjusted",
)

_INSERT_SQL = (
    "INSERT OR IGNORE INTO daily_prices "
    "(symbol, date, open, high, low, close, volume, source, adjusted) "
    "VALUES (:symbol, :date, :open, :high, :low, :close, :volume, :source, :adjusted)"
)


class DataPollutionError(Exception):
    """Raised when a write would mix adjusted and raw prices for one symbol.

    Mixing price bases (``adjusted`` 0 vs 1) under a single symbol makes the
    stored series internally inconsistent, so such writes are refused outright.
    """


class PriceRepository:
    """Read/write access to ``daily_prices`` over an open connection.

    The repository does not own the connection's lifecycle (opening, closing,
    or migrating the schema): the caller passes a connection that has already
    been migrated via :func:`tsic.storage.migrations.migrate`.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def upsert_prices(self, prices: list[DailyPrice]) -> int:
        """Insert price records, ignoring duplicate ``(symbol, date)`` keys.

        First-write-wins: a row whose ``(symbol, date)`` already exists is left
        untouched (``INSERT OR IGNORE``), so re-running a fetch is idempotent
        and never overwrites previously stored values.

        Before writing, the adjusted/raw invariant is enforced for every symbol
        in the batch (both within the batch and against rows already stored). If
        any symbol would end up mixing adjusted and raw prices, nothing is
        written and :class:`DataPollutionError` is raised.

        Args:
            prices: Records to persist. An empty list is a no-op.

        Returns:
            The number of rows actually inserted (duplicates skipped do not
            count).

        Raises:
            DataPollutionError: If a symbol would mix adjusted and raw prices.
        """
        if not prices:
            return 0

        self._check_adjusted_invariant(prices)

        cursor = self._conn.executemany(
            _INSERT_SQL, [self._as_params(price) for price in prices]
        )
        self._conn.commit()
        return cursor.rowcount

    def latest_date(self, symbol: str) -> str | None:
        """Return the most recent stored ``date`` for ``symbol``.

        Args:
            symbol: The symbol to look up.

        Returns:
            The maximum ISO ``date`` string for the symbol, or ``None`` if the
            symbol has no stored rows.
        """
        row = self._conn.execute(
            "SELECT MAX(date) FROM daily_prices WHERE symbol = ?", (symbol,)
        ).fetchone()
        return row[0] if row else None

    def query_prices(self, symbol: str, start: str, end: str) -> list[DailyPrice]:
        """Return a symbol's rows within ``[start, end]``, ordered by date.

        The range is inclusive on both ends. Results are ordered ascending by
        ``date`` and served by the ``(symbol, date)`` index.

        Args:
            symbol: The symbol to query.
            start: Inclusive lower bound ISO ``date`` string.
            end: Inclusive upper bound ISO ``date`` string.

        Returns:
            Matching :class:`~tsic.models.DailyPrice` records, ascending by date.
        """
        rows = self._conn.execute(
            "SELECT symbol, date, open, high, low, close, volume, source, adjusted "
            "FROM daily_prices "
            "WHERE symbol = ? AND date BETWEEN ? AND ? "
            "ORDER BY date ASC",
            (symbol, start, end),
        ).fetchall()
        return [DailyPrice(**dict(zip(_COLUMNS, row, strict=True))) for row in rows]

    def _check_adjusted_invariant(self, prices: list[DailyPrice]) -> None:
        """Reject the batch if any symbol would mix adjusted and raw prices."""
        incoming: dict[str, set[int]] = {}
        for price in prices:
            incoming.setdefault(price.symbol, set()).add(price.adjusted)

        for symbol, bases in incoming.items():
            stored = self._stored_adjusted(symbol)
            combined = bases | stored
            if len(combined) > 1:
                raise DataPollutionError(
                    f"symbol {symbol!r} would mix adjusted/raw prices "
                    f"(existing={sorted(stored)}, incoming={sorted(bases)}); "
                    "a symbol must use a single price basis"
                )

    def _stored_adjusted(self, symbol: str) -> set[int]:
        """Return the distinct ``adjusted`` flags already stored for ``symbol``."""
        rows = self._conn.execute(
            "SELECT DISTINCT adjusted FROM daily_prices WHERE symbol = ?", (symbol,)
        ).fetchall()
        return {row[0] for row in rows}

    @staticmethod
    def _as_params(price: DailyPrice) -> dict[str, object]:
        """Map a :class:`~tsic.models.DailyPrice` to named-bind parameters."""
        return {name: getattr(price, name) for name in _COLUMNS}
