"""TWSE official daily-K source (Story 3.3, ADR-4; FR-4/FR-5/NFR-13).

TWSE is the *fallback* price source (§3 A2): when the preferred yfinance source
is unhealthy we fetch raw daily OHLCV straight from the exchange's official
``STOCK_DAY`` endpoint, so the cache can always be backed by an authoritative
source. As with yfinance these are **raw, unadjusted** prices (``adjusted=0``)
so the cache never mixes adjusted and raw closes.

``STOCK_DAY`` only serves **one calendar month per request**, so a multi-month
fetch is split into one request per month, each parameterised by the first day
of that month (``date=YYYYMM01``). Requests are issued one at a time
(``concurrency=1``) and throttled to ``1 req/s`` through the per-source shared
:class:`~tsic.ratelimit.token_bucket.TokenBucket` (AC-4) — TWSE bans clients
that exceed its budget.

Two collaborators are injected so the network call and the wall-clock sleep can
be driven deterministically in tests:

* ``fetch_fn`` — defaults to :func:`_http_get`; called with the fully built
  request URL and expected to return an object exposing ``status_code`` and
  ``json()`` (an :class:`httpx.Response`).
* ``sleep_fn`` — defaults to :func:`time.sleep`; used by the 429 backoff.

On an HTTP 429 the request is retried up to three times with a *doubling*
``1s → 2s → 4s`` backoff; if the fourth attempt is still rate-limited the source
gives up and raises :class:`~tsic.sources.yfinance_source.SourceFetchError`
(AC-3). The shared bucket is acquired before every attempt, so even the retries
respect the ``1 req/s`` ceiling.

The same source also serves institutional net-flows (籌碼面, Story 3.4) from the
official ``T86`` (三大法人買賣超) report. Unlike ``STOCK_DAY``, ``T86`` is a
*cross-sectional daily* report: one request returns every symbol's flows for a
single trading day, so a date range is fetched as one request **per calendar
day** (``date=YYYYMMDD``), each filtered down to the requested symbol. Days with
no report (weekends, holidays, or a symbol absent from that day's data) are
skipped silently — never written, never raised (AC-2). Chip fetches share the
exact same per-source bucket and retry path as prices, so the ``1 req/s`` /
``concurrency=1`` budget is honoured across both (AC-3).
"""

from __future__ import annotations

import datetime
import logging
import time
from collections.abc import Callable, Iterator
from typing import Any

import httpx

from tsic.models import ChipFlow, DailyPrice, Fundamental
from tsic.sources.base import BaseSource
from tsic.sources.yfinance_source import SourceFetchError

logger = logging.getLogger(__name__)

#: Official monthly daily-quote endpoint (JSON variant).
_BASE_URL = "https://www.twse.com.tw/exchangeReport/STOCK_DAY"

#: Official daily institutional net-flow (三大法人買賣超) endpoint (JSON variant).
_T86_URL = "https://www.twse.com.tw/fund/T86"

#: ``T86`` column labels mapped to the :class:`ChipFlow` fields they fill. Each
#: field lists the accepted header(s); when more than one is present in a row
#: their values are *summed* (TWSE splits 外資/自營商 into sub-columns in the
#: modern format but kept a single aggregate column in the legacy one).
_FOREIGN_FIELDS = (
    "外資買賣超股數",  # legacy aggregate column
    "外陸資買賣超股數(不含外資自營商)",  # modern: foreign ex-dealer ...
    "外資自營商買賣超股數",  # ... plus foreign-dealer leg
)
_TRUST_FIELDS = ("投信買賣超股數",)
_DEALER_FIELDS = (
    "自營商買賣超股數",  # legacy/modern aggregate column
    "自營商買賣超股數(自行買賣)",  # modern: proprietary ...
    "自營商買賣超股數(避險)",  # ... plus hedging leg
)

#: Maximum number of retries after the initial attempt when rate-limited (AC-3).
_MAX_RETRIES = 3

#: First backoff delay (seconds); doubled before each subsequent retry (AC-3).
_INITIAL_BACKOFF = 1.0

#: Difference between a Gregorian year and a Republic-of-China (民國) year.
_ROC_YEAR_OFFSET = 1911


def _http_get(url: str) -> httpx.Response:
    """Default network call: a plain GET with a conservative timeout."""
    return httpx.get(url, timeout=30.0)


class TwseSource(BaseSource):
    """Fallback OHLCV source backed by TWSE's official ``STOCK_DAY`` endpoint."""

    name = "twse"
    #: Fallback source — runs after the preferred yfinance source (§3 A2).
    priority = 2
    #: AC-4: TWSE is fetched strictly one request at a time.
    concurrency = 1
    #: AC-4: TWSE budget is one request per second; sizes the shared bucket.
    rate_limit = 1.0

    def __init__(
        self,
        *,
        fetch_fn: Callable[[str], Any] = _http_get,
        sleep_fn: Callable[[float], object] = time.sleep,
    ) -> None:
        self._fetch_fn = fetch_fn
        self._sleep_fn = sleep_fn

    def fetch_prices(self, symbol: str, start: str, end: str) -> list[DailyPrice]:
        """Fetch raw OHLCV for ``symbol`` in ``[start, end]`` from TWSE.

        Issues one ``STOCK_DAY`` request per calendar month spanned by the range
        (AC-1) and concatenates the parsed rows that fall inside ``[start, end]``.

        Args:
            symbol: Taiwan stock symbol, e.g. ``"2330"``.
            start: Inclusive ISO ``YYYY-MM-DD`` start date.
            end: Inclusive ISO ``YYYY-MM-DD`` end date.

        Returns:
            One :class:`~tsic.models.DailyPrice` per trading day in range, each
            with ``adjusted=0`` and ``source="twse"``.

        Raises:
            SourceFetchError: If any month stays rate-limited (429) after the
                full retry budget (AC-3).
        """
        prices: list[DailyPrice] = []
        for year, month in _months_in_range(start, end):
            payload = self._fetch_month(symbol, year, month)
            prices.extend(_parse_prices(payload, symbol, start, end))
        return prices

    def _fetch_month(self, symbol: str, year: int, month: int) -> Any:
        """Fetch one month's ``STOCK_DAY`` payload (retries 429s, AC-3)."""
        url = f"{_BASE_URL}?response=json&date={year}{month:02d}01&stockNo={symbol}"
        return self._fetch_json(url, f"{symbol} {year}{month:02d}")

    def _fetch_json(self, url: str, context: str) -> Any:
        """GET ``url`` and return decoded JSON, retrying 429s with backoff (AC-3).

        The shared rate-limit bucket is acquired before *every* attempt so the
        ``1 req/s`` ceiling holds across retries too (AC-3). ``context`` is a
        human-readable label (e.g. ``"2330 202606"``) used only for log lines.
        """
        backoff = _INITIAL_BACKOFF
        for attempt in range(_MAX_RETRIES + 1):
            self.bucket.acquire()
            response = self._fetch_fn(url)
            status = getattr(response, "status_code", 200)
            if status != 429:
                return response.json()

            if attempt < _MAX_RETRIES:
                logger.warning(
                    "TWSE fetch for %s rate-limited (attempt %d/%d); backing off %.0fs",
                    context,
                    attempt + 1,
                    _MAX_RETRIES + 1,
                    backoff,
                )
                self._sleep_fn(backoff)
                backoff *= 2  # AC-3: double the backoff before each retry.

        raise SourceFetchError(
            f"TWSE fetch for {context} stayed rate-limited (429) "
            f"after {_MAX_RETRIES + 1} attempts"
        )

    def fetch_chips(self, symbol: str, start: str, end: str) -> list[ChipFlow]:
        """Fetch institutional net-flows for ``symbol`` in ``[start, end]`` (T86).

        ``T86`` is a per-day cross-sectional report, so this issues one request
        per calendar day in range (AC-3 shared bucket throttles them to 1 req/s)
        and keeps only the row matching ``symbol``. Days with no report — a
        non-``OK`` payload (weekend/holiday) or a day whose data omits ``symbol``
        — are skipped silently rather than written or raised (AC-2).

        Args:
            symbol: Taiwan stock symbol, e.g. ``"2330"``.
            start: Inclusive ISO ``YYYY-MM-DD`` start date.
            end: Inclusive ISO ``YYYY-MM-DD`` end date.

        Returns:
            One :class:`~tsic.models.ChipFlow` per trading day with data, each
            with ``source="twse"`` and signed net values (AC-1).

        Raises:
            SourceFetchError: If any day stays rate-limited (429) after the full
                retry budget (AC-3).
        """
        flows: list[ChipFlow] = []
        for date in _days_in_range(start, end):
            url = (
                f"{_T86_URL}?response=json&date={date.replace('-', '')}&selectType=ALL"
            )
            payload = self._fetch_json(url, f"{symbol} {date}")
            flow = _parse_chips(payload, symbol, date)
            if flow is not None:
                flows.append(flow)
        return flows

    def fetch_fundamentals(
        self, symbol: str, start: str, end: str
    ) -> list[Fundamental]:
        """Not provided by this story; fundamentals come from other sources."""
        raise NotImplementedError("twse fundamentals are out of scope")


def _months_in_range(start: str, end: str) -> list[tuple[int, int]]:
    """Enumerate the ``(year, month)`` pairs spanned by ``[start, end]`` inclusive.

    A range touching three calendar months yields three pairs, which drives the
    one-request-per-month fan-out (AC-1).
    """
    year, month = int(start[:4]), int(start[5:7])
    end_year, end_month = int(end[:4]), int(end[5:7])
    months: list[tuple[int, int]] = []
    while (year, month) <= (end_year, end_month):
        months.append((year, month))
        month += 1
        if month > 12:
            month = 1
            year += 1
    return months


def _days_in_range(start: str, end: str) -> Iterator[str]:
    """Yield every ISO ``YYYY-MM-DD`` date in ``[start, end]`` inclusive.

    Drives the one-request-per-day ``T86`` fan-out (AC-2/AC-3). Non-trading days
    are not filtered here — the parser skips them via the no-data payload.
    """
    current = datetime.date.fromisoformat(start)
    last = datetime.date.fromisoformat(end)
    one_day = datetime.timedelta(days=1)
    while current <= last:
        yield current.isoformat()
        current += one_day


def _parse_chips(payload: Any, symbol: str, date: str) -> ChipFlow | None:
    """Convert one day's ``T86`` payload into a :class:`ChipFlow` for ``symbol``.

    ``T86`` rows are keyed by 證券代號 and the net-flow columns are
    thousands-separated signed share counts. Field positions vary between the
    legacy and modern report layouts, so columns are resolved by *header name*
    via :data:`_FOREIGN_FIELDS` / :data:`_TRUST_FIELDS` / :data:`_DEALER_FIELDS`
    (summing the sub-columns the modern layout splits into).

    Returns ``None`` — never raises — when the day has no report (``stat`` not
    ``"OK"``), when ``symbol`` is absent from that day's data, or when the
    matched row's numeric cells are unparseable (AC-2).
    """
    if not payload or payload.get("stat") != "OK":
        return None

    fields = payload.get("fields") or []
    column = {name: i for i, name in enumerate(fields)}
    for row in payload.get("data") or []:
        if not row or row[0].strip() != symbol:
            continue
        try:
            return ChipFlow(
                symbol=symbol,
                date=date,
                foreign_net=_sum_fields(row, column, _FOREIGN_FIELDS),
                trust_net=_sum_fields(row, column, _TRUST_FIELDS),
                dealer_net=_sum_fields(row, column, _DEALER_FIELDS),
                source="twse",
            )
        except (KeyError, ValueError, IndexError):
            # A matched-but-malformed row is treated as no data for the day.
            return None
    return None


def _sum_fields(
    row: list[str], column: dict[str, int], field_names: tuple[str, ...]
) -> int:
    """Sum the present ``field_names`` columns of ``row`` into a signed int.

    Aliases that aren't in this payload's header are skipped, so the legacy
    aggregate column and the modern split sub-columns both resolve correctly.
    Raises :class:`ValueError` if *no* alias is present (an unexpected layout).
    """
    matched = [name for name in field_names if name in column]
    if not matched:
        raise ValueError(f"no T86 column among {field_names}")
    return sum(_to_int(row[column[name]]) for name in matched)


def _parse_prices(payload: Any, symbol: str, start: str, end: str) -> list[DailyPrice]:
    """Convert a TWSE ``STOCK_DAY`` JSON payload into raw :class:`DailyPrice` rows.

    Each ``data`` row is ``[日期, 成交股數, 成交金額, 開盤價, 最高價, 最低價,
    收盤價, 漲跌價差, 成交筆數]`` with a Republic-of-China date (``"115/06/10"``)
    and thousands-separated numbers. Rows outside ``[start, end]`` and rows whose
    prices are non-numeric (e.g. ``"--"`` on a no-trade day) are skipped.

    Args:
        payload: The decoded JSON; ignored unless ``stat == "OK"``.
        symbol: The symbol these rows belong to (TWSE does not echo it per row).
        start: Inclusive ISO ``YYYY-MM-DD`` lower bound.
        end: Inclusive ISO ``YYYY-MM-DD`` upper bound.

    Returns:
        One :class:`DailyPrice` per in-range trading day, ``adjusted=0`` and
        ``source="twse"``, in payload order.
    """
    if not payload or payload.get("stat") != "OK":
        return []

    prices: list[DailyPrice] = []
    for row in payload.get("data") or []:
        date = _format_roc_date(row[0])
        if date < start or date > end:
            continue
        try:
            prices.append(
                DailyPrice(
                    symbol=symbol,
                    date=date,
                    open=_to_float(row[3]),
                    high=_to_float(row[4]),
                    low=_to_float(row[5]),
                    close=_to_float(row[6]),
                    volume=_to_int(row[1]),
                    source="twse",
                    adjusted=0,
                )
            )
        except ValueError:
            # Skip rows whose numeric cells are placeholders like "--".
            continue
    return prices


def _format_roc_date(roc_date: str) -> str:
    """Render a Republic-of-China date (``"115/06/10"``) as ISO ``YYYY-MM-DD``."""
    year, month, day = roc_date.split("/")
    return f"{int(year) + _ROC_YEAR_OFFSET:04d}-{int(month):02d}-{int(day):02d}"


def _to_float(value: str) -> float:
    """Parse a thousands-separated TWSE numeric cell into a float."""
    return float(value.replace(",", ""))


def _to_int(value: str) -> int:
    """Parse a thousands-separated TWSE share-count cell into an int."""
    return int(float(value.replace(",", "")))
