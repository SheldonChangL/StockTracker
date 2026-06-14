"""Shared dataclass models forming the cross-layer data contract.

These models are the single source of truth consumed by the fetch, storage,
and presentation layers so that no layer redefines its own schema.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DailyPrice:
    """A single trading day's OHLCV record for one symbol.

    Fields and types follow §3 Data Model. ``adjusted`` is an integer flag
    (0 = raw price, 1 = adjusted price) rather than a price value.
    """

    symbol: str = ""
    date: str = ""
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: int = 0
    source: str = ""
    adjusted: int = 0


@dataclass
class ChipFlow:
    """Institutional net-flow (籌碼面) for one symbol on one trading day.

    Net values are signed share counts: positive = net buy, negative = net sell.
    """

    symbol: str = ""
    date: str = ""
    foreign_net: int = 0
    trust_net: int = 0
    dealer_net: int = 0
    source: str = ""


@dataclass
class Fundamental:
    """Per-symbol fundamental (基本面) snapshot.

    Story 3.6 introduces best-effort *quarterly* fundamentals from MOPS, keyed by
    a fiscal ``period`` (``YYYYQn``). Crawling MOPS is best-effort: any metric the
    page does not surface (or that fails to parse) is left ``None`` rather than
    guessed, so callers must treat every quarterly field as optional.

    ``pe_ratio_qtr_end`` is the **quarter-end P/E snapshot as reported by MOPS**
    — it is never recomputed from a live price.

    The legacy ``date`` / ``pe`` / ``pb`` / ``dividend_yield`` fields predate this
    story; they are retained so the existing ``fundamentals`` table and its
    callers keep working until fundamentals persistence is wired in a later story.
    """

    symbol: str = ""
    date: str = ""
    period: str | None = None
    eps: float | None = None
    pe: float = 0.0
    pb: float = 0.0
    dividend_yield: float = 0.0
    pe_ratio_qtr_end: float | None = None
    revenue: float | None = None
    gross_margin: float | None = None
    source: str = ""


@dataclass
class WatchlistEntry:
    """A symbol the user is tracking, with the time it was added.

    ``added_at`` is an ISO-8601 timestamp string recorded when the symbol first
    enters the watchlist (Story 6.1, FR-22).
    """

    symbol: str = ""
    added_at: str = ""


@dataclass
class FetchResult:
    """Outcome wrapper returned by data-fetch operations."""

    symbol: str = ""
    source: str = ""
    success: bool = False
    message: str = ""
    rows: int = 0
    errors: list[str] = field(default_factory=list)
