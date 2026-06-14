"""Tests for the Fugle secondary fallback price source (Story 3.5, AC-1..AC-3)."""

from __future__ import annotations

import pytest

from tsic import settings
from tsic.sources import BaseSource
from tsic.sources.fugle_source import FugleSource
from tsic.sources.yfinance_source import SourceFetchError


def _ok_payload() -> dict[str, object]:
    """A small Fugle historical-candles OK payload (raw, unadjusted prices)."""
    return {
        "symbol": "2330",
        "type": "EQUITY",
        "exchange": "TWSE",
        "data": [
            {
                "date": "2026-06-10",
                "open": 100.0,
                "high": 105.0,
                "low": 99.0,
                "close": 104.0,
                "volume": 12000,
            },
            {
                "date": "2026-06-11",
                "open": 101.5,
                "high": 102.0,
                "low": 100.5,
                "close": 101.0,
                "volume": 9000,
            },
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
    """Captures each (url, api_key) call and returns a canned OK payload."""

    def __init__(self, payload: object) -> None:
        self._payload = payload
        self.urls: list[str] = []
        self.keys: list[str] = []

    def __call__(self, url: str, api_key: str) -> _FakeResponse:
        self.urls.append(url)
        self.keys.append(api_key)
        return _FakeResponse(self._payload)


def _no_sleep(_seconds: float) -> None:
    """Sleep stub so backoff tests never touch the wall clock."""


def test_is_a_base_source() -> None:
    assert isinstance(FugleSource(api_key="k"), BaseSource)


# AC-1: with no key configured the source constructs but is unavailable.
def test_unavailable_when_key_missing(monkeypatch) -> None:
    monkeypatch.delenv(settings.FUGLE_API_KEY_ENV, raising=False)
    source = FugleSource()  # must not raise — missing key is non-fatal.
    assert source.available is False


# AC-1: an unavailable source raises (orchestrator guards via `available`),
# rather than silently hitting the network without credentials.
def test_fetch_when_unavailable_raises_source_error(monkeypatch) -> None:
    monkeypatch.delenv(settings.FUGLE_API_KEY_ENV, raising=False)
    source = FugleSource()
    with pytest.raises(SourceFetchError):
        source.fetch_prices("2330", "2026-06-01", "2026-06-30")


# AC-1: the env key (TSIC_FUGLE_API_KEY) makes the source available.
def test_available_from_env_key(monkeypatch) -> None:
    monkeypatch.setenv(settings.FUGLE_API_KEY_ENV, "env-key")
    assert FugleSource().available is True


# AC-2: the OK fixture parses into raw fugle-sourced DailyPrice rows.
def test_parser_emits_raw_fugle_daily_prices() -> None:
    fetcher = _RecordingFetcher(_ok_payload())
    source = FugleSource(api_key="k", fetch_fn=fetcher, sleep_fn=_no_sleep)

    prices = source.fetch_prices("2330", "2026-06-01", "2026-06-30")

    assert [p.date for p in prices] == ["2026-06-10", "2026-06-11"]
    assert all(p.source == "fugle" for p in prices)
    assert all(p.adjusted == 0 for p in prices)
    assert all(p.symbol == "2330" for p in prices)

    first = prices[0]
    assert first.open == 100.0
    assert first.high == 105.0
    assert first.low == 99.0
    assert first.close == 104.0
    assert first.volume == 12000


# AC-2: the request carries the API key and targets the candles endpoint.
def test_request_carries_key_and_targets_candles_endpoint() -> None:
    fetcher = _RecordingFetcher(_ok_payload())
    source = FugleSource(api_key="secret", fetch_fn=fetcher, sleep_fn=_no_sleep)

    source.fetch_prices("2330", "2026-06-01", "2026-06-30")

    assert len(fetcher.urls) == 1
    url = fetcher.urls[0]
    assert "stock/historical/candles/2330" in url
    assert "from=2026-06-01" in url
    assert "to=2026-06-30" in url
    assert fetcher.keys == ["secret"]


def test_rows_outside_range_are_filtered() -> None:
    source = FugleSource(
        api_key="k", fetch_fn=_RecordingFetcher(_ok_payload()), sleep_fn=_no_sleep
    )

    prices = source.fetch_prices("2330", "2026-06-11", "2026-06-30")

    assert [p.date for p in prices] == ["2026-06-11"]


def test_empty_payload_yields_no_prices() -> None:
    source = FugleSource(
        api_key="k", fetch_fn=_RecordingFetcher({"data": []}), sleep_fn=_no_sleep
    )
    assert source.fetch_prices("2330", "2026-06-01", "2026-06-30") == []


def test_malformed_rows_are_skipped() -> None:
    payload = {
        "data": [
            {"date": "2026-06-10", "open": "n/a"},  # unparseable / missing cells
            {
                "date": "2026-06-11",
                "open": 101.5,
                "high": 102.0,
                "low": 100.5,
                "close": 101.0,
                "volume": 9000,
            },
        ]
    }
    source = FugleSource(
        api_key="k", fetch_fn=_RecordingFetcher(payload), sleep_fn=_no_sleep
    )

    prices = source.fetch_prices("2330", "2026-06-01", "2026-06-30")

    assert [p.date for p in prices] == ["2026-06-11"]


# AC-3: a 429 is retried with a doubling backoff, then succeeds.
def test_retries_429_with_doubling_backoff_then_succeeds() -> None:
    payload = _ok_payload()
    attempts = {"n": 0}

    def flaky(url: str, api_key: str) -> _FakeResponse:
        attempts["n"] += 1
        if attempts["n"] < 3:
            return _FakeResponse(None, status_code=429)
        return _FakeResponse(payload)

    slept: list[float] = []
    source = FugleSource(api_key="k", fetch_fn=flaky, sleep_fn=slept.append)

    prices = source.fetch_prices("2330", "2026-06-01", "2026-06-30")

    assert attempts["n"] == 3
    assert slept == [1.0, 2.0]  # doubling backoff
    assert len(prices) == 2


# AC-3: after the retry budget (3 retries / 4 attempts) a 429 gives up.
def test_gives_up_after_retry_budget_and_raises() -> None:
    def always_429(url: str, api_key: str) -> _FakeResponse:
        return _FakeResponse(None, status_code=429)

    slept: list[float] = []
    source = FugleSource(api_key="k", fetch_fn=always_429, sleep_fn=slept.append)

    with pytest.raises(SourceFetchError):
        source.fetch_prices("2330", "2026-06-01", "2026-06-30")

    assert slept == [1.0, 2.0, 4.0]  # exactly three doubling backoffs


# AC-3: the shared per-source bucket is acquired before every attempt.
def test_bucket_is_acquired_before_every_attempt() -> None:
    payload = _ok_payload()
    attempts = {"n": 0}

    def flaky(url: str, api_key: str) -> _FakeResponse:
        attempts["n"] += 1
        if attempts["n"] < 3:
            return _FakeResponse(None, status_code=429)
        return _FakeResponse(payload)

    source = FugleSource(api_key="k", fetch_fn=flaky, sleep_fn=_no_sleep)
    acquisitions: list[float] = []
    original_acquire = source.bucket.acquire
    source.bucket.acquire = lambda *a, **k: (  # type: ignore[method-assign]
        acquisitions.append(1.0) or original_acquire(*a, **k)
    )

    source.fetch_prices("2330", "2026-06-01", "2026-06-30")

    assert len(acquisitions) == 3  # one acquire per attempt, retries included


# AC-3: priority is third (after yfinance=1, twse=2); budget is configurable.
def test_priority_and_default_budget() -> None:
    source = FugleSource(api_key="k")
    assert source.name == "fugle"
    assert source.priority == 3
    assert source.concurrency == 3
    assert source.rate_limit == 3.0
    assert source.bucket.rate == source.rate_limit


def test_concurrency_and_rate_limit_are_configurable() -> None:
    source = FugleSource(api_key="k", concurrency=10, rate_limit=8.0)
    assert source.concurrency == 10
    assert source.rate_limit == 8.0
    assert source.bucket.rate == 8.0  # bucket sized from the configured rate
