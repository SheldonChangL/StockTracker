"""Tests for the TWSE fallback price source (Story 3.3, AC-1..AC-4)."""

from __future__ import annotations

import pytest

from tsic.sources import BaseSource
from tsic.sources.twse_source import TwseSource
from tsic.sources.yfinance_source import SourceFetchError


def _ok_payload() -> dict[str, object]:
    """A small TWSE STOCK_DAY OK payload (raw, thousands-separated, ROC dates)."""
    return {
        "stat": "OK",
        "fields": [
            "日期",
            "成交股數",
            "成交金額",
            "開盤價",
            "最高價",
            "最低價",
            "收盤價",
            "漲跌價差",
            "成交筆數",
        ],
        "data": [
            [
                "115/06/10",
                "12,000",
                "1,248,000",
                "100.0",
                "105.0",
                "99.0",
                "104.0",
                "+1.0",
                "30",
            ],
            [
                "115/06/11",
                "9,000",
                "909,000",
                "101.5",
                "102.0",
                "100.5",
                "101.0",
                "-3.0",
                "25",
            ],
        ],
    }


class _FakeResponse:
    """Minimal httpx.Response stand-in exposing status_code and json()."""

    def __init__(self, payload: object, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> object:
        return self._payload


class _RecordingFetcher:
    """Captures each request URL and returns a canned OK payload."""

    def __init__(self, payload: object) -> None:
        self._payload = payload
        self.urls: list[str] = []

    def __call__(self, url: str) -> _FakeResponse:
        self.urls.append(url)
        return _FakeResponse(self._payload)


def _no_sleep(_seconds: float) -> None:
    """Sleep stub so backoff tests never touch the wall clock."""


def test_is_a_base_source() -> None:
    assert isinstance(TwseSource(), BaseSource)


# AC-1: a 3-month range issues 3 monthly STOCK_DAY requests, one per month.
def test_fetch_prices_issues_one_request_per_month() -> None:
    fetcher = _RecordingFetcher(_ok_payload())
    source = TwseSource(fetch_fn=fetcher, sleep_fn=_no_sleep)

    source.fetch_prices("2330", "2026-04-15", "2026-06-10")

    assert len(fetcher.urls) == 3
    for url in fetcher.urls:
        assert "STOCK_DAY" in url
        assert "stockNo=2330" in url
    assert "date=20260401" in fetcher.urls[0]
    assert "date=20260501" in fetcher.urls[1]
    assert "date=20260601" in fetcher.urls[2]


# AC-2: the OK fixture parses into raw twse-sourced DailyPrice rows.
def test_parser_emits_raw_twse_daily_prices() -> None:
    source = TwseSource(fetch_fn=_RecordingFetcher(_ok_payload()), sleep_fn=_no_sleep)

    prices = source.fetch_prices("2330", "2026-06-01", "2026-06-30")

    assert [p.date for p in prices] == ["2026-06-10", "2026-06-11"]
    assert all(p.source == "twse" for p in prices)
    assert all(p.adjusted == 0 for p in prices)
    assert all(p.symbol == "2330" for p in prices)

    first = prices[0]
    assert first.open == 100.0
    assert first.high == 105.0
    assert first.low == 99.0
    assert first.close == 104.0
    assert first.volume == 12000  # thousands separator stripped


def test_rows_outside_range_are_filtered() -> None:
    source = TwseSource(fetch_fn=_RecordingFetcher(_ok_payload()), sleep_fn=_no_sleep)

    prices = source.fetch_prices("2330", "2026-06-11", "2026-06-30")

    assert [p.date for p in prices] == ["2026-06-11"]


def test_no_data_payload_yields_no_prices() -> None:
    source = TwseSource(
        fetch_fn=_RecordingFetcher({"stat": "很抱歉，沒有符合條件的資料!"}),
        sleep_fn=_no_sleep,
    )
    assert source.fetch_prices("2330", "2026-06-01", "2026-06-30") == []


def test_placeholder_rows_are_skipped() -> None:
    payload = {
        "stat": "OK",
        "data": [
            ["115/06/10", "0", "0", "--", "--", "--", "--", "0.00", "0"],
            [
                "115/06/11",
                "9,000",
                "909,000",
                "101.5",
                "102.0",
                "100.5",
                "101.0",
                "-3.0",
                "25",
            ],
        ],
    }
    source = TwseSource(fetch_fn=_RecordingFetcher(payload), sleep_fn=_no_sleep)

    prices = source.fetch_prices("2330", "2026-06-01", "2026-06-30")

    assert [p.date for p in prices] == ["2026-06-11"]


# AC-3: a 429 is retried with a doubling backoff, then succeeds.
def test_retries_429_with_doubling_backoff_then_succeeds() -> None:
    payload = _ok_payload()
    attempts = {"n": 0}

    def flaky(url: str) -> _FakeResponse:
        attempts["n"] += 1
        if attempts["n"] < 3:  # first two attempts are rate-limited.
            return _FakeResponse(None, status_code=429)
        return _FakeResponse(payload)

    slept: list[float] = []
    source = TwseSource(fetch_fn=flaky, sleep_fn=slept.append)

    prices = source.fetch_prices("2330", "2026-06-01", "2026-06-30")

    assert attempts["n"] == 3
    assert slept == [1.0, 2.0]  # doubling backoff
    assert len(prices) == 2


# AC-3: after the retry budget (3 retries / 4 attempts) a 429 gives up.
def test_gives_up_after_retry_budget_and_raises() -> None:
    def always_429(url: str) -> _FakeResponse:
        return _FakeResponse(None, status_code=429)

    slept: list[float] = []
    source = TwseSource(fetch_fn=always_429, sleep_fn=slept.append)

    with pytest.raises(SourceFetchError):
        source.fetch_prices("2330", "2026-06-01", "2026-06-30")

    assert slept == [1.0, 2.0, 4.0]  # exactly three doubling backoffs


# AC-3/AC-4: the shared 1 req/s bucket is acquired before every attempt,
# retries included.
def test_bucket_is_acquired_before_every_attempt() -> None:
    payload = _ok_payload()
    attempts = {"n": 0}

    def flaky(url: str) -> _FakeResponse:
        attempts["n"] += 1
        if attempts["n"] < 3:
            return _FakeResponse(None, status_code=429)
        return _FakeResponse(payload)

    source = TwseSource(fetch_fn=flaky, sleep_fn=_no_sleep)
    acquisitions: list[float] = []
    original_acquire = source.bucket.acquire
    source.bucket.acquire = lambda *a, **k: (  # type: ignore[method-assign]
        acquisitions.append(1.0) or original_acquire(*a, **k)
    )

    source.fetch_prices("2330", "2026-06-01", "2026-06-30")

    assert len(acquisitions) == 3  # one acquire per attempt, retries included


# AC-4: concurrency=1, rate_limit=1 req/s, shared per-source bucket.
def test_concurrency_and_rate_limit_match_twse_budget() -> None:
    source = TwseSource()
    assert source.name == "twse"
    assert source.priority == 2
    assert source.concurrency == 1
    assert source.rate_limit == 1.0
    assert source.bucket.rate == 1.0
