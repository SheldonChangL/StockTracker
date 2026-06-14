"""The individual-stock detail screen for tsic (Story 8.2, FR-28).

After picking a symbol in the watchlist (Story 8.1) the user drills into its
recent detail: the last 30 trading days of OHLCV plus whatever 籌碼面 (chip) and
基本面 (fundamental) data the cache holds. This module owns both the *pure
presentation rules* (kept free of any Textual widget so they unit-test without a
running app) and the :class:`DetailApp` that renders them:

* :func:`ohlcv_rows` — projects a symbol's :class:`~tsic.models.DailyPrice` rows
  to the cell strings the OHLCV table shows, capped to the most recent
  :data:`MAX_OHLCV_ROWS` trading days, newest first (AC-1/AC-4).
* :func:`chip_summary` — a one-line 籌碼面 summary built from the latest chip
  record, or the literal :data:`NO_DATA` text when none exists, so a symbol with
  no chip data renders a notice rather than raising (AC-2).
* :func:`fundamental_summary` — projects a (possibly partial) ``Fundamental`` to
  labelled rows, rendering any absent field as :data:`MISSING` rather than
  guessing or omitting it (AC-3).

:class:`DetailApp` mounts a :class:`~textual.widgets.DataTable` whose stable
``id`` is :data:`OHLCV_TABLE_ID` so test automation can query ``#detail-ohlcv``
and assert at most 30 rows (AC-4). Like :class:`~tsic.tui.app.TsicApp`, it holds
no storage logic of its own — it renders an injected :class:`StockDetail` — and
defines no bespoke colour system, relying on Textual's default theme.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from textual.app import App, ComposeResult
from textual.widgets import DataTable, Footer, Header, Static

from tsic.models import ChipFlow, DailyPrice, Fundamental

#: OHLCV table column headers in display order (AC-1).
OHLCV_COLUMNS: tuple[str, ...] = ("日期", "開盤", "最高", "最低", "收盤", "成交量")

#: Maximum OHLCV rows shown: the most recent 30 trading days (AC-1/AC-4).
MAX_OHLCV_ROWS = 30

#: Rendered for a fundamental field the cache does not have (AC-3).
MISSING = "—"

#: Rendered as the 籌碼面 summary when the symbol has no chip data (AC-2).
NO_DATA = "無資料"

#: Stable ``id`` of the OHLCV table, queried by the app and its tests (AC-4).
OHLCV_TABLE_ID = "detail-ohlcv"

#: Stable ``id`` of the 籌碼面 summary panel.
CHIP_SUMMARY_ID = "detail-chips"

#: Stable ``id`` of the 基本面 summary panel.
FUNDAMENTAL_SUMMARY_ID = "detail-fundamentals"

#: 基本面 fields shown in display order, as ``(label, attribute)`` pairs. Any
#: field whose value is ``None`` renders as :data:`MISSING` (AC-3).
FUNDAMENTAL_FIELDS: tuple[tuple[str, str], ...] = (
    ("季別", "period"),
    ("EPS", "eps"),
    ("本益比(季底)", "pe_ratio_qtr_end"),
    ("營收", "revenue"),
    ("毛利率", "gross_margin"),
    ("股價淨值比", "pb"),
    ("殖利率", "dividend_yield"),
)


@dataclass(frozen=True)
class StockDetail:
    """The cached data backing one symbol's detail screen.

    Bundles the inputs :class:`DetailApp` renders so the app stays a dumb
    renderer over already-resolved data, mirroring the source-injection style
    used across the storage layer and :class:`~tsic.tui.app.TsicApp`.
    """

    symbol: str = ""
    prices: Sequence[DailyPrice] = field(default_factory=tuple)
    chips: Sequence[ChipFlow] | None = None
    fundamental: Fundamental | None = None


def ohlcv_rows(prices: Sequence[DailyPrice]) -> list[tuple[str, ...]]:
    """Project ``prices`` to OHLCV cell rows, newest first, capped to 30.

    Only the most recent :data:`MAX_OHLCV_ROWS` trading days are kept (AC-1), so
    a long history never renders more than 30 rows (AC-4). Input is expected in
    ascending date order (as :meth:`PriceRepository.query_prices` returns); the
    output is reversed to newest-first for at-a-glance reading.

    Args:
        prices: A symbol's daily OHLCV rows, ascending by ``date``.

    Returns:
        One cell tuple per shown day in :data:`OHLCV_COLUMNS` order.
    """
    recent = list(prices)[-MAX_OHLCV_ROWS:]
    recent.reverse()
    return [
        (
            row.date,
            _num(row.open),
            _num(row.high),
            _num(row.low),
            _num(row.close),
            str(row.volume),
        )
        for row in recent
    ]


def chip_summary(chips: Sequence[ChipFlow] | None) -> str:
    """Return a one-line 籌碼面 summary, or :data:`NO_DATA` when empty (AC-2).

    The summary reports the most recent chip record's institutional net flows.
    A missing or empty ``chips`` yields the :data:`NO_DATA` notice rather than
    raising, so a symbol with no chip data still renders cleanly.

    Args:
        chips: Institutional net-flow rows for the symbol, any order. ``None``
            or empty means "no 籌碼面 data".

    Returns:
        A human-readable summary line, or :data:`NO_DATA`.
    """
    rows = list(chips) if chips else []
    if not rows:
        return NO_DATA

    latest = max(rows, key=lambda chip: chip.date)
    return (
        f"日期 {latest.date}｜外資 {latest.foreign_net}"
        f"｜投信 {latest.trust_net}｜自營商 {latest.dealer_net}"
    )


def fundamental_summary(fundamental: Fundamental | None) -> list[tuple[str, str]]:
    """Project a (possibly partial) ``Fundamental`` to labelled rows (AC-3).

    Every field in :data:`FUNDAMENTAL_FIELDS` is emitted in order; an absent
    value (``None``, or no ``Fundamental`` at all) renders as :data:`MISSING`
    rather than being guessed or dropped, so partial data shows what it has and
    marks the gaps.

    Args:
        fundamental: The symbol's fundamental snapshot, or ``None`` when none is
            cached.

    Returns:
        ``(label, value)`` pairs in :data:`FUNDAMENTAL_FIELDS` order.
    """
    return [
        (label, _fmt(getattr(fundamental, attr, None)))
        for label, attr in FUNDAMENTAL_FIELDS
    ]


def _num(value: float) -> str:
    """Render a price as a compact string, dropping trailing ``.0`` noise."""
    return f"{value:g}"


def _fmt(value: object) -> str:
    """Render a fundamental value, mapping ``None`` to :data:`MISSING` (AC-3)."""
    if value is None:
        return MISSING
    if isinstance(value, float):
        return _num(value)
    return str(value)


class DetailApp(App):
    """Individual-stock detail screen: 30-day OHLCV + 籌碼/基本面 summaries.

    Renders an injected :class:`StockDetail`; it owns no storage logic and
    defines no bespoke colour system, relying on Textual's default theme.
    """

    TITLE = "tsic"
    SUB_TITLE = "個股詳細"

    def __init__(self, detail: StockDetail) -> None:
        """Build the screen over one symbol's cached detail.

        Args:
            detail: The OHLCV/chip/fundamental data this screen renders.
        """
        super().__init__()
        self._detail = detail

    def compose(self) -> ComposeResult:
        """Lay out the header, OHLCV table, summary panels, and footer."""
        yield Header()
        yield DataTable(id=OHLCV_TABLE_ID)
        yield Static(id=CHIP_SUMMARY_ID)
        yield Static(id=FUNDAMENTAL_SUMMARY_ID)
        yield Footer()

    def on_mount(self) -> None:
        """Populate the OHLCV table and the 籌碼/基本面 summary panels."""
        table = self.query_one(f"#{OHLCV_TABLE_ID}", DataTable)
        table.add_columns(*OHLCV_COLUMNS)
        for row in ohlcv_rows(self._detail.prices):
            table.add_row(*row)

        chips = self.query_one(f"#{CHIP_SUMMARY_ID}", Static)
        chips.update(f"籌碼面：{chip_summary(self._detail.chips)}")

        lines = ["基本面："]
        lines += [
            f"{label}：{value}"
            for label, value in fundamental_summary(self._detail.fundamental)
        ]
        self.query_one(f"#{FUNDAMENTAL_SUMMARY_ID}", Static).update("\n".join(lines))
