"""The pluggable data-source contract (Story 3.1, ADR-2; NFR-13).

Every upstream provider (TWSE, Fugle, yfinance, …) is modelled as a Strategy
implementing :class:`BaseSource`, so adding a new provider means writing one
class against this interface rather than touching call sites. Each source
declares its identity and operational budget (``name`` / ``priority`` /
``concurrency`` / ``rate_limit``) and the three fetch operations the rest of
the system consumes.

Rate limiting is *per source, not per task*: a source exposes a single shared
:class:`~tsic.ratelimit.token_bucket.TokenBucket` (lazily built from
``rate_limit`` and cached on the instance via :attr:`BaseSource.bucket`), so
every concurrent fetch task driven through one source instance contends for the
same token budget and the provider's request ceiling is honoured globally.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from functools import cached_property

from tsic.models import ChipFlow, DailyPrice, Fundamental
from tsic.ratelimit.token_bucket import TokenBucket


class BaseSource(ABC):
    """Strategy interface every market-data source must implement.

    Concrete sources declare four configuration values as abstract properties
    (so the interface is enforced at instantiation time) and implement the
    three fetch operations:

    * :attr:`name` — stable source identifier (e.g. ``"twse"``).
    * :attr:`priority` — selection order when several sources can serve a
      symbol; lower runs first.
    * :attr:`concurrency` — maximum simultaneous in-flight requests permitted
      for this source.
    * :attr:`rate_limit` — request ceiling in requests per second, used to size
      the shared :attr:`bucket`.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Stable, unique source identifier (e.g. ``"twse"``)."""

    @property
    @abstractmethod
    def priority(self) -> int:
        """Selection order across sources; lower priority runs first."""

    @property
    @abstractmethod
    def concurrency(self) -> int:
        """Maximum simultaneous in-flight requests allowed for this source."""

    @property
    @abstractmethod
    def rate_limit(self) -> float:
        """Request ceiling in requests per second (sizes :attr:`bucket`)."""

    @cached_property
    def bucket(self) -> TokenBucket:
        """The per-source shared rate limiter, built once from ``rate_limit``.

        Because this is a :func:`~functools.cached_property`, every access on a
        given source instance returns the *same* :class:`TokenBucket`, so all
        fetch tasks sharing the source share one token budget (per-source, not
        per-task). Distinct source instances get distinct buckets.
        """
        return TokenBucket(rate=self.rate_limit)

    @abstractmethod
    def fetch_prices(self, symbol: str, start: str, end: str) -> list[DailyPrice]:
        """Fetch OHLCV records for ``symbol`` within ``[start, end]``."""

    @abstractmethod
    def fetch_chips(self, symbol: str, start: str, end: str) -> list[ChipFlow]:
        """Fetch institutional net-flow records for ``symbol`` in range."""

    @abstractmethod
    def fetch_fundamentals(
        self, symbol: str, start: str, end: str
    ) -> list[Fundamental]:
        """Fetch fundamental snapshots for ``symbol`` within ``[start, end]``."""
