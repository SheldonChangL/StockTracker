"""Tests for the MOPS best-effort fundamentals source (Story 3.6, AC-1..AC-3)."""

from __future__ import annotations

import logging

from tsic.sources import BaseSource
from tsic.sources.mops_source import MopsSource


def _ok_page() -> str:
    """A small MOPS season-report style table (Gregorian period labels)."""
    return """
    <html><body>
      <table class="hasBorder">
        <tr>
          <th>期別</th>
          <th>每股盈餘(元)</th>
          <th>本益比</th>
          <th>營業收入(千元)</th>
          <th>毛利率(%)</th>
        </tr>
        <tr>
          <td>2026Q1</td><td>8.50</td><td>18.3</td>
          <td>625,000,000</td><td>53.2</td>
        </tr>
        <tr>
          <td>2025Q4</td><td>9.10</td><td>17.1</td>
          <td>638,000,000</td><td>54.0</td>
        </tr>
      </table>
    </body></html>
    """


class _FakeResponse:
    """Minimal httpx.Response stand-in exposing status_code and text."""

    def __init__(self, text: str, status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code


class _RecordingFetcher:
    """Captures each request URL and returns a canned HTML page."""

    def __init__(self, page: str, status_code: int = 200) -> None:
        self._page = page
        self._status = status_code
        self.urls: list[str] = []

    def __call__(self, url: str) -> _FakeResponse:
        self.urls.append(url)
        return _FakeResponse(self._page, self._status)


def test_is_a_base_source() -> None:
    assert isinstance(MopsSource(), BaseSource)


# AC-1: a MOPS HTML fixture parses (via lxml) into mops-sourced Fundamentals
# with YYYYQn periods and the expected metric values.
def test_parser_emits_mops_fundamentals() -> None:
    source = MopsSource(fetch_fn=_RecordingFetcher(_ok_page()))

    rows = source.fetch_fundamentals("2330", "2025-10-01", "2026-03-31")

    assert [r.period for r in rows] == ["2026Q1", "2025Q4"]
    assert all(r.source == "mops" for r in rows)
    assert all(r.symbol == "2330" for r in rows)

    first = rows[0]
    assert first.eps == 8.50
    assert first.pe_ratio_qtr_end == 18.3
    assert first.revenue == 625_000_000  # thousands separators stripped
    assert first.gross_margin == 53.2


# AC-1: missing/blank cells become None rather than being guessed.
def test_missing_fields_are_none() -> None:
    page = """
    <table>
      <tr><th>期別</th><th>每股盈餘</th><th>本益比</th><th>毛利率</th></tr>
      <tr><td>2026Q1</td><td>--</td><td>18.3</td><td></td></tr>
    </table>
    """
    source = MopsSource(fetch_fn=_RecordingFetcher(page))

    [row] = source.fetch_fundamentals("2330", "2026-01-01", "2026-03-31")

    assert row.period == "2026Q1"
    assert row.eps is None  # blank "--"
    assert row.pe_ratio_qtr_end == 18.3
    assert row.gross_margin is None  # empty cell
    assert row.revenue is None  # column absent entirely


# AC-3: pe_ratio_qtr_end is the page's 本益比 snapshot, read verbatim — never
# recomputed from a price.
def test_pe_ratio_is_the_reported_quarter_end_snapshot() -> None:
    page = """
    <table>
      <tr><th>期別</th><th>本益比</th></tr>
      <tr><td>2026Q1</td><td>21.7</td></tr>
    </table>
    """
    source = MopsSource(fetch_fn=_RecordingFetcher(page))

    [row] = source.fetch_fundamentals("2330", "2026-01-01", "2026-03-31")

    assert row.pe_ratio_qtr_end == 21.7


# AC-1: Republic-of-China period labels are normalised to Gregorian YYYYQn.
def test_roc_period_is_normalised() -> None:
    page = """
    <table>
      <tr><th>季別</th><th>每股盈餘</th></tr>
      <tr><td>115年第1季</td><td>8.50</td></tr>
    </table>
    """
    source = MopsSource(fetch_fn=_RecordingFetcher(page))

    [row] = source.fetch_fundamentals("2330", "2026-01-01", "2026-03-31")

    assert row.period == "2026Q1"  # 115 + 1911 = 2026


# AC-2: an unrecognisable page structure yields [] and exactly one warning,
# never an exception.
def test_unrecognisable_structure_warns_once_and_returns_empty(caplog) -> None:
    page = "<html><body><p>查無資料</p></body></html>"
    source = MopsSource(fetch_fn=_RecordingFetcher(page))

    with caplog.at_level(logging.WARNING, logger="tsic.sources.mops_source"):
        rows = source.fetch_fundamentals("2330", "2026-01-01", "2026-03-31")

    assert rows == []
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1


# AC-2: a network failure is swallowed — one warning, empty result, no raise.
def test_fetch_failure_is_swallowed(caplog) -> None:
    def boom(_url: str) -> _FakeResponse:
        raise RuntimeError("connection reset")

    source = MopsSource(fetch_fn=boom)

    with caplog.at_level(logging.WARNING, logger="tsic.sources.mops_source"):
        rows = source.fetch_fundamentals("2330", "2026-01-01", "2026-03-31")

    assert rows == []
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1


# AC-2: a non-200 response is treated as unavailable, not an error.
def test_non_200_returns_empty(caplog) -> None:
    source = MopsSource(fetch_fn=_RecordingFetcher("<html></html>", status_code=503))

    with caplog.at_level(logging.WARNING, logger="tsic.sources.mops_source"):
        rows = source.fetch_fundamentals("2330", "2026-01-01", "2026-03-31")

    assert rows == []
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1


# AC-1: the request targets MOPS and carries the symbol.
def test_request_targets_mops_with_symbol() -> None:
    fetcher = _RecordingFetcher(_ok_page())
    source = MopsSource(fetch_fn=fetcher)

    source.fetch_fundamentals("2330", "2025-10-01", "2026-03-31")

    assert len(fetcher.urls) == 1
    assert "mops" in fetcher.urls[0]
    assert "co_id=2330" in fetcher.urls[0]


# Rows without a normalisable period (totals, spacers) are skipped silently.
def test_rows_without_period_are_skipped() -> None:
    page = """
    <table>
      <tr><th>期別</th><th>每股盈餘</th></tr>
      <tr><td>2026Q1</td><td>8.50</td></tr>
      <tr><td>合計</td><td>17.60</td></tr>
    </table>
    """
    source = MopsSource(fetch_fn=_RecordingFetcher(page))

    rows = source.fetch_fundamentals("2330", "2026-01-01", "2026-03-31")

    assert [r.period for r in rows] == ["2026Q1"]
