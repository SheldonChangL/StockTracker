"""Tests for the TUI background-update worker and progress bar (Story 8.3).

FR-30/NFR-8, AC-1..AC-3. The update runs on a threaded worker
(``run_worker(thread=True)``) so the event loop keeps handling input while a
slow batch fetch runs (AC-2), and per-symbol progress events drive an
observable ``id="progress-bar"`` widget (AC-1, AC-3).

The async bodies are driven through :func:`asyncio.run` (the project does not
depend on pytest-asyncio), matching the ``async with TsicApp(...).run_test()``
Pilot harness used across Story 8.x.
"""

from __future__ import annotations

import asyncio
import threading

from textual.widgets import ProgressBar

from tsic.fetching.orchestrator import FetchOrchestrator
from tsic.models import ChipFlow, DailyPrice, Fundamental
from tsic.sources.base import BaseSource
from tsic.tui.app import PROGRESS_BAR_ID, TsicApp


class FakeRepo:
    """A WatchlistSource with no rows; the update path is what these tests drive."""

    def watchlist_rows(self) -> list:
        return []


class _Source(BaseSource):
    """In-memory source yielding one row per symbol, optionally gated.

    When ``gate`` is set, each fetch sets ``entered`` and blocks on the event,
    letting a test hold the worker mid-fetch to prove the event loop is free.
    """

    concurrency = 1
    rate_limit = 1.0

    def __init__(
        self,
        *,
        gate: threading.Event | None = None,
        entered: threading.Event | None = None,
    ) -> None:
        self._gate = gate
        self._entered = entered

    name = property(lambda self: "fake")  # type: ignore[assignment]
    priority = property(lambda self: 1)  # type: ignore[assignment]

    @property
    def available(self) -> bool:
        return True

    def fetch_prices(self, symbol: str, start: str, end: str) -> list[DailyPrice]:
        if self._entered is not None:
            self._entered.set()
        if self._gate is not None:
            self._gate.wait(timeout=5.0)
        return [
            DailyPrice(
                symbol=symbol,
                date="2026-06-10",
                open=1.0,
                high=1.0,
                low=1.0,
                close=1.0,
                volume=1,
                source="fake",
            )
        ]

    def fetch_chips(self, symbol: str, start: str, end: str) -> list[ChipFlow]:
        raise NotImplementedError

    def fetch_fundamentals(
        self, symbol: str, start: str, end: str
    ) -> list[Fundamental]:
        raise NotImplementedError


class FakeRepoStore:
    """Thread-safe in-memory PriceRepository stand-in (first-write-wins)."""

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


def _app(*, gate=None, entered=None, symbols=("2330", "2317", "2454")) -> TsicApp:
    orch = FetchOrchestrator(
        [_Source(gate=gate, entered=entered)], FakeRepoStore(), concurrency=3
    )
    return TsicApp(
        repo=FakeRepo(),
        orchestrator=orch,
        symbols=list(symbols),
        date_range=("2026-06-01", "2026-06-30"),
    )


# --- AC-1: the progress bar widget exists with the stable id ---------------


def test_progress_bar_has_stable_id() -> None:
    async def scenario() -> None:
        async with TsicApp(repo=FakeRepo()).run_test() as pilot:
            bar = pilot.app.query_one(f"#{PROGRESS_BAR_ID}", ProgressBar)
            assert bar is not None

    asyncio.run(scenario())


# --- AC-1/AC-2: update runs on a threaded worker, off the event loop --------


def test_update_runs_on_threaded_worker() -> None:
    async def scenario() -> None:
        gate = threading.Event()
        entered = threading.Event()
        app = _app(gate=gate, entered=entered, symbols=("2330",))
        try:
            async with app.run_test() as pilot:
                pilot.app.action_update()
                await pilot.pause()
                assert entered.wait(timeout=2.0)
                # While the fetch is held, the update is observably in-flight on
                # a worker rather than having run inline on the event loop.
                workers = list(pilot.app.workers)
                assert len(workers) == 1
                gate.set()
                await pilot.app.workers.wait_for_complete()
        finally:
            gate.set()

    asyncio.run(scenario())


def test_event_loop_not_frozen_during_slow_update() -> None:
    """AC-2: a slow fetch holds the worker, yet the loop still serves the UI."""

    async def scenario() -> None:
        gate = threading.Event()
        entered = threading.Event()
        app = _app(gate=gate, entered=entered, symbols=("2330",))
        try:
            async with app.run_test() as pilot:
                pilot.app.action_update()
                await pilot.pause()
                # The worker thread is now blocked inside the slow fetch...
                assert entered.wait(timeout=2.0)
                assert not gate.is_set()
                # ...yet the main event loop still answers queries (not frozen).
                bar = pilot.app.query_one(f"#{PROGRESS_BAR_ID}", ProgressBar)
                assert bar is not None
                gate.set()  # release the worker so it can finish
                await pilot.app.workers.wait_for_complete()
        finally:
            gate.set()

    asyncio.run(scenario())


# --- AC-3: worker progress events advance the progress bar ------------------


def test_progress_bar_reaches_total_after_update() -> None:
    async def scenario() -> None:
        symbols = ("2330", "2317", "2454")
        async with _app(symbols=symbols).run_test() as pilot:
            pilot.app.action_update()
            await pilot.app.workers.wait_for_complete()
            await pilot.pause()
            bar = pilot.app.query_one(f"#{PROGRESS_BAR_ID}", ProgressBar)
            assert bar.total == len(symbols)
            assert bar.progress == len(symbols)
            assert bar.percentage == 1.0

    asyncio.run(scenario())


def test_no_orchestrator_makes_update_a_noop() -> None:
    """Story 8.1 keeps working: no orchestrator means update does nothing."""

    async def scenario() -> None:
        async with TsicApp(repo=FakeRepo()).run_test() as pilot:
            pilot.app.action_update()
            await pilot.pause()
            assert not list(pilot.app.workers)

    asyncio.run(scenario())
