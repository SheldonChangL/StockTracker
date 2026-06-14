"""Pluggable market-data sources (Story 3.1)."""

from __future__ import annotations

from tsic.sources.base import BaseSource
from tsic.sources.fugle_source import FugleSource
from tsic.sources.mops_source import MopsSource
from tsic.sources.twse_source import TwseSource
from tsic.sources.yfinance_source import SourceFetchError, YfinanceSource

__all__ = [
    "BaseSource",
    "FugleSource",
    "MopsSource",
    "SourceFetchError",
    "TwseSource",
    "YfinanceSource",
]
