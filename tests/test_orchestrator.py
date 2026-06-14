"""Tests for the FetchOrchestrator (Story 3.7, AC-1..AC-5)."""

from __future__ import annotations

import threading

from tsic.fetching.orchestrator import FetchOrchestrator, FetchSummary
from tsic.models import ChipFlow, DailyPrice, Fundamental
from tsic.sources.base import BaseSource


class FakeSource(BaseSource):
    """Configurable in-memory source for exercising orchestration paths.

    A source either yields a fixed list of prices, raises a chosen error, or
    blocks on an event (to drive the timeout path). ``available`` is settable so
    the unavailable-skip path can be tested too.
    """

    def __init__(
        self,
        name: str,
        priority: int,
        *,
        prices: list[DailyPrice] | None = None,
        error: Exception | None = None,
        block: threading.Event | None = None,
        available: bool = True,
    ) -> None:
        self._name = name
        self._priority = priority
        self._prices = prices or []
        self._error = error
        self._block = block
        self._available = available
        self.calls: list[tuple[str, str, str]] = []

    name = property(lambda self: self._name)  # type: ignore[assignment]
    priority = property(lambda self: self._priority)  # type: ignore[assignment]
    concurrency = 1
    rate_limit = 1.0

    @property
    def available(self) -> bool:
        return self._available

    def fetch_prices(self, symbol: str, start: str, end: str) -> list[DailyPrice]:
        self.calls.append((symbol, start, end))
        if self._block is not None:
            self._block.wait(timeout=5.0)
        if self._error is not None:
            raise self._error
        return [
            DailyPrice(
                symbol=symbol, date=p.date, open=p.open, high=p.high, low=p.low,
                close=p.close, volume=p.volume, source=self._name, adjusted=0,
            )
            for p in self._prices
        ]

    def fetch_chips(self, symbol: str, start: str, end: str) -> list[ChipFlow]:
        raise NotImplementedError

    def fetch_fundamentals(
        self, symbol: str, start: str, end: str
    ) -> list[Fundamental]:
        raise NotImplementedError


class FakeRepo:
    """Thread-safe in-memory stand-in for PriceRepository.

    Honours first-write-wins on ``(symbol, date)`` like the real upsert so the
    resume/no-duplicate behaviour (AC-5) can be asserted, and tracks rows so
    successful writes (AC-1) are observable.
    """

    def __init__(self) -> None:
        self._rows: dict[tuple[str, str], DailyPrice] = {}
        self._lock = threading.Lock()

    def latest_date(self, symbol: str) -> str | None:
        with self._lock:
            dates = [d for (s, d) in self._rows if s == symbol]
        return max(dates) if dates else None

    def upsert_prices(self, prices: list[DailyPrice]) -> int:
        written = 0
        with self._lock:
            for price in prices:
                key = (price.symbol, price.date)
                if key not in self._rows:
                    self._rows[key] = price
                    written += 1
        return written

    def rows_for(self, symbol: str) -> list[DailyPrice]:
        with self._lock:
            return [p for (s, _), p in self._rows.items() if s == symbol]


def _price(date: str, close: float = 100.0) -> DailyPrice:
    return DailyPrice(
        symbol="", date=date, open=close, high=close, low=close, close=close,
        volume=1000,
    )


# AC-1: fallback by priority — the higher-priority source fails, the next succeeds.
def test_fallback_to_next_source_on_failure() -> None:
    repo = FakeRepo()
    primary = FakeSource("primary", 1, error=RuntimeError("boom"))
    secondary = FakeSource("secondary", 2, prices=[_price("2026-06-10")])
    orch = FetchOrchestrator([secondary, primary], repo)  # unsorted input

    summary = orch.fetch_prices(["2330"], "2026-06-01", "2026-06-30")

    assert summary.success_count == 1
    (result,) = summary.succeeded
    assert result.source == "secondary"
    assert result.rows == 1
    rows = repo.rows_for("2330")
    assert len(rows) == 1 and rows[0].source == "secondary"
    # The primary was tried first (priority 1) and its failure recorded.
    assert primary.calls and secondary.calls
    assert any("primary" in e for e in result.errors)


# AC-1 corollary: an unavailable source is skipped, not treated as a failure.
def test_unavailable_source_is_skipped() -> None:
    repo = FakeRepo()
    off = FakeSource("off", 1, available=False, prices=[_price("2026-06-10")])
    on = FakeSource("on", 2, prices=[_price("2026-06-10")])
    orch = FetchOrchestrator([off, on], repo)

    summary = orch.fetch_prices(["2330"], "2026-06-01", "2026-06-30")

    assert summary.success_count == 1
    assert off.calls == []  # never invoked
    assert summary.succeeded[0].source == "on"


# AC-2: all sources fail -> failure recorded with reason, batch continues.
def test_all_sources_fail_is_recorded_and_batch_continues() -> None:
    repo = FakeRepo()
    bad1 = FakeSource("bad1", 1, error=RuntimeError("net down"))
    bad2 = FakeSource("bad2", 2, error=ValueError("parse error"))
    orch = FetchOrchestrator([bad1, bad2], repo)

    summary = orch.fetch_prices(["FAIL", "OK"], "2026-06-01", "2026-06-30")

    # The whole batch still completed both symbols (continue-on-failure).
    assert len(summary.results) == 2
    assert summary.failed_count == 2  # both symbols hit the same dead sources
    failed = {r.symbol: r for r in summary.failed}
    assert "net down" in "; ".join(failed["FAIL"].errors)
    assert "parse error" in "; ".join(failed["FAIL"].errors)


def test_one_symbol_fails_others_succeed() -> None:
    repo = FakeRepo()

    class PerSymbolSource(FakeSource):
        def fetch_prices(self, symbol, start, end):  # type: ignore[override]
            self.calls.append((symbol, start, end))
            if symbol == "BAD":
                raise RuntimeError("only BAD fails")
            return [DailyPrice(symbol=symbol, date="2026-06-10", close=1.0,
                               open=1.0, high=1.0, low=1.0, volume=1,
                               source=self._name)]

    orch = FetchOrchestrator([PerSymbolSource("s", 1)], repo)
    summary = orch.fetch_prices(["GOOD", "BAD"], "2026-06-01", "2026-06-30")

    assert summary.success_count == 1
    assert summary.failed_count == 1
    assert summary.succeeded[0].symbol == "GOOD"


# AC-3: three-way summary (success / skipped / failed) is assertable with reasons.
def test_summary_partitions_success_skip_fail() -> None:
    repo = FakeRepo()
    # SKIP already has data up to the end date -> resume start > end -> skipped.
    repo.upsert_prices([DailyPrice(symbol="SKIP", date="2026-06-30", close=1.0,
                                   open=1.0, high=1.0, low=1.0, volume=1)])

    class Mixed(FakeSource):
        def fetch_prices(self, symbol, start, end):  # type: ignore[override]
            self.calls.append((symbol, start, end))
            if symbol == "FAIL":
                raise RuntimeError("upstream 500")
            return [DailyPrice(symbol=symbol, date="2026-06-10", close=1.0,
                               open=1.0, high=1.0, low=1.0, volume=1,
                               source=self._name)]

    orch = FetchOrchestrator([Mixed("s", 1)], repo)
    summary = orch.fetch_prices(["OK", "SKIP", "FAIL"], "2026-06-01", "2026-06-30")

    assert summary.success_count == 1
    assert summary.skipped_count == 1
    assert summary.failed_count == 1
    rendered = summary.render()
    assert "成功 1 / 跳過 1 / 失敗 1" in rendered
    assert "FAIL" in rendered and "upstream 500" in rendered


def test_skipped_when_source_returns_no_rows() -> None:
    repo = FakeRepo()
    empty = FakeSource("empty", 1, prices=[])
    orch = FetchOrchestrator([empty], repo)

    summary = orch.fetch_prices(["2330"], "2026-06-01", "2026-06-30")

    assert summary.skipped_count == 1
    assert summary.success_count == 0


# AC-1: an empty (no-data) higher-priority source must fall back, not skip.
def test_empty_source_falls_back_to_next_source() -> None:
    repo = FakeRepo()
    # The preferred source has no data for this symbol (e.g. yfinance with no
    # .TW/.TWO listing); a lower-priority source does.
    empty = FakeSource("empty", 1, prices=[])
    backup = FakeSource("backup", 2, prices=[_price("2026-06-10")])
    orch = FetchOrchestrator([empty, backup], repo)

    summary = orch.fetch_prices(["2330"], "2026-06-01", "2026-06-30")

    assert summary.success_count == 1
    (result,) = summary.succeeded
    assert result.source == "backup"
    assert result.rows == 1
    assert empty.calls and backup.calls  # the empty source was tried first


# All sources empty (none has data) is a clean skip, not a failure.
def test_all_empty_sources_report_skip_not_failure() -> None:
    repo = FakeRepo()
    orch = FetchOrchestrator(
        [FakeSource("a", 1, prices=[]), FakeSource("b", 2, prices=[])], repo
    )

    summary = orch.fetch_prices(["2330"], "2026-06-01", "2026-06-30")

    assert summary.skipped_count == 1
    assert summary.failed_count == 0


# AC-4: concurrency uses a sized pool; a per-future timeout protects the batch.
def test_timeout_does_not_stall_batch() -> None:
    repo = FakeRepo()
    gate = threading.Event()
    slow = FakeSource("slow", 1, block=gate, prices=[_price("2026-06-10")])
    orch = FetchOrchestrator([slow], repo, concurrency=3, timeout=0.05)

    try:
        summary = orch.fetch_prices(["2330"], "2026-06-01", "2026-06-30")
        assert summary.failed_count == 1
        assert "timed out" in "; ".join(summary.failed[0].errors)
    finally:
        gate.set()  # release the blocked worker thread so it can exit


def test_concurrency_runs_symbols_in_parallel() -> None:
    repo = FakeRepo()
    barrier = threading.Barrier(3, timeout=5.0)

    class BarrierSource(FakeSource):
        def fetch_prices(self, symbol, start, end):  # type: ignore[override]
            # All three must arrive together, proving max_workers >= 3.
            barrier.wait()
            return [DailyPrice(symbol=symbol, date="2026-06-10", close=1.0,
                               open=1.0, high=1.0, low=1.0, volume=1,
                               source=self._name)]

    orch = FetchOrchestrator([BarrierSource("s", 1)], repo, concurrency=3)
    summary = orch.fetch_prices(["A", "B", "C"], "2026-06-01", "2026-06-30")

    assert summary.success_count == 3


# AC-5: a re-run resumes from MAX(date)+1 and writes no duplicates.
def test_resume_from_max_date_plus_one() -> None:
    repo = FakeRepo()

    class RangeSource(FakeSource):
        def fetch_prices(self, symbol, start, end):  # type: ignore[override]
            self.calls.append((symbol, start, end))
            # Echo a single row dated at the requested resume start.
            return [DailyPrice(symbol=symbol, date=start, close=1.0, open=1.0,
                               high=1.0, low=1.0, volume=1, source=self._name)]

    source = RangeSource("s", 1)
    orch = FetchOrchestrator([source], repo)

    first = orch.fetch_prices(["2330"], "2026-06-10", "2026-06-30")
    assert first.success_count == 1
    assert source.calls[-1] == ("2330", "2026-06-10", "2026-06-30")

    # Second run must resume from the day after the stored MAX(date).
    second = orch.fetch_prices(["2330"], "2026-06-10", "2026-06-30")
    assert source.calls[-1] == ("2330", "2026-06-11", "2026-06-30")
    # First-write-wins kept the existing row; the new resume start wrote one more.
    assert second.success_count == 1
    assert len(repo.rows_for("2330")) == 2


def test_empty_symbols_returns_empty_summary() -> None:
    orch = FetchOrchestrator([FakeSource("s", 1)], FakeRepo())
    summary = orch.fetch_prices([], "2026-06-01", "2026-06-30")
    assert isinstance(summary, FetchSummary)
    assert summary.results == []
