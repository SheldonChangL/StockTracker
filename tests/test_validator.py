"""Tests for the write-time price validator (Story 2.3, FR-13)."""

from __future__ import annotations

import logging

from tsic.fetching import validator
from tsic.models import DailyPrice


def _good_price(**overrides: object) -> DailyPrice:
    """A baseline valid record; override individual fields per test."""
    base = dict(
        symbol="2330",
        date="2026-06-12",
        open=100.0,
        high=105.0,
        low=99.0,
        close=104.0,
        volume=1000,
        source="test",
        adjusted=0,
    )
    base.update(overrides)
    return DailyPrice(**base)  # type: ignore[arg-type]


def test_valid_record_passes() -> None:
    result = validator.validate_price(_good_price())
    assert result.valid is True
    assert result.reasons == []


def test_invalid_date_is_rejected() -> None:
    """AC-1: an impossible date is invalid and reports a reason."""
    result = validator.validate_price(_good_price(date="2026-13-40"))
    assert result.valid is False
    assert any("date" in r for r in result.reasons)
    assert result.reason  # non-empty human-readable reason


def test_negative_open_is_rejected() -> None:
    """AC-2: a negative open price is invalid."""
    result = validator.validate_price(_good_price(open=-1))
    assert result.valid is False
    assert any("open" in r for r in result.reasons)


def test_negative_volume_is_rejected() -> None:
    """AC-2: a negative volume is invalid."""
    result = validator.validate_price(_good_price(volume=-5))
    assert result.valid is False
    assert any("volume" in r for r in result.reasons)


def test_zero_close_is_rejected() -> None:
    """AC-3: a zero close price is invalid (close must be > 0)."""
    result = validator.validate_price(_good_price(close=0))
    assert result.valid is False
    assert any("close" in r for r in result.reasons)


def test_negative_close_is_rejected() -> None:
    """AC-2/AC-3: a negative close fails both non-negative and >0 rules."""
    result = validator.validate_price(_good_price(close=-2))
    assert result.valid is False
    assert any("close" in r for r in result.reasons)


def test_batch_returns_valid_list_and_one_warning_per_invalid(
    caplog: object,
) -> None:
    """AC-4: a mixed batch returns valid records + one warning per invalid."""
    prices = [
        _good_price(symbol="A", date="2026-06-10"),
        _good_price(symbol="B", date="2026-13-40"),  # invalid date
        _good_price(symbol="C", open=-1),  # invalid open
        _good_price(symbol="D", date="2026-06-11"),
        _good_price(symbol="E", close=0),  # invalid close
    ]

    with caplog.at_level(logging.WARNING):  # type: ignore[attr-defined]
        result = validator.validate_prices(prices)

    assert [p.symbol for p in result.valid] == ["A", "D"]
    assert len(result.warnings) == 3  # invalid count is assertable

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]  # type: ignore[attr-defined]
    assert len(warnings) == 3


def test_empty_batch_is_all_valid_no_warnings() -> None:
    result = validator.validate_prices([])
    assert result.valid == []
    assert result.warnings == []
