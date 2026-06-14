"""Concurrent, fault-tolerant price-fetch orchestration (Story 3.7).

The :class:`FetchOrchestrator` drives a batch of symbols through the layered
data-source strategy (Story 3.1) and the incremental repository (Story 2.4),
turning many independent fetches into one robust batch run. Its guarantees:

* **Source fallback** — for each symbol the configured sources are tried in
  ascending :attr:`~tsic.sources.base.BaseSource.priority` order; a source that
  raises is recorded and the next source is tried, so a healthy lower-priority
  source still serves the symbol (AC-1). A source flagged unavailable (e.g. a
  Fugle source with no API key) is skipped without counting as a failure.
* **Continue-on-failure** — a symbol whose every source fails is recorded as a
  failure *with its reasons* but never aborts the batch; the remaining symbols
  are still fetched (AC-2).
* **Resumable / idempotent** — each symbol resumes from ``MAX(date) + 1`` so a
  re-run after an interruption appends only the missing tail and never
  duplicates rows (AC-5, leaning on the repository's first-write-wins upsert).
* **Concurrent with timeout protection** — symbols are fetched on a
  :class:`~concurrent.futures.ThreadPoolExecutor` sized by ``concurrency``, and
  a per-future ``timeout`` stops one wedged fetch from stalling the whole batch
  (no ``signal.alarm``; future-level only) (AC-4).

The batch returns a :class:`FetchSummary` partitioning every symbol into
*succeeded* (new rows written), *skipped* (a source answered but had no new
data), or *failed* (every source failed), with a human-readable ``render()``
of "成功 N / 跳過 N / 失敗 N（附原因）" (AC-3).

Repository access is serialized through a lock so a single connection can back
all worker threads (ADR-1's write-serialization). For a real SQLite connection
shared across threads, open it with ``check_same_thread=False``; WAL mode then
serializes writers while the lock here prevents concurrent use of the one
connection object.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass, field
from datetime import date, timedelta

from tsic.fetching.validator import BatchValidation, validate_prices
from tsic.models import DailyPrice, FetchResult
from tsic.sources.base import BaseSource
from tsic.storage.repository import ChipRepository, DataPollutionError, PriceRepository

logger = logging.getLogger(__name__)

#: Default number of symbols fetched concurrently (AC-4).
_DEFAULT_CONCURRENCY = 3

#: Default lookback (days) for the best-effort 籌碼面 fetch. Kept short on purpose:
#: TWSE's T86 report is one HTTP request *per day*, so matching the 365-day price
#: window would make every update minutes-long. 30 days covers the recent chip
#: trend an analysis needs, and the fetch resumes incrementally from there.
_DEFAULT_CHIP_HISTORY_DAYS = 30


#: Write-time validator signature; injectable so tests can swap it out.
Validator = Callable[[list[DailyPrice]], BatchValidation]

#: Progress callback signature: invoked with ``(completed, total)`` after each
#: symbol finishes, so a UI can drive a progress bar (Story 8.3, FR-30).
ProgressCallback = Callable[[int, int], None]


@dataclass
class FetchSummary:
    """Aggregate outcome of a batch fetch, partitioned for assertion (AC-3).

    Each symbol contributes exactly one :class:`~tsic.models.FetchResult`. The
    three categories are derived from that result so there is a single source of
    truth per symbol:

    * **succeeded** — a source returned data and new rows were written
      (``success`` and ``rows > 0``).
    * **skipped** — a source answered but yielded no new rows, i.e. the symbol
      was already up to date (``success`` and ``rows == 0``).
    * **failed** — every source failed (``not success``); ``errors`` carries the
      per-source reasons.
    """

    results: list[FetchResult] = field(default_factory=list)

    @property
    def succeeded(self) -> list[FetchResult]:
        """Symbols for which new rows were written."""
        return [r for r in self.results if r.success and r.rows > 0]

    @property
    def skipped(self) -> list[FetchResult]:
        """Symbols a source served but with no new data."""
        return [r for r in self.results if r.success and r.rows == 0]

    @property
    def failed(self) -> list[FetchResult]:
        """Symbols whose every source failed."""
        return [r for r in self.results if not r.success]

    @property
    def success_count(self) -> int:
        """Number of symbols with new rows written."""
        return len(self.succeeded)

    @property
    def skipped_count(self) -> int:
        """Number of symbols skipped as already up to date."""
        return len(self.skipped)

    @property
    def failed_count(self) -> int:
        """Number of symbols that failed on every source."""
        return len(self.failed)

    def render(self) -> str:
        """Render the assertable summary line plus per-symbol failure reasons.

        Returns the headline ``成功 N / 跳過 N / 失敗 N`` followed by one line per
        failed symbol giving its joined reasons, so callers (and the AC) can
        read both the counts and *why* a symbol failed.
        """
        lines = [
            f"成功 {self.success_count} / 跳過 {self.skipped_count} / "
            f"失敗 {self.failed_count}"
        ]
        for result in self.failed:
            reason = "; ".join(result.errors) or result.message or "unknown error"
            lines.append(f"  - {result.symbol}: {reason}")
        return "\n".join(lines)


class FetchOrchestrator:
    """Fetch many symbols concurrently with source fallback and a summary.

    Args:
        sources: The data sources to try, in any order; they are tried per
            symbol in ascending :attr:`~tsic.sources.base.BaseSource.priority`.
        repository: Store exposing ``latest_date`` and ``upsert_prices``
            (typically a :class:`~tsic.storage.repository.PriceRepository`).
            Access is serialized internally (see module docstring).
        concurrency: Maximum symbols fetched at once; sizes the thread pool
            (AC-4). Defaults to ``3``.
        timeout: Per-symbol wall-clock ceiling in seconds. ``None`` (default)
            waits indefinitely; a finite value records a timed-out symbol as a
            failure and lets the batch continue, so one wedged fetch cannot
            stall the whole run (AC-4).
        validator: Write-time price validator; defaults to
            :func:`~tsic.fetching.validator.validate_prices`.
        chip_repository: Optional store for 籌碼面 net-flows. When provided, each
            symbol's recent chips are fetched best-effort alongside its prices
            (see ``chip_history_days``) and persisted here; when ``None`` chip
            fetching is disabled and behaviour is exactly the price-only path.
        chip_history_days: Lookback window (days) for the chip fetch, counted back
            from the batch ``end``. Defaults to :data:`_DEFAULT_CHIP_HISTORY_DAYS`.
    """

    def __init__(
        self,
        sources: Iterable[BaseSource],
        repository: PriceRepository,
        *,
        concurrency: int = _DEFAULT_CONCURRENCY,
        timeout: float | None = None,
        validator: Validator = validate_prices,
        chip_repository: ChipRepository | None = None,
        chip_history_days: int = _DEFAULT_CHIP_HISTORY_DAYS,
    ) -> None:
        self._sources: list[BaseSource] = sorted(sources, key=lambda s: s.priority)
        self._repository = repository
        self._concurrency = max(1, concurrency)
        self._timeout = timeout
        self._validate = validator
        self._chip_repository = chip_repository
        self._chip_history_days = max(0, chip_history_days)
        self._repo_lock = threading.Lock()

    def fetch_prices(
        self,
        symbols: Sequence[str],
        start: str,
        end: str,
        *,
        progress: ProgressCallback | None = None,
    ) -> FetchSummary:
        """Fetch ``[start, end]`` OHLCV for every symbol and summarize.

        Symbols are fetched concurrently on a pool of ``concurrency`` workers.
        Each symbol resumes from ``MAX(date) + 1`` (AC-5); a per-future timeout
        guards against a single wedged fetch (AC-4); a symbol whose sources all
        fail is recorded but never aborts the batch (AC-2).

        Args:
            symbols: Symbols to fetch. Order is irrelevant to the result counts.
            start: Inclusive ISO ``YYYY-MM-DD`` lower bound for symbols with no
                stored history yet.
            end: Inclusive ISO ``YYYY-MM-DD`` upper bound for every symbol.
            progress: Optional callback invoked with ``(completed, total)`` after
                each symbol finishes (success or failure), letting a caller drive
                a progress bar without coupling to the orchestrator's internals
                (Story 8.3). Invoked from the calling thread, never concurrently.

        Returns:
            A :class:`FetchSummary` with one result per symbol.
        """
        if not symbols:
            return FetchSummary()

        results: list[FetchResult] = []
        executor = ThreadPoolExecutor(max_workers=self._concurrency)
        try:
            futures = {
                executor.submit(self._fetch_one, symbol, start, end): symbol
                for symbol in symbols
            }
            # Wait on each future with its own timeout so a single stuck symbol
            # is recorded as a failure rather than blocking the batch (AC-4).
            for future, symbol in futures.items():
                try:
                    results.append(future.result(timeout=self._timeout))
                except FutureTimeoutError:
                    message = f"timed out after {self._timeout}s"
                    logger.warning("fetch for %s %s", symbol, message)
                    results.append(
                        FetchResult(
                            symbol=symbol,
                            success=False,
                            message=message,
                            errors=[message],
                        )
                    )
                except Exception as exc:  # noqa: BLE001 - defensive batch guard.
                    logger.warning("fetch for %s raised: %s", symbol, exc)
                    results.append(
                        FetchResult(
                            symbol=symbol,
                            success=False,
                            message=str(exc),
                            errors=[str(exc)],
                        )
                    )
                # Report progress once per finished symbol, regardless of outcome.
                if progress is not None:
                    progress(len(results), len(symbols))
        finally:
            # Do not block batch completion on a wedged worker thread (AC-4);
            # not-yet-started fetches are cancelled.
            executor.shutdown(wait=False, cancel_futures=True)

        return FetchSummary(results)

    def _fetch_one(self, symbol: str, start: str, end: str) -> FetchResult:
        """Worker body: fetch a symbol's prices, then its chips best-effort.

        The :class:`FetchResult` reflects the *price* outcome only; chip fetching
        is a non-fatal companion (籌碼面 is supplementary), so any chip error is
        logged and swallowed rather than dragging the symbol into "failed".
        """
        result = self._fetch_symbol(symbol, start, end)
        if self._chip_repository is not None and self._chip_history_days > 0:
            try:
                self._fetch_chips_for_symbol(symbol, end)
            except Exception as exc:  # noqa: BLE001 - chips are best-effort.
                logger.warning("chip fetch for %s raised: %s", symbol, exc)
        return result

    def _fetch_chips_for_symbol(self, symbol: str, end: str) -> None:
        """Fetch and store ``symbol``'s recent 籌碼面 net-flows (best-effort).

        Resumes from ``MAX(chip date) + 1`` but never reaches further back than
        ``chip_history_days`` before ``end``. Sources that do not provide chips
        (every source but TWSE today) raise ``NotImplementedError`` and are
        skipped; the first source that answers — even with no rows — ends the
        fallback, mirroring the price path's "a source answered" semantics.
        """
        assert self._chip_repository is not None
        start = self._resume_chip_start(symbol, end)
        if start > end:
            return
        for source in self._sources:
            if not getattr(source, "available", True):
                continue
            try:
                chips = source.fetch_chips(symbol, start, end)
            except NotImplementedError:
                continue
            except Exception as exc:  # noqa: BLE001 - upstream errors are opaque.
                logger.warning(
                    "chip fetch for %s via %s failed: %s", symbol, source.name, exc
                )
                continue
            if chips:
                with self._repo_lock:
                    self._chip_repository.upsert_chips(chips)
            return

    def _resume_chip_start(self, symbol: str, end: str) -> str:
        """Return the chip resume date: ``MAX(date)+1`` clamped to the window start."""
        window_start = (
            date.fromisoformat(end) - timedelta(days=self._chip_history_days)
        ).isoformat()
        with self._repo_lock:
            latest = self._chip_repository.latest_chip_date(symbol)  # type: ignore[union-attr]
        if latest is None:
            return window_start
        resume = (date.fromisoformat(latest) + timedelta(days=1)).isoformat()
        return max(window_start, resume)

    def _fetch_symbol(self, symbol: str, start: str, end: str) -> FetchResult:
        """Fetch one symbol with source fallback; never raises for source errors.

        Resumes from ``MAX(date) + 1`` and tries each source in priority order,
        falling back on failure. Returns a classified :class:`FetchResult`.
        """
        resume_start = self._resume_start(symbol, start)
        if resume_start > end:
            message = f"{symbol} already up to date (>= {end})"
            logger.info(message)
            return FetchResult(symbol=symbol, success=True, rows=0, message=message)

        errors: list[str] = []
        empty_note: str | None = None
        for source in self._sources:
            if not getattr(source, "available", True):
                errors.append(f"{source.name}: unavailable, skipped")
                continue

            try:
                fetched = source.fetch_prices(symbol, resume_start, end)
            except Exception as exc:  # noqa: BLE001 - upstream errors are opaque.
                reason = f"{source.name}: {exc}"
                logger.warning("fetch for %s failed via %s", symbol, reason)
                errors.append(reason)
                continue

            # A source that returns nothing simply has no data for this symbol
            # (e.g. yfinance lacks a ``.TW``/``.TWO`` listing); fall back to the
            # next source instead of masking the gap as "up to date". Remember
            # it so an all-empty run reports a clean skip, not a failure.
            if not fetched:
                empty_note = f"{symbol}: no data from {source.name}"
                logger.info(empty_note)
                continue

            # The source answered with data: validate, persist, stop falling back.
            validation = self._validate(fetched)
            for warning in validation.warnings:
                logger.warning(warning)

            try:
                with self._repo_lock:
                    written = self._repository.upsert_prices(validation.valid)
            except DataPollutionError as exc:
                reason = f"{source.name}: {exc}"
                logger.warning("write for %s rejected: %s", symbol, reason)
                errors.append(reason)
                continue

            if written > 0:
                message = f"fetched {written} row(s) from {source.name}"
                return FetchResult(
                    symbol=symbol,
                    source=source.name,
                    success=True,
                    rows=written,
                    message=message,
                    errors=errors,
                )

            message = f"{symbol}: no new data from {source.name}"
            return FetchResult(
                symbol=symbol,
                source=source.name,
                success=True,
                rows=0,
                message=message,
                errors=errors,
            )

        # Every source is exhausted. If at least one answered (with no data),
        # that is a clean skip — the symbol simply has nothing in this range.
        # Only if every source errored/was unavailable is it a real failure.
        if empty_note is not None:
            return FetchResult(
                symbol=symbol,
                success=True,
                rows=0,
                message=empty_note,
                errors=errors,
            )

        message = f"all sources failed for {symbol}"
        logger.warning(message)
        return FetchResult(symbol=symbol, success=False, message=message, errors=errors)

    def _resume_start(self, symbol: str, default_start: str) -> str:
        """Return the resume date: ``MAX(date) + 1`` or ``default_start`` (AC-5)."""
        with self._repo_lock:
            latest = self._repository.latest_date(symbol)
        if latest is None:
            return default_start
        return (date.fromisoformat(latest) + timedelta(days=1)).isoformat()
