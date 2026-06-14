"""yfinance market-data source (Story 3.2, ADR-3; FR-4/FR-5/FR-6).

yfinance is the *preferred* (lowest-priority-number) price source: when it is
healthy it returns ~5 years of OHLCV in one fast call. We download **raw,
unadjusted** prices (``auto_adjust=False``) so the cache stores the same
price basis everywhere — ``adjusted=0`` — and never silently mixes adjusted
and raw closes (see :class:`~tsic.storage.repository.DataPollutionError`).

Two collaborators are injected so the network call and the wall-clock sleep can
be driven deterministically in tests:

* ``download_fn`` — defaults to :func:`yfinance.download`; called with
  ``auto_adjust=False`` and ``threads=False`` (AC-1).
* ``sleep_fn`` — defaults to :func:`time.sleep`; used by the retry backoff.

On a transient upstream error the fetch is retried up to three times with an
exponential ``1s → 2s → 4s`` backoff; if the fourth attempt still fails the
source gives up and raises :class:`SourceFetchError` (AC-3).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

import yfinance

from tsic.models import ChipFlow, DailyPrice, Fundamental
from tsic.sources.base import BaseSource

logger = logging.getLogger(__name__)

#: Backoff delays (seconds) applied *before* each retry. Its length therefore
#: fixes the retry budget: 3 retries (4 attempts total) at 1s → 2s → 4s (AC-3).
_BACKOFF_SCHEDULE: tuple[float, ...] = (1.0, 2.0, 4.0)


class SourceFetchError(Exception):
    """Raised when a source exhausts its retry budget without succeeding."""


class YfinanceSource(BaseSource):
    """Preferred OHLCV source backed by yfinance, fetching raw (unadjusted) prices."""

    name = "yfinance"
    #: Preferred source — lowest priority number runs first (ADR-3, §3 A1).
    priority = 1
    #: AC-4: at most five simultaneous in-flight requests for this source.
    concurrency = 5
    #: Request ceiling sizing the shared token bucket. ADR-3 does not pin a
    #: yfinance-specific value; we mirror ``concurrency`` as a conservative
    #: default. Adjust here if the ADR later specifies a tighter ceiling.
    rate_limit = 5.0

    def __init__(
        self,
        *,
        download_fn: Callable[..., Any] = yfinance.download,
        sleep_fn: Callable[[float], object] = time.sleep,
    ) -> None:
        self._download_fn = download_fn
        self._sleep_fn = sleep_fn

    def fetch_prices(self, symbol: str, start: str, end: str) -> list[DailyPrice]:
        """Fetch raw OHLCV for ``symbol`` in ``[start, end]`` via yfinance.

        Args:
            symbol: Taiwan stock symbol, e.g. ``"2330"``.
            start: Inclusive ISO ``YYYY-MM-DD`` start date.
            end: Inclusive ISO ``YYYY-MM-DD`` end date.

        Returns:
            One :class:`~tsic.models.DailyPrice` per trading day, each with
            ``adjusted=0`` and ``source="yfinance"``.

        Raises:
            SourceFetchError: If the download fails on every attempt (AC-3).
        """
        # A bare Taiwan code maps to two possible Yahoo tickers — ``.TW``
        # (listed/TWSE) and ``.TWO`` (OTC/TPEx) — and the code alone can't tell
        # them apart. Try each in turn and keep the first that returns data.
        for yahoo_symbol in _yahoo_candidates(symbol):
            frame = self._download_with_retry(yahoo_symbol, start, end)
            prices = _parse_prices(frame, symbol)
            if prices:
                return prices
        return []

    def _download_with_retry(self, symbol: str, start: str, end: str) -> Any:
        """Call ``download_fn`` with raw-price flags, retrying with backoff (AC-3)."""
        last_error: Exception | None = None
        # One initial attempt plus one retry per backoff delay.
        for attempt in range(len(_BACKOFF_SCHEDULE) + 1):
            try:
                return self._download_fn(
                    symbol,
                    start=start,
                    end=end,
                    auto_adjust=False,  # AC-1: keep raw, unadjusted prices.
                    threads=False,  # AC-1: deterministic single-threaded fetch.
                )
            except Exception as error:  # noqa: BLE001 — upstream errors are opaque.
                last_error = error
                if attempt < len(_BACKOFF_SCHEDULE):
                    delay = _BACKOFF_SCHEDULE[attempt]
                    logger.warning(
                        "yfinance fetch for %s failed (attempt %d/%d): %s; "
                        "retrying in %.0fs",
                        symbol,
                        attempt + 1,
                        len(_BACKOFF_SCHEDULE) + 1,
                        error,
                        delay,
                    )
                    self._sleep_fn(delay)

        raise SourceFetchError(
            f"yfinance fetch for {symbol} failed after "
            f"{len(_BACKOFF_SCHEDULE) + 1} attempts"
        ) from last_error

    def fetch_chips(self, symbol: str, start: str, end: str) -> list[ChipFlow]:
        """Not supported by yfinance; institutional flows come from other sources."""
        raise NotImplementedError("yfinance does not provide institutional flows")

    def fetch_fundamentals(
        self, symbol: str, start: str, end: str
    ) -> list[Fundamental]:
        """Not supported by this story; fundamentals come from other sources."""
        raise NotImplementedError("yfinance fundamentals are out of scope")


def _yahoo_candidates(symbol: str) -> list[str]:
    """Yahoo Finance tickers to try, in order, for a Taiwan stock ``symbol``.

    Yahoo keys Taiwan stocks under a market suffix the bare code lacks: ``.TW``
    for listed (TWSE) and ``.TWO`` for OTC (TPEx). A bare numeric code returns
    no data and looks "delisted", and the code alone can't tell the two markets
    apart — so we return both, listed first. A symbol that already carries a
    suffix (``2330.TW``, ``2330.TWO``) or is non-numeric (foreign tickers) is
    used as-is. The stored ``DailyPrice.symbol`` keeps the original bare code —
    this mapping affects only the download call.
    """
    if symbol.isdigit():
        return [f"{symbol}.TW", f"{symbol}.TWO"]
    return [symbol]


def _parse_prices(frame: Any, symbol: str) -> list[DailyPrice]:
    """Convert a yfinance OHLCV DataFrame into raw :class:`DailyPrice` records.

    yfinance indexes rows by trading date and may return either flat columns
    (``Open``/``High``/…) or a per-symbol :class:`pandas.MultiIndex`; we flatten
    the latter to its first level so a single-symbol frame parses uniformly.

    Args:
        frame: The DataFrame returned by ``yfinance.download``.
        symbol: The symbol these rows belong to (yfinance does not echo it).

    Returns:
        One :class:`DailyPrice` per row, ``adjusted=0`` and ``source="yfinance"``,
        in the frame's row order.
    """
    if frame is None or getattr(frame, "empty", True):
        return []

    columns = frame.columns
    if getattr(columns, "nlevels", 1) > 1:
        frame = frame.copy()
        frame.columns = columns.get_level_values(0)

    prices: list[DailyPrice] = []
    for index, row in frame.iterrows():
        prices.append(
            DailyPrice(
                symbol=symbol,
                date=_format_date(index),
                open=float(row["Open"]),
                high=float(row["High"]),
                low=float(row["Low"]),
                close=float(row["Close"]),
                volume=int(row["Volume"]),
                source="yfinance",
                adjusted=0,
            )
        )
    return prices


def _format_date(index_value: Any) -> str:
    """Render a yfinance row index (a Timestamp or date) as ISO ``YYYY-MM-DD``."""
    strftime = getattr(index_value, "strftime", None)
    if strftime is not None:
        return strftime("%Y-%m-%d")
    return str(index_value)
