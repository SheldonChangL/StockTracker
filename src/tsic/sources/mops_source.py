"""MOPS quarterly fundamentals source (Story 3.6, §3 fundamentals; FR-8/OPS-6).

MOPS (公開資訊觀測站) is the *best-effort* fundamentals provider: it tries to
surface quarterly EPS / 本益比 / 營收 / 毛利率 for a symbol, but it is never on the
critical path. MOPS HTML is brittle and changes layout without notice, so the
contract here is deliberately forgiving (AC-2):

* A metric the page does not expose — or whose cell cannot be parsed — is left
  ``None`` on the :class:`~tsic.models.Fundamental` rather than guessed (AC-1).
* If the page itself is unfetchable or its structure is unrecognisable, the
  source logs **exactly one** warning and returns an empty list. It never
  raises and never interrupts the surrounding fetch (AC-2).

``pe_ratio_qtr_end`` is read straight from the page's 本益比 column and means the
**quarter-end P/E snapshot as MOPS reported it** — it is never recomputed from a
live price (AC-3).

Parsing is done with :mod:`lxml` (AC-1). Columns are resolved by *header label*
(substring match against the Chinese headers) rather than by fixed position, so
minor column reordering or relabelling on the MOPS page does not break the
parser. ``period`` is normalised to ``YYYYQn`` whether the page reports a
Gregorian quarter (``2026Q1``) or a Republic-of-China one (``115年第1季``).

The network call is injected (``fetch_fn``) so tests can drive the parser with a
static HTML fixture; the default issues a plain GET returning an object exposing
``status_code`` and ``text``.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import Any

import httpx
from lxml import html as lxml_html

from tsic.models import ChipFlow, DailyPrice, Fundamental
from tsic.sources.base import BaseSource

logger = logging.getLogger(__name__)

#: MOPS season-report base endpoint. The real page is form-driven; the exact URL
#: is irrelevant to parsing (``fetch_fn`` is injected in tests) but is built here
#: so the default network path targets a sensible location.
_BASE_URL = "https://mops.twse.com.tw/mops/web/t163sb04"

#: Difference between a Gregorian year and a Republic-of-China (民國) year.
_ROC_YEAR_OFFSET = 1911

#: Canonical field -> accepted header substrings. A header cell matches a field
#: when it *contains* any of the substrings, so decorated labels such as
#: "每股盈餘(元)" still resolve. ``period`` must resolve for a table to count as a
#: recognisable fundamentals table.
_HEADER_FIELDS: dict[str, tuple[str, ...]] = {
    "period": ("期別", "季別", "會計期間", "年度/季別"),
    "eps": ("每股盈餘",),
    "pe_ratio_qtr_end": ("本益比",),
    "revenue": ("營業收入", "營收"),
    "gross_margin": ("毛利率",),
}

#: Cell values that mean "no data" on MOPS and parse to ``None``.
_BLANK_CELLS = frozenset({"", "-", "--", "—", "N/A", "n/a", "不適用", "無"})


def _http_get(url: str) -> httpx.Response:
    """Default network call: a plain GET with a conservative timeout."""
    return httpx.get(url, timeout=30.0)


class MopsSource(BaseSource):
    """Best-effort quarterly fundamentals source backed by MOPS HTML.

    Only :meth:`fetch_fundamentals` is served; MOPS is not a price or
    institutional-flow provider, so the other two operations are out of scope.
    """

    name = "mops"
    #: Fundamentals-only source; ranks after the price/flow sources (§3).
    priority = 4
    #: MOPS is a government site — fetch gently, one request at a time.
    concurrency = 1
    #: One request per second sizes the shared bucket.
    rate_limit = 1.0

    def __init__(
        self,
        *,
        fetch_fn: Callable[[str], Any] = _http_get,
    ) -> None:
        self._fetch_fn = fetch_fn

    def fetch_prices(self, symbol: str, start: str, end: str) -> list[DailyPrice]:
        """Not provided by this story; prices come from other sources."""
        raise NotImplementedError("mops does not provide prices")

    def fetch_chips(self, symbol: str, start: str, end: str) -> list[ChipFlow]:
        """Not provided by this story; institutional flows come from TWSE."""
        raise NotImplementedError("mops does not provide institutional flows")

    def fetch_fundamentals(
        self, symbol: str, start: str, end: str
    ) -> list[Fundamental]:
        """Best-effort quarterly fundamentals for ``symbol`` from MOPS (AC-1/AC-2).

        Fetches the symbol's MOPS season report and parses every quarterly row it
        can recognise into a :class:`~tsic.models.Fundamental` with
        ``source="mops"``. Any individual missing/unparseable metric is left
        ``None`` (AC-1).

        This call is *non-fatal by contract*: a failed fetch, a non-200 response,
        or an unrecognisable page structure results in a single logged warning and
        an empty list — never an exception (AC-2).

        Args:
            symbol: Taiwan stock symbol, e.g. ``"2330"``.
            start: Inclusive ISO ``YYYY-MM-DD`` start date (used to scope the
                request; range filtering is best-effort).
            end: Inclusive ISO ``YYYY-MM-DD`` end date.

        Returns:
            One :class:`~tsic.models.Fundamental` per parsed quarter, or ``[]`` if
            nothing could be parsed.
        """
        self.bucket.acquire()
        try:
            url = f"{_BASE_URL}?co_id={symbol}&from={start}&to={end}"
            response = self._fetch_fn(url)
            status = getattr(response, "status_code", 200)
            if status != 200:
                raise _MopsParseError(f"MOPS returned HTTP {status}")
            return _parse_fundamentals(response.text, symbol)
        except Exception as error:  # noqa: BLE001 — best-effort: never propagate.
            logger.warning(
                "MOPS fundamentals for %s unavailable (%s); skipping", symbol, error
            )
            return []


class _MopsParseError(Exception):
    """Internal signal that the MOPS page structure was unrecognisable (AC-2)."""


def _parse_fundamentals(page: str, symbol: str) -> list[Fundamental]:
    """Parse a MOPS season-report HTML page into quarterly fundamentals.

    Locates the first table whose header row resolves a ``period`` column plus at
    least one metric column, then maps each data row to a
    :class:`~tsic.models.Fundamental`. Rows without a normalisable period are
    skipped. Raises :class:`_MopsParseError` when no such table exists so the
    caller can emit a single best-effort warning (AC-2).
    """
    root = lxml_html.fromstring(page)
    for table in root.xpath("//table"):
        rows = table.xpath(".//tr")
        if not rows:
            continue
        header = _header_map(rows[0])
        if "period" not in header:
            continue  # not a fundamentals table; try the next one.

        fundamentals: list[Fundamental] = []
        for row in rows[1:]:
            cells = [c.text_content().strip() for c in row.xpath("./td | ./th")]
            period = _normalise_period(_cell(cells, header, "period"))
            if period is None:
                continue  # spacer / total / non-data row.
            fundamentals.append(
                Fundamental(
                    symbol=symbol,
                    period=period,
                    eps=_to_float(_cell(cells, header, "eps")),
                    pe_ratio_qtr_end=_to_float(
                        _cell(cells, header, "pe_ratio_qtr_end")
                    ),
                    revenue=_to_float(_cell(cells, header, "revenue")),
                    gross_margin=_to_float(_cell(cells, header, "gross_margin")),
                    source="mops",
                )
            )
        return fundamentals

    raise _MopsParseError("no recognisable fundamentals table on page")


def _header_map(header_row: Any) -> dict[str, int]:
    """Map canonical field names to their column index from a header ``<tr>``.

    Each header cell is matched against :data:`_HEADER_FIELDS` by substring, so
    decorated labels (e.g. ``每股盈餘(元)``) still resolve. The first column that
    matches a field wins.
    """
    labels = [c.text_content().strip() for c in header_row.xpath("./th | ./td")]
    mapping: dict[str, int] = {}
    for index, label in enumerate(labels):
        for field, needles in _HEADER_FIELDS.items():
            if field not in mapping and any(needle in label for needle in needles):
                mapping[field] = index
    return mapping


def _cell(cells: list[str], header: dict[str, int], field: str) -> str | None:
    """Return the raw cell text for ``field`` in ``cells``, or ``None`` if absent."""
    index = header.get(field)
    if index is None or index >= len(cells):
        return None
    return cells[index]


def _to_float(raw: str | None) -> float | None:
    """Parse a MOPS numeric cell to ``float``, or ``None`` when blank/unparseable.

    Thousands separators are stripped and recognised blank markers map to
    ``None``. An unparseable value is treated as missing (``None``) rather than an
    error — per the best-effort contract (AC-1), a bad cell never fails the row.
    """
    if raw is None:
        return None
    text = raw.strip().replace(",", "")
    if text in _BLANK_CELLS:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _normalise_period(raw: str | None) -> str | None:
    """Normalise a MOPS period label to ``YYYYQn``, or ``None`` if unrecognised.

    Accepts Gregorian forms (``2026Q1``, ``2026 Q1``, ``2026/Q1``) and
    Republic-of-China forms (``115年第1季``), converting民國 years to Gregorian.
    """
    if raw is None:
        return None
    text = raw.strip()

    # Gregorian "2026Q1" / "2026 Q1" / "2026/Q1".
    gregorian = re.search(r"(\d{4})\s*[/\s]?\s*[Qq]\s*([1-4])", text)
    if gregorian:
        return f"{gregorian.group(1)}Q{gregorian.group(2)}"

    # Gregorian "2026年第1季" — matched before the ROC form so a 4-digit year is
    # never mistaken for a (2-3 digit) 民國 year.
    cjk = re.search(r"(\d{4})\s*年\s*第?\s*([1-4])\s*季", text)
    if cjk:
        return f"{cjk.group(1)}Q{cjk.group(2)}"

    # Republic-of-China "115年第1季". The lookbehind stops it grabbing the tail
    # of a longer number.
    roc = re.search(r"(?<!\d)(\d{2,3})\s*年\s*第?\s*([1-4])\s*季", text)
    if roc:
        year = int(roc.group(1)) + _ROC_YEAR_OFFSET
        return f"{year}Q{roc.group(2)}"

    return None
