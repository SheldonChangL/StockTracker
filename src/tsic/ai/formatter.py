"""Structured Markdown formatter and the default analysis prompt (Story 5.2).

Before tsic hands cached data to an external AI CLI it must shape that data into
something an LLM can read reliably. This module is that presentation layer for
the AI path (FR-31/FR-32/FR-33):

* :func:`to_markdown` renders a symbol's :class:`~tsic.models.DailyPrice` rows
  (and, when available, their :class:`~tsic.models.ChipFlow` rows) into a
  headed Markdown document — a stock-symbol/query-range header followed by a
  Markdown table whose columns are 日期 / OHLCV / 籌碼面 (AC-1). When no chip
  data is supplied the 籌碼面 columns are simply omitted rather than padded with
  blanks, so a prices-only render never errors (AC-4).
* :func:`build_prompt` returns the analysis instruction sent alongside the
  table. By default it is :data:`DEFAULT_PROMPT_TEMPLATE` with ``{代號}``
  substituted for the real symbol (AC-2); a caller-supplied override (the CLI's
  ``--prompt``) is used verbatim instead (AC-3).

This module is a pure prerequisite: it only *produces* strings. Wiring it into
the ``tsic analyze`` command is left to a later story.
"""

from __future__ import annotations

from collections.abc import Sequence

from tsic.models import ChipFlow, DailyPrice

#: Default analysis instruction. ``{代號}`` is replaced with the real symbol by
#: :func:`build_prompt` unless the caller overrides the whole prompt (AC-2).
DEFAULT_PROMPT_TEMPLATE = (
    "請分析以下台灣股票 {代號} 近期走勢，包含技術面觀察與籌碼面變化，並給出簡要看法。"
)

#: The placeholder inside :data:`DEFAULT_PROMPT_TEMPLATE` swapped for the symbol.
_SYMBOL_PLACEHOLDER = "{代號}"

#: Price-side table columns, fixed order: 日期 + OHLCV (AC-1).
_PRICE_HEADERS: tuple[str, ...] = ("日期", "開盤", "最高", "最低", "收盤", "成交量")

#: Chip-side (籌碼面) table columns, appended only when chip data exists (AC-1/AC-4).
_CHIP_HEADERS: tuple[str, ...] = ("外資", "投信", "自營商")

#: Rendered when a price row has no matching chip record for its date.
_MISSING_CELL = "—"


def build_prompt(symbol: str, override: str | None = None) -> str:
    """Return the analysis prompt for ``symbol`` (FR-32).

    Args:
        symbol: Taiwan stock symbol, e.g. ``"2330"``.
        override: A caller-supplied prompt (the CLI ``--prompt`` value). When
            given it is returned verbatim (AC-3); when ``None`` the default
            template is used with ``{代號}`` replaced by ``symbol`` (AC-2).

    Returns:
        The prompt string to send to the AI CLI.
    """
    if override is not None:
        return override
    return DEFAULT_PROMPT_TEMPLATE.replace(_SYMBOL_PLACEHOLDER, symbol)


def to_markdown(
    symbol: str,
    prices: Sequence[DailyPrice],
    chips: Sequence[ChipFlow] | None = None,
    *,
    start: str | None = None,
    end: str | None = None,
) -> str:
    """Render ``symbol`` price/chip data as a headed Markdown document (FR-31).

    The output is a header carrying the stock symbol and the inclusive query
    range, followed by a Markdown table with one row per trading day (AC-1).
    Chip (籌碼面) columns are appended only when ``chips`` is non-empty; with no
    chip data the table drops those columns entirely and never raises (AC-4).

    Args:
        symbol: The stock symbol the data belongs to.
        prices: Daily OHLCV rows, expected in ascending date order.
        chips: Institutional net-flow rows matched to price rows by ``date``.
            ``None`` or empty means "no 籌碼面 data" — the chip columns are
            omitted (AC-4).
        start: Inclusive range start for the header. Defaults to the earliest
            price date when omitted.
        end: Inclusive range end for the header. Defaults to the latest price
            date when omitted.

    Returns:
        The Markdown document as a string, terminated by a trailing newline.
    """
    price_rows = list(prices)
    chip_rows = list(chips) if chips else []
    has_chips = bool(chip_rows)
    chip_by_date = {chip.date: chip for chip in chip_rows}

    dates = [row.date for row in price_rows]
    range_start = start if start is not None else (min(dates) if dates else "")
    range_end = end if end is not None else (max(dates) if dates else "")

    headers = list(_PRICE_HEADERS) + (list(_CHIP_HEADERS) if has_chips else [])

    lines = [
        f"# 台灣股票 {symbol} 近期走勢資料",
        "",
        f"- 股票代號：{symbol}",
        f"- 查詢區間：{range_start} ~ {range_end}",
        "",
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]

    for row in price_rows:
        cells = [
            row.date,
            _num(row.open),
            _num(row.high),
            _num(row.low),
            _num(row.close),
            str(row.volume),
        ]
        if has_chips:
            chip = chip_by_date.get(row.date)
            if chip is None:
                cells += [_MISSING_CELL, _MISSING_CELL, _MISSING_CELL]
            else:
                cells += [
                    str(chip.foreign_net),
                    str(chip.trust_net),
                    str(chip.dealer_net),
                ]
        lines.append("| " + " | ".join(cells) + " |")

    return "\n".join(lines) + "\n"


def _num(value: float) -> str:
    """Render a price as a compact string, dropping trailing ``.0`` noise."""
    return f"{value:g}"
