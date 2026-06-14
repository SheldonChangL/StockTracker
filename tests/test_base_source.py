"""Tests for the BaseSource contract and per-source bucket (Story 3.1)."""

from __future__ import annotations

import pytest

from tsic.models import ChipFlow, DailyPrice, Fundamental
from tsic.ratelimit.token_bucket import TokenBucket
from tsic.sources.base import BaseSource


class FakeSource(BaseSource):
    """Minimal concrete source used to exercise the interface."""

    name = "fake"
    priority = 1
    concurrency = 2
    rate_limit = 1.0

    def fetch_prices(self, symbol: str, start: str, end: str) -> list[DailyPrice]:
        return [DailyPrice(symbol=symbol, date=start, close=1.0, source=self.name)]

    def fetch_chips(self, symbol: str, start: str, end: str) -> list[ChipFlow]:
        return [ChipFlow(symbol=symbol, date=start, source=self.name)]

    def fetch_fundamentals(
        self, symbol: str, start: str, end: str
    ) -> list[Fundamental]:
        return [Fundamental(symbol=symbol, date=start, source=self.name)]


def test_concrete_source_exposes_config_and_fetch_methods() -> None:
    # AC-1: name/priority/concurrency/rate_limit + the three fetch methods.
    source = FakeSource()

    assert source.name == "fake"
    assert source.priority == 1
    assert source.concurrency == 2
    assert source.rate_limit == 1.0

    assert source.fetch_prices("2330", "2026-06-10", "2026-06-10")[0].symbol == "2330"
    assert source.fetch_chips("2330", "2026-06-10", "2026-06-10")[0].symbol == "2330"
    fundamentals = source.fetch_fundamentals("2330", "2026-06-10", "2026-06-10")
    assert fundamentals[0].symbol == "2330"


def test_incomplete_source_cannot_be_instantiated() -> None:
    # AC-1: the interface is enforced — a subclass missing parts is abstract.
    class Incomplete(BaseSource):
        name = "incomplete"
        # missing priority/concurrency/rate_limit and the fetch methods

    with pytest.raises(TypeError):
        Incomplete()  # type: ignore[abstract]


def test_bucket_is_shared_per_source_instance() -> None:
    # AC-4: every task driven through one source shares the same bucket.
    source = FakeSource()

    assert source.bucket is source.bucket
    assert isinstance(source.bucket, TokenBucket)
    assert source.bucket.rate == source.rate_limit


def test_distinct_sources_have_distinct_buckets() -> None:
    # AC-4 corollary: per-source, not global — two sources don't share a bucket.
    assert FakeSource().bucket is not FakeSource().bucket
