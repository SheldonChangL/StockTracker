"""Tests for the shared dataclass models."""

from dataclasses import fields, is_dataclass

from tsic.models import ChipFlow, DailyPrice, FetchResult, Fundamental


def test_models_are_dataclasses() -> None:
    for model in (DailyPrice, ChipFlow, Fundamental, FetchResult):
        assert is_dataclass(model)


def test_daily_price_field_names() -> None:
    names = [f.name for f in fields(DailyPrice)]
    assert names == [
        "symbol",
        "date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "source",
        "adjusted",
    ]


def test_daily_price_field_types() -> None:
    # AC-2: construct with only adjusted, then verify runtime types.
    price = DailyPrice(adjusted=0)
    assert isinstance(price.open, float)
    assert isinstance(price.high, float)
    assert isinstance(price.low, float)
    assert isinstance(price.close, float)
    assert isinstance(price.volume, int)
    assert isinstance(price.adjusted, int)
    assert isinstance(price.symbol, str)
    assert isinstance(price.source, str)
