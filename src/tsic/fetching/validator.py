"""Write-time validation for fetched price records (Story 2.3, FR-13).

This module is the last gate before a :class:`~tsic.models.DailyPrice` is
persisted to the local cache. Malformed or out-of-range records are rejected
here so the cache never feeds corrupt data to downstream AI analysis.

Validation rules (per the acceptance criteria):

* ``date`` must be a real calendar date in ISO ``YYYY-MM-DD`` form.
* All OHLCV values (``open``, ``high``, ``low``, ``close``, ``volume``) must be
  non-negative.
* ``close`` must be strictly positive (a zero close price is meaningless and
  signals a bad fetch).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

from tsic.models import DailyPrice

logger = logging.getLogger(__name__)

#: OHLCV fields that must be non-negative.
_NON_NEGATIVE_FIELDS = ("open", "high", "low", "close", "volume")


@dataclass(frozen=True)
class ValidationResult:
    """Outcome of validating a single :class:`~tsic.models.DailyPrice`.

    ``reasons`` lists every rule the record violated; it is empty when the
    record is valid. ``valid`` is derived from it.
    """

    valid: bool
    reasons: list[str] = field(default_factory=list)

    @property
    def reason(self) -> str:
        """A single human-readable string joining all rejection reasons."""
        return "; ".join(self.reasons)


@dataclass(frozen=True)
class BatchValidation:
    """Outcome of validating a batch of records.

    ``valid`` holds the records that passed; ``warnings`` holds exactly one
    message per rejected record, so ``len(warnings)`` is the invalid count.
    """

    valid: list[DailyPrice] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _is_valid_date(value: str) -> bool:
    """Return ``True`` if ``value`` is a real ISO ``YYYY-MM-DD`` calendar date."""
    try:
        date.fromisoformat(value)
    except (ValueError, TypeError):
        return False
    return True


def validate_price(price: DailyPrice) -> ValidationResult:
    """Validate one OHLCV record against the write-time rules.

    Args:
        price: The record to check.

    Returns:
        A :class:`ValidationResult`. When invalid, ``reasons`` explains every
        rule that failed.
    """
    reasons: list[str] = []

    if not _is_valid_date(price.date):
        reasons.append(f"invalid date: {price.date!r} is not a valid YYYY-MM-DD date")

    for name in _NON_NEGATIVE_FIELDS:
        value = getattr(price, name)
        if value < 0:
            reasons.append(f"{name} must be >= 0, got {value}")

    if price.close <= 0:
        reasons.append(f"close must be > 0, got {price.close}")

    return ValidationResult(valid=not reasons, reasons=reasons)


def validate_prices(prices: list[DailyPrice]) -> BatchValidation:
    """Validate a batch, returning the valid records plus per-record warnings.

    Each invalid record yields exactly one warning (its reasons joined) which
    is both returned and logged for observability.

    Args:
        prices: The records to check.

    Returns:
        A :class:`BatchValidation` whose ``valid`` list preserves input order
        and whose ``warnings`` has one entry per rejected record.
    """
    valid: list[DailyPrice] = []
    warnings: list[str] = []

    for price in prices:
        result = validate_price(price)
        if result.valid:
            valid.append(price)
            continue

        warning = (
            f"Rejected {price.symbol or '<unknown>'} {price.date}: {result.reason}"
        )
        warnings.append(warning)
        logger.warning(warning)

    return BatchValidation(valid=valid, warnings=warnings)
