"""Tests for the ``tsic fetch`` command (Story 3.8, AC-1..AC-5).

These drive the *real* CLI entry point (``tsic.commandline.app.app``) end to
end, swapping the network-backed sources for an in-process ``FakeSource``
(loopback) by monkeypatching :func:`tsic.commandline.fetch_cmd._default_sources`.
No test touches the network.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from tsic.commandline import fetch_cmd
from tsic.commandline.app import app
from tsic.models import ChipFlow, DailyPrice, Fundamental
from tsic.sources.base import BaseSource
from tsic.storage import database, migrations, repository

runner = CliRunner()


class FakeSource(BaseSource):
    """In-process loopback source: returns one row per symbol, no network.

    A symbol listed in ``fail`` (or any symbol when ``fail_all`` is set) raises,
    exercising the failure paths; every other symbol yields a single
    ``DailyPrice`` dated at the requested ``start`` so a fresh DB always sees a
    write. Calls are recorded so tests can assert which symbols were fetched.
    """

    name = "fake"
    priority = 1
    concurrency = 1
    rate_limit = 1.0

    def __init__(
        self, *, fail: tuple[str, ...] = (), fail_all: bool = False
    ) -> None:
        self._fail = set(fail)
        self._fail_all = fail_all
        self.calls: list[str] = []

    def fetch_prices(self, symbol: str, start: str, end: str) -> list[DailyPrice]:
        self.calls.append(symbol)
        if self._fail_all or symbol in self._fail:
            raise RuntimeError(f"source down for {symbol}")
        return [
            DailyPrice(
                symbol=symbol, date=start, open=1.0, high=1.0, low=1.0,
                close=1.0, volume=1, source=self.name, adjusted=0,
            )
        ]

    def fetch_chips(self, symbol: str, start: str, end: str) -> list[ChipFlow]:
        raise NotImplementedError

    def fetch_fundamentals(
        self, symbol: str, start: str, end: str
    ) -> list[Fundamental]:
        raise NotImplementedError


def _inject(monkeypatch: pytest.MonkeyPatch, source: FakeSource) -> None:
    """Replace the real source factory with one returning ``source``."""
    monkeypatch.setattr(fetch_cmd, "_default_sources", lambda: [source])


def _stored_count(db_path: Path, symbol: str) -> int:
    conn = database.connect(db_path)
    try:
        rows = repository.PriceRepository(conn).query_prices(
            symbol, "2000-01-01", "2999-12-31"
        )
        return len(rows)
    finally:
        conn.close()


# AC-1: a single symbol fetched via the real CLI writes the db and exits 0.
def test_fetch_single_symbol_writes_db_and_reports_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_path = tmp_path / "t.db"
    _inject(monkeypatch, FakeSource())

    result = runner.invoke(
        app,
        ["fetch", "2330", "--db", str(db_path), "--start", "2026-06-01",
         "--end", "2026-06-30"],
    )

    assert result.exit_code == 0
    assert "成功 1" in result.stdout
    assert db_path.exists()
    assert _stored_count(db_path, "2330") == 1


# AC-2: a batch where one symbol fails still succeeds on the other; the summary
# shows both counts plus the failure reason; the batch exit code stays 0.
def test_batch_partial_failure_reports_both_and_exits_zero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_path = tmp_path / "t.db"
    _inject(monkeypatch, FakeSource(fail=("2317",)))

    result = runner.invoke(
        app,
        ["fetch", "2330", "2317", "--db", str(db_path),
         "--start", "2026-06-01", "--end", "2026-06-30"],
    )

    assert result.exit_code == 0
    assert "成功 1" in result.stdout
    assert "失敗 1" in result.stdout
    assert "2317" in result.stdout  # the failing symbol is named
    assert "source down for 2317" in result.stdout  # with its reason
    assert _stored_count(db_path, "2330") == 1
    assert _stored_count(db_path, "2317") == 0


# AC-3: when every symbol fails the command exits 1.
def test_all_symbols_fail_exits_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_path = tmp_path / "t.db"
    _inject(monkeypatch, FakeSource(fail_all=True))

    result = runner.invoke(
        app,
        ["fetch", "2330", "2317", "--db", str(db_path),
         "--start", "2026-06-01", "--end", "2026-06-30"],
    )

    assert result.exit_code == 1
    assert "失敗 2" in result.stdout


# AC-4: --file reads one symbol per line and fetches each.
def test_fetch_from_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_path = tmp_path / "t.db"
    watchlist = tmp_path / "watchlist.txt"
    watchlist.write_text("2330\n2317\n\n", encoding="utf-8")
    source = FakeSource()
    _inject(monkeypatch, source)

    result = runner.invoke(
        app,
        ["fetch", "--file", str(watchlist), "--db", str(db_path),
         "--start", "2026-06-01", "--end", "2026-06-30"],
    )

    assert result.exit_code == 0
    assert "成功 2" in result.stdout
    assert sorted(source.calls) == ["2317", "2330"]


# AC-4: --all fetches every symbol already tracked in the db.
def test_fetch_all_tracked_symbols(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_path = tmp_path / "t.db"
    # Seed an existing tracked symbol with one stored row.
    conn = database.connect(db_path)
    try:
        migrations.migrate(conn)
        repository.PriceRepository(conn).upsert_prices(
            [DailyPrice(symbol="2454", date="2026-06-10", open=1.0, high=1.0,
                        low=1.0, close=1.0, volume=1, source="seed", adjusted=0)]
        )
    finally:
        conn.close()

    source = FakeSource()
    _inject(monkeypatch, source)

    result = runner.invoke(
        app, ["fetch", "--all", "--db", str(db_path), "--end", "2026-06-30"]
    )

    assert result.exit_code == 0
    assert source.calls == ["2454"]  # the tracked symbol was fetched
    assert "成功 1" in result.stdout


# AC-5: --concurrency above the ceiling is clamped to _MAX_CONCURRENCY.
def test_concurrency_is_clamped_to_max(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_path = tmp_path / "t.db"
    _inject(monkeypatch, FakeSource())

    captured: dict[str, int] = {}
    real_orchestrator = fetch_cmd.FetchOrchestrator

    class SpyOrchestrator(real_orchestrator):  # type: ignore[misc, valid-type]
        def __init__(self, sources, repo, *, concurrency=3, **kwargs):
            captured["concurrency"] = concurrency
            super().__init__(sources, repo, concurrency=concurrency, **kwargs)

    monkeypatch.setattr(fetch_cmd, "FetchOrchestrator", SpyOrchestrator)

    result = runner.invoke(
        app,
        ["fetch", "2330", "--db", str(db_path), "--concurrency", "12",
         "--start", "2026-06-01", "--end", "2026-06-30"],
    )

    assert result.exit_code == 0
    assert captured["concurrency"] == fetch_cmd._MAX_CONCURRENCY == 10


def test_clamp_concurrency_helper() -> None:
    assert fetch_cmd._clamp_concurrency(12) == 10
    assert fetch_cmd._clamp_concurrency(5) == 5
    assert fetch_cmd._clamp_concurrency(0) == 1


# No symbols supplied at all is a usage error (exit 1) with guidance.
def test_no_symbols_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_path = tmp_path / "t.db"
    _inject(monkeypatch, FakeSource())

    result = runner.invoke(app, ["fetch", "--db", str(db_path)])

    assert result.exit_code == 1
    assert "未指定任何代號" in result.stdout
