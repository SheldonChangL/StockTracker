"""Tests for the ``tsic analyze`` command (Story 5.4, AC-1..AC-3).

These drive the *real* CLI entry point (``tsic.commandline.app.app``) end to
end. The happy path injects a fake AI CLI via ``--agent cat`` — a real echo
subprocess — so the assembled Markdown payload comes straight back on stdout
without depending on any installed LLM (AC-1). The "no AI CLI" path forces
detection to fail by monkeypatching the resolver (AC-2).
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tsic.commandline import analyze_cmd
from tsic.commandline.app import app
from tsic.storage import database, migrations
from tsic.storage.repository import PriceRepository
from tsic.models import DailyPrice

runner = CliRunner()


def _seed(path: Path, symbol: str = "2330", dates: tuple[str, ...] = ()) -> None:
    """Insert one daily-price row per date for ``symbol`` into ``path``."""
    conn = database.connect(path)
    try:
        migrations.migrate(conn)
        PriceRepository(conn).upsert_prices(
            [
                DailyPrice(
                    symbol=symbol, date=day, open=1000.0, high=1010.0,
                    low=995.0, close=1005.0, volume=12000, source="twse",
                    adjusted=0,
                )
                for day in dates
            ]
        )
    finally:
        conn.close()


# AC-1: with cached data and an injected echo CLI, the Markdown payload (header +
# table) is piped to the agent, echoed back on stdout, and the command exits 0.
def test_analyze_pipes_markdown_to_agent_and_exits_zero(tmp_path: Path) -> None:
    db_path = tmp_path / "t.db"
    _seed(db_path, "2330", dates=("2026-06-01", "2026-06-02"))

    result = runner.invoke(
        app, ["analyze", "2330", "--agent", "cat", "--db", str(db_path)]
    )

    assert result.exit_code == 0
    # The fake CLI echoed the payload: the header and a Markdown table are present.
    assert "台灣股票 2330" in result.stdout
    assert "查詢區間：2026-06-01 ~ 2026-06-02" in result.stdout
    for col in ("日期", "開盤", "最高", "最低", "收盤", "成交量"):
        assert col in result.stdout
    assert "| 2026-06-01 |" in result.stdout
    assert "| 2026-06-02 |" in result.stdout
    # The default analysis prompt rode along with the table.
    assert "請分析以下台灣股票 2330" in result.stdout


# AC-1 corollary: an explicit --prompt overrides the default instruction.
def test_analyze_uses_prompt_override(tmp_path: Path) -> None:
    db_path = tmp_path / "t.db"
    _seed(db_path, "2330", dates=("2026-06-01",))

    result = runner.invoke(
        app,
        ["analyze", "2330", "--agent", "cat", "--prompt", "只看技術面。",
         "--db", str(db_path)],
    )

    assert result.exit_code == 0
    assert "只看技術面。" in result.stdout
    assert "請分析以下台灣股票" not in result.stdout


# AC-2: no --agent and no AI CLI on PATH exits 3 with install + --agent guidance.
def test_analyze_no_agent_exits_three(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_path = tmp_path / "t.db"
    _seed(db_path, "2330", dates=("2026-06-01",))
    # Force "no AI CLI detected" regardless of what is installed on the host.
    monkeypatch.setattr(analyze_cmd, "resolve_agent_command", lambda override: None)

    result = runner.invoke(app, ["analyze", "2330", "--db", str(db_path)])

    assert result.exit_code == 3
    assert "找不到可用的 AI CLI" in result.stdout
    assert "--agent" in result.stdout
    # Names every auto-detected CLI so the user knows what to install.
    for name in ("claude", "openai", "llm"):
        assert name in result.stdout


# AC-2 guard: exit 3 happens before any DB read, so a missing db is irrelevant.
def test_analyze_no_agent_fails_fast_before_db(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(analyze_cmd, "resolve_agent_command", lambda override: None)

    result = runner.invoke(
        app, ["analyze", "2330", "--db", str(tmp_path / "missing.db")]
    )

    assert result.exit_code == 3


# A symbol with no cached rows prints a notice and exits 2 (mirrors query).
def test_analyze_no_data_exits_two(tmp_path: Path) -> None:
    db_path = tmp_path / "t.db"
    _seed(db_path, "2330", dates=("2026-06-01",))

    result = runner.invoke(
        app, ["analyze", "9999", "--agent", "cat", "--db", str(db_path)]
    )

    assert result.exit_code == 2
    assert "無資料" in result.stdout


# AC-3: a cached analyze reaches the AI pipe well within the 5s budget (NFR-5).
def test_analyze_completes_within_budget(tmp_path: Path) -> None:
    db_path = tmp_path / "t.db"
    _seed(db_path, "2330", dates=tuple(f"2026-06-{d:02d}" for d in range(1, 29)))

    started = time.perf_counter()
    result = runner.invoke(
        app, ["analyze", "2330", "--agent", "cat", "--db", str(db_path)]
    )
    elapsed = time.perf_counter() - started

    assert result.exit_code == 0
    assert elapsed < 5.0
