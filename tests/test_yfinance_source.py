"""Tests for the yfinance preferred price source (Story 3.2, AC-1..AC-4)."""

from __future__ import annotations

import pandas as pd
import pytest

from tsic.sources import BaseSource
from tsic.sources.yfinance_source import SourceFetchError, YfinanceSource


def _recorded_frame() -> pd.DataFrame:
    """A small recorded yfinance OHLCV DataFrame (raw, unadjusted prices)."""
    return pd.DataFrame(
        {
            "Open": [100.0, 101.5],
            "High": [105.0, 102.0],
            "Low": [99.0, 100.5],
            "Close": [104.0, 101.0],
            "Adj Close": [103.2, 100.4],
            "Volume": [12000, 9000],
        },
        index=pd.to_datetime(["2026-06-10", "2026-06-11"]),
    )


class _RecordingDownloader:
    """Captures the args of each ``download`` call and returns a canned frame."""

    def __init__(self, frame: pd.DataFrame) -> None:
        self._frame = frame
        self.calls: list[dict[str, object]] = []

    def __call__(self, symbol: str, **kwargs: object) -> pd.DataFrame:
        self.calls.append({"symbol": symbol, **kwargs})
        return self._frame


def _no_sleep(_seconds: float) -> None:
    """Sleep stub so retry tests never touch the wall clock."""


def test_is_a_base_source() -> None:
    assert isinstance(YfinanceSource(), BaseSource)


# AC-1: yfinance is called with auto_adjust=False and threads=False.
def test_fetch_prices_downloads_raw_unadjusted_single_threaded() -> None:
    downloader = _RecordingDownloader(_recorded_frame())
    source = YfinanceSource(download_fn=downloader, sleep_fn=_no_sleep)

    source.fetch_prices("2330", "2026-06-10", "2026-06-11")

    assert len(downloader.calls) == 1
    call = downloader.calls[0]
    assert call["symbol"] == "2330"
    assert call["start"] == "2026-06-10"
    assert call["end"] == "2026-06-11"
    assert call["auto_adjust"] is False
    assert call["threads"] is False


# AC-2: the fixture parses into DailyPrice rows, all raw and sourced "yfinance".
def test_parser_emits_raw_yfinance_daily_prices() -> None:
    downloader = _RecordingDownloader(_recorded_frame())
    source = YfinanceSource(download_fn=downloader, sleep_fn=_no_sleep)

    prices = source.fetch_prices("2330", "2026-06-10", "2026-06-11")

    assert [p.date for p in prices] == ["2026-06-10", "2026-06-11"]
    assert all(p.adjusted == 0 for p in prices)
    assert all(p.source == "yfinance" for p in prices)
    assert all(p.symbol == "2330" for p in prices)

    first = prices[0]
    assert first.open == 100.0
    assert first.high == 105.0
    assert first.low == 99.0
    assert first.close == 104.0  # raw close, NOT the 103.2 adj close
    assert first.volume == 12000


def test_parser_handles_multiindex_columns() -> None:
    # Newer yfinance returns per-symbol MultiIndex columns for single tickers.
    frame = _recorded_frame()
    frame.columns = pd.MultiIndex.from_product([frame.columns, ["2330"]])
    source = YfinanceSource(download_fn=_RecordingDownloader(frame), sleep_fn=_no_sleep)

    prices = source.fetch_prices("2330", "2026-06-10", "2026-06-11")

    assert len(prices) == 2
    assert prices[0].close == 104.0


def test_empty_frame_yields_no_prices() -> None:
    source = YfinanceSource(
        download_fn=_RecordingDownloader(pd.DataFrame()), sleep_fn=_no_sleep
    )
    assert source.fetch_prices("2330", "2026-06-10", "2026-06-11") == []


# AC-3: retry up to 3 times with 1s -> 2s -> 4s backoff, then give up.
def test_retries_then_succeeds_with_exponential_backoff() -> None:
    frame = _recorded_frame()
    attempts = {"n": 0}

    def flaky(symbol: str, **kwargs: object) -> pd.DataFrame:
        attempts["n"] += 1
        if attempts["n"] < 4:  # fail attempts 1-3, succeed on the 4th.
            raise RuntimeError("upstream boom")
        return frame

    slept: list[float] = []
    source = YfinanceSource(download_fn=flaky, sleep_fn=slept.append)

    prices = source.fetch_prices("2330", "2026-06-10", "2026-06-11")

    assert attempts["n"] == 4
    assert slept == [1.0, 2.0, 4.0]
    assert len(prices) == 2


def test_gives_up_after_four_failures_and_raises_source_error() -> None:
    def always_fail(symbol: str, **kwargs: object) -> pd.DataFrame:
        raise RuntimeError("upstream boom")

    slept: list[float] = []
    source = YfinanceSource(download_fn=always_fail, sleep_fn=slept.append)

    with pytest.raises(SourceFetchError):
        source.fetch_prices("2330", "2026-06-10", "2026-06-11")

    # 4 attempts total => exactly the three backoff sleeps were taken.
    assert slept == [1.0, 2.0, 4.0]


# AC-4: concurrency budget for this source is five.
def test_concurrency_is_five() -> None:
    source = YfinanceSource()
    assert source.concurrency == 5
    assert source.name == "yfinance"
    assert source.bucket.rate == source.rate_limit
