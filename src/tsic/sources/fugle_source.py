"""Fugle market-data source (Story 3.5, §3 A3; FR-4/NFR-3).

Fugle is the *secondary* fallback price source — third in priority after the
preferred yfinance source (§3 A1) and the official TWSE fallback (§3 A2). It is
only reachable with an API key supplied through the environment
(``TSIC_FUGLE_API_KEY``), so unlike the other sources it can be *unavailable*:
when the key is unset the source still constructs (it is never fatal) but flags
itself via :attr:`available` so the orchestrator can skip it rather than crash
(AC-1).

As with yfinance and TWSE these are **raw, unadjusted** prices (``adjusted=0``)
so the cache never mixes adjusted and raw closes
(see :class:`~tsic.storage.repository.DataPollutionError`).

Fugle's historical-candles endpoint serves a whole date range in one request,
so no monthly/daily fan-out is needed; the parsed candles inside ``[from, to]``
are returned directly (AC-2).

Two collaborators are injected so the network call and the wall-clock sleep can
be driven deterministically in tests:

* ``fetch_fn`` — defaults to :func:`_http_get`; called with the request URL and
  the API key, and expected to return an object exposing ``status_code`` and
  ``json()`` (an :class:`httpx.Response`).
* ``sleep_fn`` — defaults to :func:`time.sleep`; used by the 429 backoff.

The per-source budget (``concurrency`` / ``rate_limit``) is configurable at
construction time (AC-3) so it can be tuned to whatever the deployed Fugle plan
permits; both default to a conservative value. As with the other sources the
shared :class:`~tsic.ratelimit.token_bucket.TokenBucket` is acquired before
*every* attempt so retries respect the same ceiling.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

import httpx

from tsic.models import ChipFlow, DailyPrice, Fundamental
from tsic.settings import fugle_api_key
from tsic.sources.base import BaseSource
from tsic.sources.yfinance_source import SourceFetchError

logger = logging.getLogger(__name__)

#: Fugle MarketData historical daily-candles endpoint.
_BASE_URL = "https://api.fugle.tw/marketdata/v1.0/stock/historical/candles"

#: Default per-source budget. ADR §3 A3 pins these to "whatever the plan allows"
#: rather than a fixed number, so they are conservative defaults overridable per
#: instance (AC-3).
_DEFAULT_CONCURRENCY = 3
_DEFAULT_RATE_LIMIT = 3.0

#: Maximum number of retries after the initial attempt when rate-limited (AC-3).
_MAX_RETRIES = 3

#: First backoff delay (seconds); doubled before each subsequent retry.
_INITIAL_BACKOFF = 1.0


def _http_get(url: str, api_key: str) -> httpx.Response:
    """Default network call: a GET carrying the Fugle ``X-API-KEY`` header."""
    return httpx.get(url, headers={"X-API-KEY": api_key}, timeout=30.0)


class FugleSource(BaseSource):
    """Secondary fallback OHLCV source backed by Fugle's historical-candles API.

    The source is *unavailable* (and skipped by the orchestrator) when no API
    key is configured; see :attr:`available` (AC-1).
    """

    name = "fugle"
    #: Secondary fallback — runs after yfinance (1) and TWSE (2) (§3 A3).
    priority = 3
    #: Class-level defaults satisfy the BaseSource contract; both are overridden
    #: per instance when explicit values are passed to ``__init__`` (AC-3).
    concurrency = _DEFAULT_CONCURRENCY
    rate_limit = _DEFAULT_RATE_LIMIT

    def __init__(
        self,
        *,
        api_key: str | None = None,
        concurrency: int | None = None,
        rate_limit: float | None = None,
        fetch_fn: Callable[[str, str], Any] = _http_get,
        sleep_fn: Callable[[float], object] = time.sleep,
    ) -> None:
        # Fall back to the environment key when none is injected; ``None`` here
        # is non-fatal and simply marks the source unavailable (AC-1).
        self._api_key = api_key if api_key is not None else fugle_api_key()
        if concurrency is not None:
            self.concurrency = concurrency
        if rate_limit is not None:
            self.rate_limit = rate_limit
        self._fetch_fn = fetch_fn
        self._sleep_fn = sleep_fn

    @property
    def available(self) -> bool:
        """Whether a Fugle API key is configured.

        ``False`` means the source could not authenticate; the orchestrator
        skips it rather than treating the missing key as a fatal error (AC-1).
        """
        return self._api_key is not None

    def fetch_prices(self, symbol: str, start: str, end: str) -> list[DailyPrice]:
        """Fetch raw OHLCV for ``symbol`` in ``[start, end]`` from Fugle.

        Args:
            symbol: Taiwan stock symbol, e.g. ``"2330"``.
            start: Inclusive ISO ``YYYY-MM-DD`` start date.
            end: Inclusive ISO ``YYYY-MM-DD`` end date.

        Returns:
            One :class:`~tsic.models.DailyPrice` per candle in range, each with
            ``adjusted=0`` and ``source="fugle"``.

        Raises:
            SourceFetchError: If the source is unavailable (no API key, AC-1) or
                the request stays rate-limited (429) after the full retry budget.
        """
        if not self.available:
            raise SourceFetchError(
                "fugle source unavailable: TSIC_FUGLE_API_KEY is not set"
            )

        url = (
            f"{_BASE_URL}/{symbol}"
            f"?from={start}&to={end}&fields=open,high,low,close,volume"
        )
        payload = self._fetch_json(url, f"{symbol} {start}..{end}")
        return _parse_prices(payload, symbol, start, end)

    def _fetch_json(self, url: str, context: str) -> Any:
        """GET ``url`` and return decoded JSON, retrying 429s with backoff (AC-3).

        The shared rate-limit bucket is acquired before *every* attempt so the
        configured per-source ceiling holds across retries too. ``context`` is a
        human-readable label used only for log lines.
        """
        assert self._api_key is not None  # guarded by available in callers.
        backoff = _INITIAL_BACKOFF
        for attempt in range(_MAX_RETRIES + 1):
            self.bucket.acquire()
            response = self._fetch_fn(url, self._api_key)
            status = getattr(response, "status_code", 200)
            if status != 429:
                return response.json()

            if attempt < _MAX_RETRIES:
                logger.warning(
                    "Fugle fetch for %s rate-limited (attempt %d/%d); "
                    "backing off %.0fs",
                    context,
                    attempt + 1,
                    _MAX_RETRIES + 1,
                    backoff,
                )
                self._sleep_fn(backoff)
                backoff *= 2  # double the backoff before each retry.

        raise SourceFetchError(
            f"Fugle fetch for {context} stayed rate-limited (429) "
            f"after {_MAX_RETRIES + 1} attempts"
        )

    def fetch_chips(self, symbol: str, start: str, end: str) -> list[ChipFlow]:
        """Not provided by this story; institutional flows come from TWSE."""
        raise NotImplementedError("fugle does not provide institutional flows")

    def fetch_fundamentals(
        self, symbol: str, start: str, end: str
    ) -> list[Fundamental]:
        """Not provided by this story; fundamentals come from other sources."""
        raise NotImplementedError("fugle fundamentals are out of scope")


def _parse_prices(payload: Any, symbol: str, start: str, end: str) -> list[DailyPrice]:
    """Convert a Fugle historical-candles payload into raw :class:`DailyPrice` rows.

    The payload's ``data`` array holds one object per trading day with ISO
    ``date`` and numeric OHLCV fields. Rows whose ``date`` falls outside
    ``[start, end]`` or whose required cells are missing/unparseable are skipped
    silently — never written, never raised (AC-2).

    Args:
        payload: The decoded JSON returned by the candles endpoint.
        symbol: The symbol these candles belong to.
        start: Inclusive ISO ``YYYY-MM-DD`` start date.
        end: Inclusive ISO ``YYYY-MM-DD`` end date.

    Returns:
        One :class:`DailyPrice` per in-range candle, ``adjusted=0`` and
        ``source="fugle"``, in ascending date order.
    """
    if not isinstance(payload, dict):
        return []
    rows = payload.get("data")
    if not isinstance(rows, list):
        return []

    prices: list[DailyPrice] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        date = row.get("date")
        if not isinstance(date, str) or not (start <= date <= end):
            continue
        try:
            price = DailyPrice(
                symbol=symbol,
                date=date,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=int(row["volume"]),
                source="fugle",
                adjusted=0,
            )
        except (KeyError, TypeError, ValueError):
            continue
        prices.append(price)

    prices.sort(key=lambda p: p.date)
    return prices
