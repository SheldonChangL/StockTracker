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
    """Per-symbol fundamental (基本面) snapshot for a given date."""

    symbol: str = ""
    date: str = ""
    eps: float = 0.0
    pe: float = 0.0
    pb: float = 0.0
    dividend_yield: float = 0.0
    source: str = ""


@dataclass
class FetchResult:
    """Outcome wrapper returned by data-fetch operations."""

    symbol: str = ""
    source: str = ""
    success: bool = False
    message: str = ""
    rows: int = 0
    errors: list[str] = field(default_factory=list)
