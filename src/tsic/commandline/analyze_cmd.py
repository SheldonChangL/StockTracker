"""The ``tsic analyze`` command: cache → Markdown → AI CLI (Story 5.4).

This is the *vertical* entry point that turns ``tsic analyze 2330`` into a real
analysis run, stitching together the four prerequisite seams built in Story 5.x:

* :func:`tsic.ai.detector.detect` (via :func:`resolve_agent_command`, Story 5.1)
  picks an installed AI CLI unless ``--agent`` overrides it (FR-20/FR-34).
* :func:`tsic.ai.formatter.to_markdown` / :func:`~tsic.ai.formatter.build_prompt`
  (Story 5.2) shape the cached rows into a headed Markdown table plus the
  analysis instruction (FR-31/FR-32).
* :class:`~tsic.storage.repository.PriceRepository` (Story 2.4) reads the cached
  prices — no network — so the pipe starts well within the NFR-5 budget (AC-3).
* :func:`tsic.ai.pipe.run` (Story 5.3) feeds the assembled payload to the AI CLI
  on its stdin and returns its stdout verbatim (FR-21/FR-35, AC-1).

Exit code follows the outcome: a successful pipe prints the AI's stdout and
exits ``0`` (AC-1); a symbol with no cached rows prints a notice and exits ``2``
(mirroring ``tsic query``); and when no AI CLI is detected and ``--agent`` was
not supplied the command prints install guidance and exits ``3`` (AC-2).

``resolve_agent_command``, ``run``, ``to_markdown``, and ``build_prompt`` are
imported at module scope so tests can substitute fakes (e.g. force "no AI CLI")
while the happy path drives the real subprocess against an injected echo command
such as ``--agent cat`` (AC-1).
"""

from __future__ import annotations

from pathlib import Path

import typer

from tsic.ai.detector import CLI_PRIORITY
from tsic.ai.formatter import build_prompt, to_markdown
from tsic.ai.pipe import resolve_agent_command, run
from tsic.storage import database, migrations
from tsic.storage.repository import ChipRepository, PriceRepository

#: Default inclusive range bounds when ``--start`` / ``--end`` are omitted. ISO
#: date strings compare lexically, so these sentinels select every stored row;
#: they are also how the command knows the range was *not* set and lets the
#: formatter derive the header range from the data instead.
_MIN_DATE = "0001-01-01"
_MAX_DATE = "9999-12-31"

#: Exit code when no AI CLI is detected and ``--agent`` was not supplied (AC-2).
_NO_AGENT_EXIT = 3

#: Exit code when the symbol has no cached rows (mirrors ``tsic query``).
_NO_DATA_EXIT = 2


def _no_agent_message() -> str:
    """Guidance shown when no AI CLI is found and ``--agent`` is absent (AC-2).

    Names the AI CLIs tsic auto-detects (in preference order) and shows the
    ``--agent`` escape hatch so the user can point tsic at any other CLI.
    """
    known = "、".join(CLI_PRIORITY)
    return (
        "找不到可用的 AI CLI。\n"
        f"請安裝下列其中一個（偵測順序）：{known}，\n"
        "或以 --agent 指定要使用的命令，例如：\n"
        '  tsic analyze 2330 --agent "ollama run llama3"\n'
        '  tsic analyze 2330 --agent claude'
    )


def analyze(
    symbol: str = typer.Argument(..., help="股票代號（例如 2330）。"),
    db_path: Path | None = typer.Option(
        None,
        "--db",
        "--db-path",
        help="覆寫資料庫路徑（預設 ~/.tsic/data.db）。",
    ),
    start: str = typer.Option(
        _MIN_DATE, "--start", help="分析區間起始日（ISO YYYY-MM-DD，含當日）。"
    ),
    end: str = typer.Option(
        _MAX_DATE, "--end", help="分析區間結束日（ISO YYYY-MM-DD，含當日）。"
    ),
    agent: str | None = typer.Option(
        None,
        "--agent",
        help='指定要使用的 AI CLI 命令（例如 "ollama run llama3"）；未指定時自動偵測。',
    ),
    prompt: str | None = typer.Option(
        None, "--prompt", help="覆寫預設分析提示。"
    ),
) -> None:
    """Send SYMBOL's cached data to an AI CLI and print the analysis (FR-20/21).

    Reads from the local cache only — no network — then pipes a headed Markdown
    table plus the analysis prompt to the resolved AI CLI on its stdin and
    echoes the CLI's stdout verbatim (AC-1). With no AI CLI installed and no
    ``--agent`` override, prints install guidance and exits ``3`` (AC-2).
    """
    # Resolve the AI CLI first so a missing-agent run fails fast (exit 3) before
    # any database work (AC-2).
    agent_cmd = resolve_agent_command(agent)
    if agent_cmd is None:
        typer.echo(_no_agent_message())
        raise typer.Exit(code=_NO_AGENT_EXIT)

    conn = database.connect(db_path)
    try:
        migrations.migrate(conn)
        rows = PriceRepository(conn).query_prices(symbol, start, end)
        chips = ChipRepository(conn).query_chips(symbol, start, end)
    finally:
        conn.close()

    if not rows:
        typer.echo(f"無資料：{symbol} 在指定區間內沒有任何記錄。")
        raise typer.Exit(code=_NO_DATA_EXIT)

    # Only forward an explicitly-set range to the header; the sentinels mean
    # "unset", so let the formatter derive the range from the data instead.
    header_start = start if start != _MIN_DATE else None
    header_end = end if end != _MAX_DATE else None

    markdown = to_markdown(symbol, rows, chips, start=header_start, end=header_end)
    instruction = build_prompt(symbol, prompt)
    payload = f"{instruction}\n\n{markdown}"

    output = run(agent_cmd, payload)
    typer.echo(output)
